"""
evcc Vehicle Provider — v4 unchanged in v5.

Reads vehicle SoC directly from evcc state (no separate API).
Used for vehicles that don't have their own cloud API,
or when the vehicle is connected to the wallbox.
"""

from datetime import datetime, timezone
from typing import Optional

from logging_util import log
from vehicles.base import VehicleData


class EvccProvider:
    """Reads SoC from evcc state.

    No active polling — data is passively updated from evcc websocket state.
    Only available when vehicle is physically connected to the wallbox.
    """

    def __init__(self, config: dict):
        self.evcc_name = config.get("evcc_name") or config.get("name", "unknown")
        self.capacity_kwh = float(config.get("capacity_kwh", config.get("capacity", 30)))
        self.charge_power_kw = float(config.get("charge_power_kw", 11))
        log("info", f"EvccProvider: {self.evcc_name} ({self.capacity_kwh} kWh) — SoC via evcc only")

    def poll(self) -> Optional[VehicleData]:
        """EvccProvider has no active poll — returns None."""
        return None

    def make_vehicle_data(self) -> VehicleData:
        """Create an empty VehicleData shell for this vehicle."""
        return VehicleData(
            name=self.evcc_name,
            capacity_kwh=self.capacity_kwh,
            charge_power_kw=self.charge_power_kw,
            provider_type="evcc",
            data_source="evcc",
        )

    @property
    def supports_active_poll(self) -> bool:
        return False
