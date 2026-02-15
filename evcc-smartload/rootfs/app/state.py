"""
Shared data structures for system state, actions, and vehicle status.

These classes are the *single source of truth* that all modules read from and write to.
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
    battery_soc: float  # 0-100
    battery_power: float  # W, positive = charging

    # Grid
    grid_power: float  # W, positive = import
    current_price: float  # EUR/kWh

    # PV
    pv_power: float  # W

    # House
    home_power: float  # W

    # EV (the vehicle currently at the wallbox)
    ev_connected: bool
    ev_soc: float  # 0-100
    ev_power: float  # W
    ev_name: str = ""
    ev_capacity_kwh: float = 0
    ev_charge_power_kw: float = 11

    # Forecast (next 6 hours)
    price_forecast: List[float] = field(default_factory=list)
    pv_forecast: List[float] = field(default_factory=list)

    def to_vector(self) -> np.ndarray:
        """Normalised feature vector for the RL agent (25-d)."""
        hour = self.timestamp.hour
        weekday = self.timestamp.weekday()

        features = [
            self.battery_soc / 100,
            np.clip(self.battery_power / 5000, -1, 1),
            np.clip(self.grid_power / 10000, -1, 1),
            self.current_price / 0.5,
            np.clip(self.pv_power / 10000, 0, 1),
            np.clip(self.home_power / 5000, 0, 1),
            float(self.ev_connected),
            self.ev_soc / 100 if self.ev_connected else 0,
            np.clip(self.ev_power / 11000, 0, 1),
            np.sin(2 * np.pi * hour / 24),
            np.cos(2 * np.pi * hour / 24),
            np.sin(2 * np.pi * weekday / 7),
            np.cos(2 * np.pi * weekday / 7),
        ]

        prices = (self.price_forecast[:6] + [0] * 6)[:6]
        features.extend([p / 0.5 for p in prices])

        pv = (self.pv_forecast[:6] + [0] * 6)[:6]
        features.extend([p / 10000 for p in pv])

        return np.array(features, dtype=np.float32)


# =============================================================================
# Action (output of optimizer / RL agent)
# =============================================================================

@dataclass
class Action:
    """Charging decision for battery and EV."""

    battery_action: int  # 0=hold, 1=charge_grid, 2=charge_pv_only, 3=discharge
    ev_action: int  # 0=no_charge, 1=charge_cheap, 2=charge_now, 3=charge_pv_only

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
    last_update: datetime  # when the vehicle DATA was generated (car timestamp)
    connected_to_wallbox: bool = False
    charging: bool = False
    data_source: str = "evcc"  # 'evcc', 'direct_api', 'cache', 'manual'
    provider_type: str = "evcc"
    last_poll: Optional[datetime] = None  # when WE last successfully polled

    # Manual SoC override
    manual_soc: Optional[float] = None
    manual_soc_timestamp: Optional[datetime] = None

    def get_effective_soc(self) -> float:
        """Return best-known SoC (manual override wins over stale/zero data)."""
        if self.manual_soc is not None and self.manual_soc_timestamp:
            # Manual always wins if API reports 0% (no real data)
            if self.soc == 0:
                return self.manual_soc
            # Manual wins if newer than last API update
            if not self.last_update or self.manual_soc_timestamp > self.last_update:
                return self.manual_soc
        return self.soc

    def get_poll_age_string(self) -> str:
        """How long ago we last polled (not how old the data is)."""
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
        """How old the actual vehicle data is."""
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
# Thread-safe store for manual SoC values (persists to disk)
# =============================================================================

class ManualSocStore:
    """Persistent store for manually entered SoC values (e.g. ORA 03)."""

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


# ---------------------------------------------------------------------------
# Solar surplus helpers
# ---------------------------------------------------------------------------

def calc_solar_surplus_kwh(solar_forecast: List[Dict], home_consumption_kw: float = 1.0) -> float:
    """Calculate expected solar surplus energy in kWh from evcc forecast entries.

    Each forecast entry has 'start' (ISO timestamp) and 'value' (kW production).
    We compute actual energy by determining the duration of each time slot from
    the difference between consecutive timestamps.

    Returns the total surplus (production minus home consumption) in kWh.
    """
    if not solar_forecast or len(solar_forecast) < 2:
        return 0.0

    # Parse and sort by start time
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

    # Detect typical slot duration from first gap
    typical_gap = (entries[1][0] - entries[0][0]).total_seconds() / 3600  # hours
    if typical_gap <= 0 or typical_gap > 2:
        typical_gap = 0.25  # default 15 min

    # Auto-detect unit: if median value > 100, probably Watts not kW
    vals = [v for _, v in entries]
    median_val = sorted(vals)[len(vals) // 2]
    unit_factor = 0.001 if median_val > 100 else 1.0  # W → kW conversion

    total_surplus = 0.0
    for i, (start, val_raw) in enumerate(entries):
        val_kw = val_raw * unit_factor

        # Determine slot duration
        if i < len(entries) - 1:
            gap_h = (entries[i + 1][0] - start).total_seconds() / 3600
            if gap_h <= 0 or gap_h > 2:
                gap_h = typical_gap
        else:
            gap_h = typical_gap

        surplus_kw = max(0, val_kw - home_consumption_kw)
        total_surplus += surplus_kw * gap_h

    # Sanity cap: max ~50 kWh per day × 2 days = 100 kWh for residential
    return min(total_surplus, 100.0)
