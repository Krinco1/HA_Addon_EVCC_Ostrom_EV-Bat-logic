"""
Shadow Reinforcement Learning Agent — v5.0

Changes from v4:
  - Action space: 7×5 = 35 (was 4×4 = 16)
  - State space: 31-d (was 25-d) — includes price percentiles + solar forecast
  - Q-table reset on load if state_size mismatch (migration guard)
  - _compute_limits() uses percentile thresholds from SystemState
"""

import json
import os
import random
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import Config, RL_MODEL_PATH, RL_MEMORY_PATH
from logging_util import log
from state import Action, SystemState


# =============================================================================
# Replay Memory (unchanged from v4)
# =============================================================================

class ReplayMemory:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.memory: List[Optional[Tuple]] = []
        self.priorities: List[Optional[float]] = []
        self.position = 0

    def push(self, state, action, reward, next_state, done, priority: float = 1.0):
        if len(self.memory) < self.capacity:
            self.memory.append(None)
            self.priorities.append(None)
        self.memory[self.position] = (state, action, reward, next_state, done)
        self.priorities[self.position] = priority
        self.position = (self.position + 1) % self.capacity

    def sample(self, batch_size: int) -> List[Tuple]:
        n = len(self.memory)
        if n < batch_size:
            return [m for m in self.memory if m is not None]
        probs = np.array(
            [p for p in self.priorities[:n] if p is not None], dtype=np.float32
        )
        probs /= probs.sum()
        indices = np.random.choice(n, batch_size, p=probs, replace=False)
        return [self.memory[i] for i in indices]

    def __len__(self):
        return len(self.memory)

    def save(self, path: str):
        try:
            data = {
                "memory": [
                    (
                        s.tolist() if isinstance(s, np.ndarray) else s,
                        a, r,
                        ns.tolist() if isinstance(ns, np.ndarray) else ns,
                        d,
                    )
                    for s, a, r, ns, d in self.memory
                    if s is not None
                ],
                "priorities": [p for p in self.priorities if p is not None],
                "position": self.position,
            }
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            log("warning", f"Could not save replay memory: {e}")

    def load(self, path: str):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.memory = [
                (np.array(s), a, r, np.array(ns), d)
                for s, a, r, ns, d in data.get("memory", [])
            ]
            self.priorities = data.get("priorities", [1.0] * len(self.memory))
            self.position = data.get("position", 0)
        except Exception:
            pass


# =============================================================================
# DQN Agent — v5
# =============================================================================

class DQNAgent:
    """Q-table DQN with 7-battery × 5-EV = 35 actions and 31-d state."""

    N_BATTERY_ACTIONS = 7
    N_EV_ACTIONS = 5
    N_ACTIONS = N_BATTERY_ACTIONS * N_EV_ACTIONS  # 35

    STATE_SIZE = 31  # v5 extended state vector

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.q_table: Dict[Tuple, np.ndarray] = defaultdict(
            lambda: np.zeros(self.N_ACTIONS)
        )
        self.memory = ReplayMemory(cfg.rl_memory_size)
        self.epsilon = cfg.rl_epsilon_start
        self.learning_rate = cfg.rl_learning_rate
        self.gamma = cfg.rl_discount_factor
        self.total_steps = 0
        self.training_episodes = 0
        self.load()

    # ------------------------------------------------------------------
    # State discretisation (extended for 31-d)
    # ------------------------------------------------------------------

    def _discretize_state(self, state_vec: np.ndarray) -> Tuple:
        # First 13 features: same bins as v4
        bins_13 = [5, 3, 3, 5, 3, 3, 2, 3, 3, 4, 4, 4, 4]
        discretized = []
        for val, n_bins in zip(state_vec[:13], bins_13):
            discretized.append(int(np.clip(val * n_bins, 0, n_bins - 1)))

        # Price/PV forecast summary (features 13-24, same as v4)
        discretized.append(int(np.clip(np.mean(state_vec[13:19]) * 5, 0, 4)))
        discretized.append(int(np.clip(np.mean(state_vec[19:25]) * 3, 0, 2)))

        # v5 new features (25-30): 3 bins each
        for val in state_vec[25:31]:
            discretized.append(int(np.clip(val * 3, 0, 2)))

        return tuple(discretized)

    def _action_to_tuple(self, idx: int) -> Tuple[int, int]:
        return idx // self.N_EV_ACTIONS, idx % self.N_EV_ACTIONS

    def _tuple_to_action(self, battery: int, ev: int) -> int:
        return battery * self.N_EV_ACTIONS + ev

    # ------------------------------------------------------------------
    # Action selection
    # ------------------------------------------------------------------

    def select_action(self, state: SystemState, explore: bool = True) -> Action:
        state_vec = state.to_vector()
        state_key = self._discretize_state(state_vec)

        if explore and random.random() < self.epsilon:
            action_idx = random.randint(0, self.N_ACTIONS - 1)
        else:
            action_idx = int(np.argmax(self.q_table[state_key]))

        bat, ev = self._action_to_tuple(action_idx)
        action = Action(battery_action=bat, ev_action=ev)
        self._compute_limits(action, state)
        return action

    def _compute_limits(self, action: Action, state: SystemState):
        """Map action indices to EUR/kWh thresholds using percentile context."""
        cfg_max_bat = self.cfg.battery_max_price_ct / 100
        cfg_max_ev = self.cfg.ev_max_price_ct / 100

        p = state.price_percentiles  # may be empty on first steps

        bat_map = {
            0: None,                                                  # hold
            1: min(p.get(20, state.current_price), cfg_max_bat),     # P20
            2: min(p.get(40, state.current_price), cfg_max_bat),     # P40
            3: min(p.get(60, state.current_price), cfg_max_bat),     # P60
            4: cfg_max_bat,                                           # max
            5: 0.0,                                                   # PV only
            6: None,                                                  # discharge
        }
        action.battery_limit_eur = bat_map.get(action.battery_action)

        ev_map = {
            0: None,                                                  # no charge
            1: min(p.get(30, state.current_price), cfg_max_ev),      # P30
            2: min(p.get(60, state.current_price), cfg_max_ev),      # P60
            3: cfg_max_ev,                                            # max
            4: 0.0,                                                   # PV only
        }
        action.ev_limit_eur = ev_map.get(action.ev_action)

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    def imitation_learn(self, state: SystemState, expert_action: Action):
        state_vec = state.to_vector()
        state_key = self._discretize_state(state_vec)
        expert_idx = self._tuple_to_action(
            expert_action.battery_action, expert_action.ev_action
        )
        self.q_table[state_key][expert_idx] += self.learning_rate * 2
        self.total_steps += 1

    def learn(
        self,
        state: SystemState,
        action: Action,
        reward: float,
        next_state: SystemState,
        done: bool,
        priority: float = 1.0,
    ):
        state_vec = state.to_vector()
        next_vec = next_state.to_vector()
        action_idx = self._tuple_to_action(action.battery_action, action.ev_action)

        self.memory.push(state_vec, action_idx, reward, next_vec, done, priority)

        skey = self._discretize_state(state_vec)
        nkey = self._discretize_state(next_vec)
        current_q = self.q_table[skey][action_idx]
        target_q = reward if done else reward + self.gamma * np.max(self.q_table[nkey])
        self.q_table[skey][action_idx] += self.learning_rate * (target_q - current_q)

        self.epsilon = max(
            self.cfg.rl_epsilon_min, self.epsilon * self.cfg.rl_epsilon_decay
        )
        self.total_steps += 1

        if len(self.memory) >= self.cfg.rl_batch_size and self.total_steps % 10 == 0:
            self._replay_learn()

    def _replay_learn(self):
        for sv, ai, r, nsv, d in self.memory.sample(self.cfg.rl_batch_size):
            sk = self._discretize_state(sv)
            nk = self._discretize_state(nsv)
            target = r if d else r + self.gamma * np.max(self.q_table[nk])
            self.q_table[sk][ai] += (
                self.learning_rate * 0.5 * (target - self.q_table[sk][ai])
            )

    # ------------------------------------------------------------------
    # Persistence — with migration guard
    # ------------------------------------------------------------------

    def save(self):
        try:
            q_ser = {
                ",".join(map(str, k)): v.tolist() for k, v in self.q_table.items()
            }
            data = {
                "q_table": q_ser,
                "epsilon": self.epsilon,
                "total_steps": self.total_steps,
                "training_episodes": self.training_episodes,
                "state_size": self.STATE_SIZE,
                "n_actions": self.N_ACTIONS,
                "saved_at": datetime.now().isoformat(),
            }
            with open(RL_MODEL_PATH, "w") as f:
                json.dump(data, f, indent=2)
            self.memory.save(RL_MEMORY_PATH)
            log(
                "info",
                f"RL model saved (steps={self.total_steps}, "
                f"q_states={len(self.q_table)}, ε={self.epsilon:.3f})",
            )
        except Exception as e:
            log("error", f"Could not save RL model: {e}")

    def load(self) -> bool:
        if not os.path.exists(RL_MODEL_PATH):
            log("info", "No existing RL model found, starting fresh (v5 action space)")
            return False
        try:
            with open(RL_MODEL_PATH, "r") as f:
                data = json.load(f)

            # Migration guard: if saved model has different action/state size → reset
            saved_n_actions = data.get("n_actions", 16)
            saved_state_size = data.get("state_size", 25)
            if saved_n_actions != self.N_ACTIONS or saved_state_size != self.STATE_SIZE:
                log(
                    "warning",
                    f"RL model incompatible (actions={saved_n_actions} vs {self.N_ACTIONS}, "
                    f"state={saved_state_size} vs {self.STATE_SIZE}) → resetting Q-table",
                )
                return False

            self.q_table = defaultdict(lambda: np.zeros(self.N_ACTIONS))
            for ks, v in data.get("q_table", {}).items():
                try:
                    key = tuple(map(int, ks.split(",")))
                    arr = np.array(v)
                    if len(arr) == self.N_ACTIONS:
                        self.q_table[key] = arr
                except Exception:
                    continue

            self.epsilon = data.get("epsilon", self.cfg.rl_epsilon_start)
            self.total_steps = data.get("total_steps", 0)
            self.training_episodes = data.get("training_episodes", 0)
            self.memory.load(RL_MEMORY_PATH)
            log(
                "info",
                f"✓ RL model loaded v5 (steps={self.total_steps}, "
                f"q_states={len(self.q_table)}, ε={self.epsilon:.3f})",
            )
            return True
        except Exception as e:
            log("warning", f"Could not load RL model: {e}")
            return False

    def bootstrap_from_influxdb(self, influx, hours: int = 168) -> int:
        """Bootstrap Q-table from historical InfluxDB data."""
        try:
            data = influx.get_history_hours(hours)
            if not data:
                return 0
            learned = 0
            prev = None
            for point in data:
                try:
                    battery_soc = point.get("battery_soc") or 50
                    price = point.get("price") or 0.30
                    state_vec = np.zeros(self.STATE_SIZE)
                    state_vec[0] = battery_soc / 100
                    state_vec[3] = price / 0.5
                    if prev:
                        delta = battery_soc - (prev.get("battery_soc") or 50)
                        prev_price = prev.get("price") or 0.30
                        if delta > 2 and prev_price < 0.25:
                            # Was charging at cheap price → good
                            aidx = self._tuple_to_action(2, 0)  # charge_p40
                            reward = 0.5
                        elif delta < -2 and prev_price > 0.30:
                            aidx = self._tuple_to_action(6, 0)  # discharge
                            reward = 0.3
                        elif delta > 2 and prev_price > 0.35:
                            aidx = self._tuple_to_action(2, 0)
                            reward = -0.3
                        else:
                            aidx = self._tuple_to_action(0, 0)
                            reward = 0
                        prev_vec = np.zeros(self.STATE_SIZE)
                        prev_vec[0] = (prev.get("battery_soc") or 50) / 100
                        prev_vec[3] = prev_price / 0.5
                        sk = self._discretize_state(prev_vec)
                        nk = self._discretize_state(state_vec)
                        target = reward + self.gamma * np.max(self.q_table[nk])
                        self.q_table[sk][aidx] += (
                            self.learning_rate * 0.3 * (target - self.q_table[sk][aidx])
                        )
                        learned += 1
                    prev = point
                except Exception:
                    continue
            if learned:
                log("info", f"✓ Bootstrapped {learned} experiences from InfluxDB")
            return learned
        except Exception as e:
            log("warning", f"Bootstrap from InfluxDB failed: {e}")
            return 0
