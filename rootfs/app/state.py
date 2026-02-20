"""
Shared data structures for system state, actions, and vehicle status.

v5.0: SystemState extended with price percentiles and solar forecast bucket.
      to_vector() now returns 31 features (was 25).
      Action extended: battery 7 actions, EV 5 actions.
"""

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from config import Config, MANUAL_SOC_PATH
from logging_util import log


# =============================================================================
# System State (read by optimizer, RL, dashboard, API)
# =============================================================================

@dataclass
class SystemState:
    """Complete snapshot of the energy system at a point in time."""

    timestamp: datetime

    # Battery
    battery_soc: float          # 0-100
    battery_power: float        # W, positive = charging

    # Grid
    grid_power: float           # W, positive = import
    current_price: float        # EUR/kWh

    # PV
    pv_power: float             # W

    # House
    home_power: float           # W

    # EV (the vehicle currently at the wallbox)
    ev_connected: bool
    ev_soc: float               # 0-100
    ev_power: float             # W
    ev_name: str = ""
    ev_capacity_kwh: float = 0
    ev_charge_power_kw: float = 11

    # Forecast (next 6 hours)
    price_forecast: List[float] = field(default_factory=list)
    pv_forecast: List[float] = field(default_factory=list)

    # v5: Price percentiles from 24h tariff window
    # e.g. {20: 0.12, 30: 0.15, 40: 0.18, 60: 0.25, 80: 0.32}
    price_percentiles: Dict[int, float] = field(default_factory=dict)
    price_spread: float = 0.0           # P80 - P20 (market volatility)
    hours_cheap_remaining: int = 0      # hours below P30 remaining today
    solar_forecast_total_kwh: float = 0.0

    def to_vector(self) -> np.ndarray:
        """Normalised feature vector for the RL agent (31-d).

        Indices 0-24: identical to v4 (backward-compatible layout kept for
                       reference; Q-table is reset anyway due to new actions).
        Indices 25-30: six new forecast context features.
        """
        hour = self.timestamp.hour
        weekday = self.timestamp.weekday()

        features = [
            self.battery_soc / 100,                             # 0
            np.clip(self.battery_power / 5000, -1, 1),          # 1
            np.clip(self.grid_power / 10000, -1, 1),            # 2
            self.current_price / 0.5,                           # 3
            np.clip(self.pv_power / 10000, 0, 1),               # 4
            np.clip(self.home_power / 5000, 0, 1),              # 5
            float(self.ev_connected),                           # 6
            self.ev_soc / 100 if self.ev_connected else 0,      # 7
            np.clip(self.ev_power / 11000, 0, 1),               # 8
            np.sin(2 * np.pi * hour / 24),                      # 9
            np.cos(2 * np.pi * hour / 24),                      # 10
            np.sin(2 * np.pi * weekday / 7),                    # 11
            np.cos(2 * np.pi * weekday / 7),                    # 12
        ]

        prices = (self.price_forecast[:6] + [0] * 6)[:6]
        features.extend([p / 0.5 for p in prices])             # 13-18

        pv = (self.pv_forecast[:6] + [0] * 6)[:6]
        features.extend([p / 10000 for p in pv])               # 19-24

        # --- v5: 6 new forecast-context features ---
        p20 = self.price_percentiles.get(20, self.current_price)
        p60 = self.price_percentiles.get(60, self.current_price)
        features += [
            float(np.clip(p20 / 0.5, 0, 1)),                                    # 25 P20 normalised
            float(np.clip(p60 / 0.5, 0, 1)),                                    # 26 P60 normalised
            float(np.clip(self.price_spread / 0.3, 0, 1)),                      # 27 spread normalised
            float(min(self.hours_cheap_remaining / 12, 1.0)),                   # 28 cheap hours remaining
            float(min(self.solar_forecast_total_kwh / 30, 1.0)),               # 29 solar forecast
            float(self.timestamp.timetuple().tm_yday / 365),                   # 30 season (0=Jan, ~0.5=Jul)
        ]

        return np.array(features, dtype=np.float32)


# =============================================================================
# Action (output of optimizer / RL agent)  — v5 extended action space
# =============================================================================

@dataclass
class Action:
    """Charging decision for battery and EV.

    Battery actions (7):
        0 = hold
        1 = charge_p20  (charge only when price ≤ P20 of 24h window)
        2 = charge_p40
        3 = charge_p60
        4 = charge_max  (charge up to config battery_max_price_ct)
        5 = charge_pv   (PV-only / free surplus)
        6 = discharge

    EV actions (5):
        0 = no_charge
        1 = charge_p30  (charge only when price ≤ P30)
        2 = charge_p60
        3 = charge_max  (charge up to config ev_max_price_ct)
        4 = charge_pv   (PV-only)
    """

    battery_action: int
    ev_action: int

    battery_limit_eur: Optional[float] = None
    ev_limit_eur: Optional[float] = None


# =============================================================================
# Vehicle status (managed by VehicleMonitor)
# =============================================================================

@dataclass
class VehicleStatus:
    """Status of a single vehicle, whether connected to wallbox or not."""

    name: str
    soc: float
    capacity_kwh: float
    range_km: float
    last_update: datetime
    connected_to_wallbox: bool = False
    charging: bool = False
    data_source: str = "evcc"
    provider_type: str = "evcc"
    last_poll: Optional[datetime] = None

    manual_soc: Optional[float] = None
    manual_soc_timestamp: Optional[datetime] = None

    def get_effective_soc(self) -> float:
        if self.manual_soc is not None and self.manual_soc_timestamp:
            if self.soc == 0:
                return self.manual_soc
            if not self.last_update or self.manual_soc_timestamp > self.last_update:
                return self.manual_soc
        return self.soc

    def get_poll_age_string(self) -> str:
        ts = self.last_poll or self.last_update
        if not ts:
            return "unbekannt"
        age = datetime.now(timezone.utc) - ts
        minutes = int(age.total_seconds() / 60)
        if minutes < 1:
            return "gerade eben"
        if minutes < 60:
            return f"vor {minutes}min"
        return f"vor {int(minutes / 60)}h {minutes % 60}min"

    def get_data_age_string(self) -> str:
        if not self.last_update:
            return "unbekannt"
        age = datetime.now(timezone.utc) - self.last_update
        minutes = int(age.total_seconds() / 60)
        if minutes < 1:
            return "gerade eben"
        if minutes < 60:
            return f"vor {minutes}min"
        return f"vor {int(minutes / 60)}h {minutes % 60}min"

    def is_data_stale(self, threshold_minutes: int = 60) -> bool:
        if not self.last_update:
            return True
        return (datetime.now(timezone.utc) - self.last_update).total_seconds() > threshold_minutes * 60


# =============================================================================
# Thread-safe store for manual SoC values
# =============================================================================

class ManualSocStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        try:
            with open(MANUAL_SOC_PATH, "r") as f:
                self._data = json.load(f)
            log("info", f"Loaded manual SoC data for {len(self._data)} vehicles")
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def _save(self):
        try:
            with open(MANUAL_SOC_PATH, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            log("error", f"Failed to save manual SoC: {e}")

    def set(self, vehicle_name: str, soc: float):
        with self._lock:
            self._data[vehicle_name] = {
                "soc": soc,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._save()
            log("info", f"✏️ Manual SoC for {vehicle_name} set to {soc}%")

    def get(self, vehicle_name: str) -> Optional[Dict]:
        with self._lock:
            return self._data.get(vehicle_name)

    def get_all(self) -> Dict:
        with self._lock:
            return self._data.copy()


# =============================================================================
# Percentile calculation helper (used by main loop, LP, RL)
# =============================================================================

def compute_price_percentiles(tariffs: List[Dict]) -> Dict[int, float]:
    """Compute price percentiles from a list of tariff dicts.

    Returns {20: ..., 30: ..., 40: ..., 60: ..., 80: ...} in EUR/kWh.
    """
    prices = []
    for t in tariffs:
        try:
            prices.append(float(t.get("value", 0)))
        except Exception:
            continue
    if not prices:
        return {}
    arr = np.array(prices, dtype=np.float32)
    return {
        20: float(np.percentile(arr, 20)),
        30: float(np.percentile(arr, 30)),
        40: float(np.percentile(arr, 40)),
        60: float(np.percentile(arr, 60)),
        80: float(np.percentile(arr, 80)),
    }


# =============================================================================
# Solar surplus helpers
# =============================================================================

def calc_solar_surplus_kwh(solar_forecast: List[Dict], home_consumption_kw: float = 1.0) -> float:
    """Calculate expected solar surplus energy in kWh from evcc forecast entries."""
    if not solar_forecast or len(solar_forecast) < 2:
        return 0.0

    entries = []
    for t in solar_forecast:
        try:
            s = t.get("start", "")
            val = float(t.get("value", 0))
            if val <= 0:
                continue
            if s.endswith("Z"):
                start = datetime.fromisoformat(s.replace("Z", "+00:00"))
            elif "+" in s:
                start = datetime.fromisoformat(s)
            else:
                start = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
            entries.append((start, val))
        except Exception:
            continue

    if len(entries) < 2:
        return 0.0

    entries.sort(key=lambda x: x[0])
    typical_gap = (entries[1][0] - entries[0][0]).total_seconds() / 3600
    if typical_gap <= 0 or typical_gap > 2:
        typical_gap = 0.25

    vals = [v for _, v in entries]
    median_val = sorted(vals)[len(vals) // 2]
    unit_factor = 0.001 if median_val > 100 else 1.0

    total_surplus = 0.0
    for i, (start, val_raw) in enumerate(entries):
        val_kw = val_raw * unit_factor
        if i < len(entries) - 1:
            gap_h = (entries[i + 1][0] - start).total_seconds() / 3600
            if gap_h <= 0 or gap_h > 2:
                gap_h = typical_gap
        else:
            gap_h = typical_gap
        surplus_kw = max(0, val_kw - home_consumption_kw)
        total_surplus += surplus_kw * gap_h

    return min(total_surplus, 100.0)
