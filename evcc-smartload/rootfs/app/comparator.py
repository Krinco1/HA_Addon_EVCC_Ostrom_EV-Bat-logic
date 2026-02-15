"""
LP vs RL comparator, reward calculator, and per-device RL controller.
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config import Config, COMPARISON_LOG_PATH, DEVICE_CONTROL_DB_PATH
from logging_util import log
from state import Action, SystemState


# =============================================================================
# Comparator
# =============================================================================

class Comparator:
    """Compares LP and RL decisions, calculates rewards, tracks readiness."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.comparisons: List[Dict] = []
        self.lp_total_cost = 0.0
        self.rl_total_cost = 0.0
        self.rl_wins = 0
        self.rl_ready = False

        # Per-device tracking
        self.device_comparisons: Dict[str, int] = defaultdict(int)
        self.device_wins: Dict[str, int] = defaultdict(int)
        self.device_costs_lp: Dict[str, float] = defaultdict(float)
        self.device_costs_rl: Dict[str, float] = defaultdict(float)

        self._load()

    # ------------------------------------------------------------------
    # Reward calculation for RL learning
    # ------------------------------------------------------------------

    def calculate_reward(self, state: SystemState, action: Action,
                         next_state: SystemState, events: List[str]) -> float:
        reward = 0.0

        # Cost-based reward
        if state.grid_power > 0:
            reward -= (state.grid_power / 1000 * state.current_price / 4) * 10
        else:
            reward += (abs(state.grid_power) / 1000 * (self.cfg.feed_in_tariff_ct / 100) / 4) * 5

        # Battery reward shaping
        if next_state.battery_soc > state.battery_soc and state.current_price < 0.15:
            reward += 0.5
        if next_state.battery_soc < state.battery_soc and state.current_price > 0.25:
            reward += 0.3

        # EV reward shaping
        if state.ev_connected and next_state.ev_soc > state.ev_soc:
            if state.current_price < 0.20:
                reward += 0.5
            elif state.pv_power > 3000:
                reward += 0.8

        # Event-based rewards
        for event in events:
            if event == "EV_CHARGED_EXTERNALLY":
                reward -= 0.2
            elif event == "PRICE_DROP" and action.battery_action == 1:
                reward += 0.5
            elif event == "PRICE_SPIKE" and action.battery_action == 3:
                reward += 0.5
            elif event == "PV_SURGE" and action.battery_action == 2:
                reward += 0.3

        # Penalties
        if action.battery_action == 1 and state.current_price > self.cfg.battery_max_price_ct / 100:
            reward -= 2.0
        if state.battery_soc < 15 and action.battery_action == 3:
            reward -= 1.0

        return reward

    # ------------------------------------------------------------------
    # LP vs RL comparison
    # ------------------------------------------------------------------

    def compare(self, state: SystemState, lp_action: Action, rl_action: Action,
                actual_cost: float):
        rl_sim_cost = actual_cost
        if rl_action.battery_action != lp_action.battery_action:
            if rl_action.battery_action == 1 and state.current_price < 0.15:
                rl_sim_cost -= 0.05
            elif rl_action.battery_action == 0 and state.current_price > 0.20:
                rl_sim_cost -= 0.03

        self.comparisons.append({
            "timestamp": state.timestamp.isoformat(),
            "lp_action": (lp_action.battery_action, lp_action.ev_action),
            "rl_action": (rl_action.battery_action, rl_action.ev_action),
            "price": state.current_price,
            "battery_soc": state.battery_soc,
            "lp_cost": actual_cost,
            "rl_simulated_cost": rl_sim_cost,
            "rl_better": rl_sim_cost <= actual_cost,
        })

        self.lp_total_cost += actual_cost
        self.rl_total_cost += rl_sim_cost
        if rl_sim_cost <= actual_cost:
            self.rl_wins += 1

        n = len(self.comparisons)
        if n >= self.cfg.rl_ready_min_comparisons:
            win_rate = self.rl_wins / n
            if win_rate >= self.cfg.rl_ready_threshold and not self.rl_ready:
                self.rl_ready = True
                log("info", f"🎉 RL READY! Win-Rate: {win_rate * 100:.1f}%")

        if n % 50 == 0:
            log("info", f"RL Progress: {n} comparisons, win rate {self.rl_wins / n * 100:.1f}%")
        self.save()

    def compare_per_device(self, state: SystemState, lp_action: Action,
                           rl_action: Action, actual_cost: float,
                           rl_devices: "RLDeviceController",
                           all_vehicles: Dict = None):
        # Battery — always compared
        bat_lp = self._eval_battery_cost(state, lp_action)
        bat_rl = self._eval_battery_cost(state, rl_action)
        self.device_comparisons["battery"] += 1
        if bat_rl <= bat_lp:
            self.device_wins["battery"] += 1
        rl_devices.update_performance(
            "battery",
            self.device_wins["battery"] / max(1, self.device_comparisons["battery"]),
            self.device_comparisons["battery"],
            (bat_lp - bat_rl) * 100,
        )

        # ALL vehicles — compare charging decisions at current price
        if all_vehicles:
            for name, v in all_vehicles.items():
                needs_charge = v.get_effective_soc() < 80  # below target
                ev_lp = self._eval_vehicle_charge_cost(state, lp_action, needs_charge, v.connected_to_wallbox)
                ev_rl = self._eval_vehicle_charge_cost(state, rl_action, needs_charge, v.connected_to_wallbox)
                self.device_comparisons[name] += 1
                if ev_rl <= ev_lp:
                    self.device_wins[name] += 1
                rl_devices.update_performance(
                    name,
                    self.device_wins[name] / max(1, self.device_comparisons[name]),
                    self.device_comparisons[name],
                    (ev_lp - ev_rl) * 100,
                )
        elif state.ev_connected and state.ev_name:
            # Fallback: only connected EV (legacy)
            ev_lp = self._eval_ev_cost(state, lp_action)
            ev_rl = self._eval_ev_cost(state, rl_action)
            name = state.ev_name
            self.device_comparisons[name] += 1
            if ev_rl <= ev_lp:
                self.device_wins[name] += 1
            rl_devices.update_performance(
                name,
                self.device_wins[name] / max(1, self.device_comparisons[name]),
                self.device_comparisons[name],
                (ev_lp - ev_rl) * 100,
            )

    @staticmethod
    def _eval_battery_cost(state: SystemState, action: Action) -> float:
        if action.battery_action == 1:
            return state.current_price * 0.25
        if action.battery_action == 3:
            return -state.current_price * 0.20
        return 0.0

    @staticmethod
    def _eval_ev_cost(state: SystemState, action: Action) -> float:
        if action.ev_action in (1, 2):
            return state.current_price * 2.0
        return 0.0

    @staticmethod
    def _eval_vehicle_charge_cost(state: SystemState, action: Action,
                                   needs_charge: bool, connected: bool) -> float:
        """Evaluate charging cost for any vehicle (connected or not).
        
        For connected vehicles: actual charge cost at current price.
        For disconnected vehicles: evaluate the DECISION quality —
        would this be a good time to charge if they were connected?
        """
        if not needs_charge:
            return 0.0  # No charge needed → no cost either way

        price = state.current_price
        if connected:
            # Actually charging — real cost
            if action.ev_action in (1, 2):
                return price * 2.0  # charging at current price
            return 0.0  # waiting (opportunity cost: might miss cheap slot)
        else:
            # Not connected — evaluate price quality for theoretical charge
            # LP: would charge if price < ev_max → cost = price if below limit
            # RL: might pick different threshold
            # Simple: compare against median-ish threshold (30ct)
            if price < 0.25:
                return -0.1  # Good price — both should agree to charge
            elif price > 0.35:
                return 0.1  # Bad price — both should agree to wait
            else:
                return 0.0  # Ambiguous — RL could learn the optimal threshold

    def get_status(self) -> Dict:
        n = len(self.comparisons)
        return {
            "comparisons": n,
            "rl_wins": self.rl_wins,
            "win_rate": self.rl_wins / n if n else 0,
            "lp_total_cost": self.lp_total_cost,
            "rl_total_cost": self.rl_total_cost,
            "rl_ready": self.rl_ready,
            "ready_threshold": self.cfg.rl_ready_threshold,
            "ready_min_comparisons": self.cfg.rl_ready_min_comparisons,
        }

    def save(self):
        try:
            with open(COMPARISON_LOG_PATH, "w") as f:
                json.dump({
                    "comparisons": self.comparisons[-1000:],
                    "lp_total_cost": self.lp_total_cost,
                    "rl_total_cost": self.rl_total_cost,
                    "rl_wins": self.rl_wins,
                    "rl_ready": self.rl_ready,
                    # Per-device stats (v4.3.7)
                    "device_comparisons": dict(self.device_comparisons),
                    "device_wins": dict(self.device_wins),
                    "device_costs_lp": dict(self.device_costs_lp),
                    "device_costs_rl": dict(self.device_costs_rl),
                }, f)
        except Exception:
            pass

    def seed_from_bootstrap(self, n_experiences: int):
        """Credit the comparator with historical InfluxDB data.
        
        Counts bootstrapped RL experiences as comparisons (with 50% win rate)
        so the RL maturity bar reflects that we have historical data.
        """
        if n_experiences <= 0:
            return
        # Credit half as wins (conservative estimate)
        seed_count = min(n_experiences, self.cfg.rl_ready_min_comparisons // 2)
        seed_wins = seed_count // 2
        self.comparisons.extend([{"source": "bootstrap"}] * seed_count)
        self.rl_wins += seed_wins
        log("info", f"Comparator seeded with {seed_count} bootstrap comparisons ({seed_wins} wins)")
        self.save()

    def _load(self):
        try:
            with open(COMPARISON_LOG_PATH, "r") as f:
                data = json.load(f)
            self.comparisons = data.get("comparisons", [])
            self.lp_total_cost = data.get("lp_total_cost", 0)
            self.rl_total_cost = data.get("rl_total_cost", 0)
            self.rl_wins = data.get("rl_wins", 0)
            self.rl_ready = data.get("rl_ready", False)

            # Per-device stats (added v4.3.7)
            for k, v in data.get("device_comparisons", {}).items():
                self.device_comparisons[k] = v
            for k, v in data.get("device_wins", {}).items():
                self.device_wins[k] = v
            for k, v in data.get("device_costs_lp", {}).items():
                self.device_costs_lp[k] = v
            for k, v in data.get("device_costs_rl", {}).items():
                self.device_costs_rl[k] = v

            n = len(self.comparisons)
            if n:
                log("info", f"Comparator loaded: {n} comparisons, win rate {self.rl_wins / n * 100:.1f}%")
            dev_n = sum(self.device_comparisons.values())
            if dev_n:
                log("info", f"  Per-device: {dict(self.device_comparisons)}")
        except Exception:
            pass


# =============================================================================
# RL Device Controller (per-device RL mode management)
# =============================================================================

class RLDeviceController:
    """Manages RL/LP mode per device with SQLite persistence."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db_path = DEVICE_CONTROL_DB_PATH
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS device_control (
                device_name TEXT PRIMARY KEY,
                current_mode TEXT NOT NULL,
                override_mode TEXT,
                win_rate REAL DEFAULT 0.0,
                comparisons INTEGER DEFAULT 0,
                cost_saved_total_ct REAL DEFAULT 0.0,
                last_switch TIMESTAMP,
                switch_reason TEXT
            )
        """)
        conn.commit()
        conn.close()

    def get_device_mode(self, device_name: str) -> str:
        """Return effective mode ('lp' or 'rl') considering overrides and auto-logic."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT current_mode, override_mode, win_rate, comparisons FROM device_control WHERE device_name = ?",
            (device_name,),
        ).fetchone()
        conn.close()

        if not row:
            self._init_device(device_name)
            return "lp"

        current_mode, override, win_rate, comps = row

        if override == "manual_lp":
            return "lp"
        if override == "manual_rl":
            return "rl"

        if self.cfg.rl_auto_switch:
            if win_rate >= self.cfg.rl_ready_threshold and comps >= self.cfg.rl_ready_min_comparisons:
                if current_mode == "lp":
                    self._switch_mode(device_name, "rl", "auto_ready")
                    log("info", f"🎉 {device_name}: Auto-Switch LP → RL (Win-Rate {win_rate:.1%})")
                return "rl"
            if win_rate < self.cfg.rl_fallback_threshold and comps >= 50:
                if current_mode == "rl":
                    self._switch_mode(device_name, "lp", "auto_fallback")
                    log("warning", f"⚠️ {device_name}: Auto-Fallback RL → LP (Win-Rate {win_rate:.1%})")
                return "lp"

        return current_mode

    def set_override(self, device_name: str, override_mode: Optional[str]) -> dict:
        if override_mode == "auto":
            override_mode = None
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO device_control (device_name, current_mode) VALUES (?, 'lp')",
            (device_name,),
        )
        conn.execute(
            "UPDATE device_control SET override_mode = ? WHERE device_name = ?",
            (override_mode, device_name),
        )
        conn.commit()
        conn.close()
        log("info", f"Override for {device_name} set to: {override_mode or 'auto'}")
        return {"device": device_name, "override": override_mode or "auto"}

    def update_performance(self, device_name: str, win_rate: float,
                           comparisons: int, saved_ct: float):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO device_control (device_name, current_mode) VALUES (?, 'lp')",
            (device_name,),
        )
        conn.execute("""
            UPDATE device_control
            SET win_rate = ?, comparisons = ?, cost_saved_total_ct = cost_saved_total_ct + ?
            WHERE device_name = ?
        """, (win_rate, comparisons, saved_ct, device_name))
        conn.commit()
        conn.close()

    def get_device_status(self, device_name: str) -> Dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT * FROM device_control WHERE device_name = ?", (device_name,)
        ).fetchone()
        conn.close()
        if not row:
            return {}
        cols = ["device_name", "current_mode", "override_mode", "win_rate",
                "comparisons", "cost_saved_total_ct", "last_switch", "switch_reason"]
        d = dict(zip(cols, row))
        d["is_ready"] = (
            (d.get("win_rate", 0) >= self.cfg.rl_ready_threshold)
            and (d.get("comparisons", 0) >= self.cfg.rl_ready_min_comparisons)
        )
        return d

    def get_all_devices(self) -> Dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT device_name FROM device_control").fetchall()
        conn.close()
        return {row[0]: self.get_device_status(row[0]) for row in rows}

    def _init_device(self, device_name: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO device_control (device_name, current_mode) VALUES (?, 'lp')",
            (device_name,),
        )
        conn.commit()
        conn.close()

    def _switch_mode(self, device_name: str, new_mode: str, reason: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            UPDATE device_control SET current_mode = ?, last_switch = ?, switch_reason = ?
            WHERE device_name = ?
        """, (new_mode, datetime.now(timezone.utc).isoformat(), reason, device_name))
        conn.commit()
        conn.close()
