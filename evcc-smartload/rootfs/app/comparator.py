"""
LP vs RL comparator, reward calculator, and per-device RL controller — v6.0 (Phase 8)

Changes from v5:
  - compare_residual(): slot-0 cost comparison for ResidualRLAgent delta corrections
  - get_recent_comparisons(): rolling 7-day window for residual comparison entries
  - cumulative_savings_eur(): sum of (plan_cost - actual_cost) over all residual entries
  - avg_daily_savings(): average daily savings over last 7 days
  - Persistence version bumped to 2; graceful fallback for old v1 format
  - Backward-compatible: existing compare(), get_status(), /comparisons endpoint unchanged
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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

        self.device_comparisons: Dict[str, int] = defaultdict(int)
        self.device_wins: Dict[str, int] = defaultdict(int)
        self.device_costs_lp: Dict[str, float] = defaultdict(float)
        self.device_costs_rl: Dict[str, float] = defaultdict(float)

        # Phase 8: residual comparison entries (slot-0 cost accounting)
        self._residual_comparisons: List[Dict] = []

        self._load()

    # ------------------------------------------------------------------
    # Reward calculation — v5 action space aware
    # ------------------------------------------------------------------

    def calculate_reward(
        self,
        state: SystemState,
        action: Action,
        next_state: SystemState,
        events: List[str],
    ) -> float:
        reward = 0.0
        price = state.current_price
        p20 = state.price_percentiles.get(20, price)
        p60 = state.price_percentiles.get(60, price)

        # Grid cost / feed-in benefit
        if state.grid_power > 0:
            reward -= (state.grid_power / 1000 * price / 4) * 10
        else:
            reward += (
                abs(state.grid_power) / 1000 * (self.cfg.feed_in_tariff_ct / 100) / 4
            ) * 5

        # --- Battery reward shaping (v5: action 0-6) ---
        bat = action.battery_action

        # Charge actions 1-4: reward proportional to price advantage
        if bat in (1, 2, 3, 4) and next_state.battery_soc > state.battery_soc:
            price_advantage = p60 - price  # positive when price is below median
            if price <= p20:
                reward += 0.8   # charged at excellent price
            elif price <= p60:
                reward += 0.3   # charged at decent price
            else:
                reward -= 0.5   # charged at expensive price
        # Hold at low prices: mild penalty (missed cheap charging)
        elif bat == 0 and price <= p20 and state.battery_soc < 70:
            reward -= 0.2
        # Discharge (action 6): reward if price is high
        elif bat == 6 and next_state.battery_soc < state.battery_soc:
            if price > p60:
                reward += 0.5   # discharged at high price → good
            else:
                reward -= 0.3   # discharged at cheap time → wasteful

        # --- EV reward shaping (v5: action 0-4) ---
        ev = action.ev_action
        if state.ev_connected and next_state.ev_soc > state.ev_soc:
            if ev == 4 or price < 0.01:           # PV charging
                reward += 0.8
            elif price <= p20:                    # P20 slot
                reward += 0.6
            elif price <= p60:                    # P60 slot
                reward += 0.3
            else:
                reward -= 0.3                     # charging at high price

        # --- Event-based bonuses ---
        for event in events:
            if event == "EV_CHARGED_EXTERNALLY":
                reward -= 0.2
            elif event == "PRICE_DROP" and bat in (1, 2):
                reward += 0.5
            elif event == "PRICE_SPIKE" and bat == 6:
                reward += 0.5
            elif event == "PV_SURGE" and bat == 5:
                reward += 0.3

        # --- Hard penalties ---
        if bat in (1, 2, 3, 4) and price > self.cfg.battery_max_price_ct / 100:
            reward -= 2.0
        if state.battery_soc < 15 and bat == 6:
            reward -= 1.0

        return reward

    # ------------------------------------------------------------------
    # LP vs RL comparison
    # ------------------------------------------------------------------

    def compare(
        self,
        state: SystemState,
        lp_action: Action,
        rl_action: Action,
        actual_cost: float,
    ):
        price = state.current_price
        p20 = state.price_percentiles.get(20, price)
        p60 = state.price_percentiles.get(60, price)

        rl_sim_cost = actual_cost
        # RL charged at cheap price → simulated savings
        if rl_action.battery_action in (1, 2) and price <= p20:
            rl_sim_cost -= 0.05
        elif rl_action.battery_action == 0 and lp_action.battery_action in (1, 2) and price > p60:
            rl_sim_cost -= 0.03  # RL correctly avoided expensive grid
        elif rl_action.battery_action == 6 and price > p60:
            rl_sim_cost -= 0.04  # RL discharged at expensive price

        self.comparisons.append({
            "timestamp": state.timestamp.isoformat(),
            "lp_action": (lp_action.battery_action, lp_action.ev_action),
            "rl_action": (rl_action.battery_action, rl_action.ev_action),
            "price": price,
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

    def compare_per_device(
        self,
        state: SystemState,
        lp_action: Action,
        rl_action: Action,
        actual_cost: float,
        rl_devices: "RLDeviceController",
        all_vehicles: Dict = None,
    ):
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

        if all_vehicles:
            for name, v in all_vehicles.items():
                needs_charge = v.get_effective_soc() < 80
                ev_lp = self._eval_vehicle_charge_cost(
                    state, lp_action, needs_charge, v.connected_to_wallbox
                )
                ev_rl = self._eval_vehicle_charge_cost(
                    state, rl_action, needs_charge, v.connected_to_wallbox
                )
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
        """Cost proxy for battery action at current price."""
        bat = action.battery_action
        p = state.current_price
        p60 = state.price_percentiles.get(60, p)
        if bat in (1, 2, 3, 4):
            # Charging: cost = price × 15-min energy ≈ 4.3kW / 4
            return p * 1.075
        if bat == 6:
            # Discharge: benefit = price × energy, minus feed-in opportunity cost
            return -p * 0.86 if p > p60 else 0.0
        return 0.0  # hold / PV

    @staticmethod
    def _eval_ev_cost(state: SystemState, action: Action) -> float:
        if action.ev_action in (1, 2, 3):
            return state.current_price * 2.0
        return 0.0

    @staticmethod
    def _eval_vehicle_charge_cost(
        state: SystemState,
        action: Action,
        needs_charge: bool,
        connected: bool,
    ) -> float:
        if not needs_charge:
            return 0.0
        price = state.current_price
        p60 = state.price_percentiles.get(60, price)
        if connected:
            if action.ev_action in (1, 2, 3):
                return price * 2.0
            return 0.0
        else:
            if price < 0.25:
                return -0.1
            elif price > 0.35:
                return 0.1
            return 0.0

    # ------------------------------------------------------------------
    # ResidualRLAgent slot-0 cost comparisons (Phase 8)
    # ------------------------------------------------------------------

    def compare_residual(
        self,
        plan_slot0_cost_eur: float,
        actual_slot0_cost_eur: float,
        delta_bat_ct: float,
        delta_ev_ct: float,
    ):
        """Record a residual RL comparison using slot-0 energy cost accounting.

        CRITICAL (Pitfall 2 from research):
        plan_slot0_cost_eur MUST be the slot-0 grid energy cost:
            slot0.price_eur_kwh * (slot0.bat_charge_kw + slot0.ev_charge_kw) * 0.25
        Do NOT use plan.solver_fun — that is the full 24h horizon LP objective.
        Comparing a 24h cost against a 15-min actual cost produces nonsense rewards.

        Args:
            plan_slot0_cost_eur:   Slot-0 grid energy cost from LP plan (15-min, EUR).
            actual_slot0_cost_eur: Actual slot-0 grid energy cost incurred (15-min, EUR).
            delta_bat_ct:          Battery delta correction applied (ct/kWh).
            delta_ev_ct:           EV delta correction applied (ct/kWh).
        """
        rl_better = actual_slot0_cost_eur < plan_slot0_cost_eur
        entry: Dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "plan_cost_eur": plan_slot0_cost_eur,
            "actual_cost_eur": actual_slot0_cost_eur,
            "rl_better": rl_better,
            "delta_bat_ct": delta_bat_ct,
            "delta_ev_ct": delta_ev_ct,
        }
        self._residual_comparisons.append(entry)
        self.save()

    def get_recent_comparisons(self, days: int = 7) -> List[Dict]:
        """Return residual comparison entries from the last `days` days.

        Each entry: {timestamp, plan_cost_eur, actual_cost_eur, rl_better,
                     delta_bat_ct, delta_ev_ct}

        Args:
            days: Rolling window in days (default 7).

        Returns:
            List of comparison dicts within the window.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = []
        for entry in self._residual_comparisons:
            try:
                ts_str = entry.get("timestamp", "")
                if ts_str.endswith("Z"):
                    ts_str = ts_str.replace("Z", "+00:00")
                ts = datetime.fromisoformat(ts_str)
                if ts >= cutoff:
                    result.append(entry)
            except Exception:
                continue
        return result

    def cumulative_savings_eur(self) -> float:
        """Return cumulative savings over all recorded residual comparisons.

        savings = sum(plan_cost - actual_cost) for all entries.
        Positive means RL corrections collectively saved money vs the unmodified LP plan.
        Prefix with 'ca.' in dashboard (per Phase 06-01 convention) to signal it's
        a simulated estimate, not a directly metered value.
        """
        return sum(
            e.get("plan_cost_eur", 0.0) - e.get("actual_cost_eur", 0.0)
            for e in self._residual_comparisons
        )

    def avg_daily_savings(self, days: int = 7) -> Optional[float]:
        """Return average daily savings over the last `days` days.

        Returns None if fewer than 1 day of data exists (avoids misleading averages
        from sparse early data — Pitfall 7 from research).

        Args:
            days: Rolling window in days (default 7).
        """
        recent = self.get_recent_comparisons(days=days)
        if not recent:
            return None

        # Determine actual span in days
        try:
            timestamps = []
            for e in recent:
                ts_str = e.get("timestamp", "")
                if ts_str.endswith("Z"):
                    ts_str = ts_str.replace("Z", "+00:00")
                timestamps.append(datetime.fromisoformat(ts_str))
            if not timestamps:
                return None
            span_days = max(1.0, (max(timestamps) - min(timestamps)).total_seconds() / 86400)
            if span_days < 1.0:
                return None  # less than 1 day of data
            total_savings = sum(
                e.get("plan_cost_eur", 0.0) - e.get("actual_cost_eur", 0.0)
                for e in recent
            )
            return total_savings / span_days
        except Exception:
            return None

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
                json.dump(
                    {
                        "version": 2,
                        "comparisons": self.comparisons[-1000:],
                        "lp_total_cost": self.lp_total_cost,
                        "rl_total_cost": self.rl_total_cost,
                        "rl_wins": self.rl_wins,
                        "rl_ready": self.rl_ready,
                        "device_comparisons": dict(self.device_comparisons),
                        "device_wins": dict(self.device_wins),
                        "device_costs_lp": dict(self.device_costs_lp),
                        "device_costs_rl": dict(self.device_costs_rl),
                        "residual_comparisons": self._residual_comparisons[-2000:],
                    },
                    f,
                )
        except Exception:
            pass

    def seed_from_bootstrap(self, n_experiences: int):
        if n_experiences <= 0:
            return
        seed_count = min(n_experiences, self.cfg.rl_ready_min_comparisons // 2)
        seed_wins = seed_count // 2
        self.comparisons.extend([{"source": "bootstrap"}] * seed_count)
        self.rl_wins += seed_wins
        log("info", f"Comparator seeded with {seed_count} bootstrap comparisons")
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
            for k, v in data.get("device_comparisons", {}).items():
                self.device_comparisons[k] = v
            for k, v in data.get("device_wins", {}).items():
                self.device_wins[k] = v
            for k, v in data.get("device_costs_lp", {}).items():
                self.device_costs_lp[k] = v
            for k, v in data.get("device_costs_rl", {}).items():
                self.device_costs_rl[k] = v

            # Phase 8: residual comparisons — graceful fallback for v1 format
            saved_version = data.get("version", 1)
            if saved_version >= 2:
                self._residual_comparisons = data.get("residual_comparisons", [])
            else:
                # Old format (v1): no residual data — start fresh, keep legacy data
                self._residual_comparisons = []
                log("info", "Comparator: v1 format detected, residual entries reset (legacy data kept)")

            n = len(self.comparisons)
            if n:
                log("info", f"Comparator loaded: {n} comparisons, win rate {self.rl_wins / n * 100:.1f}%")
        except Exception:
            pass


# =============================================================================
# RL Device Controller (unchanged from v4 except import path)
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

    def dedup_case_duplicates(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT device_name, comparisons FROM device_control"
        ).fetchall()
        conn.close()
        groups: Dict[str, list] = {}
        for name, comps in rows:
            key = name.lower()
            if key not in groups:
                groups[key] = []
            groups[key].append((name, comps or 0))
        for key, entries in groups.items():
            if len(entries) <= 1:
                continue
            entries.sort(key=lambda x: (-x[1], x[0]))
            keep = entries[0][0]
            for name, _ in entries[1:]:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    "DELETE FROM device_control WHERE device_name = ?", (name,)
                )
                conn.commit()
                conn.close()
                log("info", f"🧹 Removed case-duplicate RL device '{name}' (keeping '{keep}')")

    def get_device_mode(self, device_name: str) -> str:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT current_mode, override_mode, win_rate, comparisons "
            "FROM device_control WHERE device_name = ?",
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
            if (
                win_rate >= self.cfg.rl_ready_threshold
                and comps >= self.cfg.rl_ready_min_comparisons
            ):
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

    def update_performance(
        self, device_name: str, win_rate: float, comparisons: int, saved_ct: float
    ):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO device_control (device_name, current_mode) VALUES (?, 'lp')",
            (device_name,),
        )
        conn.execute(
            """UPDATE device_control
               SET win_rate = ?, comparisons = ?, cost_saved_total_ct = cost_saved_total_ct + ?
               WHERE device_name = ?""",
            (win_rate, comparisons, saved_ct, device_name),
        )
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
        cols = [
            "device_name", "current_mode", "override_mode", "win_rate",
            "comparisons", "cost_saved_total_ct", "last_switch", "switch_reason",
        ]
        d = dict(zip(cols, row))
        d["is_ready"] = (
            d.get("win_rate", 0) >= self.cfg.rl_ready_threshold
            and d.get("comparisons", 0) >= self.cfg.rl_ready_min_comparisons
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
        conn.execute(
            """UPDATE device_control
               SET current_mode = ?, last_switch = ?, switch_reason = ?
               WHERE device_name = ?""",
            (new_mode, datetime.now(timezone.utc).isoformat(), reason, device_name),
        )
        conn.commit()
        conn.close()
