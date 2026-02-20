"""
Base vehicle data model for EVCC-Smartload.

All vehicle providers return VehicleData instances.
Vehicle-specific data is fetched by provider classes in this package.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# SoC data older than this is considered stale
STALE_THRESHOLD_MINUTES = 60


@dataclass
class VehicleData:
    """Holds all known data about a vehicle."""

    name: str
    capacity_kwh: float = 0.0

    # State of Charge
    soc: Optional[float] = None           # Last known SoC from API / evcc
    manual_soc: Optional[float] = None    # Manual override (from dashboard)

    # Derived
    range_km: Optional[float] = None
    charging: bool = False
    connected_to_wallbox: bool = False

    # Timestamps
    last_update: Optional[datetime] = None    # When SoC data was last received
    last_poll: Optional[datetime] = None      # When we last attempted a poll

    # Metadata
    data_source: str = "unknown"   # "api", "evcc", "manual", "cache"
    charge_power_kw: Optional[float] = None
    provider_type: str = "unknown"

    def get_effective_soc(self) -> float:
        """Return the best available SoC value (manual override > API > 50%)."""
        if self.manual_soc is not None:
            return self.manual_soc
        if self.soc is not None:
            return self.soc
        return 50.0

    def is_data_stale(self) -> bool:
        """Return True if SoC data is older than STALE_THRESHOLD_MINUTES."""
        if self.manual_soc is not None:
            return False   # Manual overrides are never stale
        if self.last_update is None:
            return True
        age = datetime.now(timezone.utc) - self.last_update.astimezone(timezone.utc)
        return age.total_seconds() / 60 > STALE_THRESHOLD_MINUTES

    def get_data_age_string(self) -> str:
        """Human-readable age of the SoC data."""
        if self.last_update is None:
            return "never"
        age = datetime.now(timezone.utc) - self.last_update.astimezone(timezone.utc)
        mins = int(age.total_seconds() / 60)
        if mins < 2:
            return "gerade eben"
        if mins < 60:
            return f"vor {mins}min"
        hours = mins // 60
        remaining = mins % 60
        if remaining == 0:
            return f"vor {hours}h"
        return f"vor {hours}h {remaining}min"

    def get_poll_age_string(self) -> str:
        """Human-readable age of the last poll attempt."""
        if self.last_poll is None:
            return "never"
        age = datetime.now(timezone.utc) - self.last_poll.astimezone(timezone.utc)
        mins = int(age.total_seconds() / 60)
        if mins < 2:
            return "gerade eben"
        if mins < 60:
            return f"vor {mins}min"
        return f"vor {mins // 60}h {mins % 60}min"

    def update_from_evcc(self, evcc_soc: Optional[float], connected: bool,
                          charging: bool):
        """Update vehicle state from evcc websocket data."""
        self.connected_to_wallbox = connected
        self.charging = charging
        if evcc_soc is not None:
            self.soc = evcc_soc
            self.last_update = datetime.now(timezone.utc)
            self.data_source = "evcc"

    def update_from_api(self, soc: float, range_km: Optional[float] = None):
        """Update vehicle state from direct API poll."""
        self.soc = soc
        self.last_update = datetime.now(timezone.utc)
        self.data_source = "api"
        if range_km is not None:
            self.range_km = range_km
