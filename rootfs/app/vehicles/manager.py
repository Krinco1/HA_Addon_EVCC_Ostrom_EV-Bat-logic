"""
Vehicle Manager — v4 unchanged in v5.

Initializes vehicle providers from config and coordinates SoC data.
"""

from typing import Dict, List, Optional

from logging_util import log
from vehicles.base import VehicleData
from vehicles.evcc_provider import EvccProvider
from vehicles.kia_provider import KiaProvider
from vehicles.renault_provider import RenaultProvider
from vehicles.custom_provider import CustomProvider


def _make_provider(config: dict):
    """Factory: create provider based on config type."""
    ptype = config.get("type", config.get("template", "evcc")).lower()

    if ptype in ("kia", "hyundai", "genesis"):
        return KiaProvider(config)
    elif ptype == "renault":
        return RenaultProvider(config)
    elif ptype == "custom":
        return CustomProvider(config)
    elif ptype == "evcc":
        return EvccProvider(config)
    else:
        log("warning", f"Unknown provider type '{ptype}' for {config.get('name', '?')} — using evcc fallback")
        return EvccProvider(config)


class VehicleManager:
    """Manages all configured vehicle providers."""

    def __init__(self, vehicle_configs: List[dict]):
        self.providers: Dict[str, object] = {}   # evcc_name → provider
        self._vehicle_data: Dict[str, VehicleData] = {}

        for cfg in vehicle_configs:
            name = cfg.get("evcc_name") or cfg.get("name", "unknown")
            try:
                provider = _make_provider(cfg)
                self.providers[name] = provider
                # Initialize empty VehicleData shell
                if hasattr(provider, "make_vehicle_data"):
                    self._vehicle_data[name] = provider.make_vehicle_data()
                else:
                    self._vehicle_data[name] = VehicleData(
                        name=name,
                        capacity_kwh=float(cfg.get("capacity_kwh", cfg.get("capacity", 30))),
                        charge_power_kw=float(cfg.get("charge_power_kw", 11)),
                        provider_type=cfg.get("type", "evcc"),
                    )
            except Exception as e:
                log("error", f"Failed to init provider for {name}: {e}")

        log("info", f"VehicleManager: {len(self.providers)} vehicle(s) configured")

    def poll_vehicle(self, name: str) -> Optional[VehicleData]:
        """Poll a specific vehicle's SoC from its API provider."""
        provider = self.providers.get(name)
        if provider is None:
            return None
        if not getattr(provider, "supports_active_poll", False):
            return None  # evcc-only vehicles don't poll

        result = provider.poll()
        if result:
            # Merge into existing data, preserve wallbox state from evcc
            existing = self._vehicle_data.get(name)
            if existing:
                result.connected_to_wallbox = existing.connected_to_wallbox
                result.charging = existing.charging
            self._vehicle_data[name] = result
        return result

    def get_vehicle(self, name: str) -> Optional[VehicleData]:
        return self._vehicle_data.get(name)

    def get_all_vehicles(self) -> Dict[str, VehicleData]:
        return dict(self._vehicle_data)

    def update_from_evcc(self, evcc_state: dict):
        """Update vehicle connectivity and SoC from evcc loadpoint state."""
        loadpoints = evcc_state.get("loadpoints", [])

        # Mark all disconnected first
        for v in self._vehicle_data.values():
            v.connected_to_wallbox = False
            v.charging = False

        for lp in loadpoints:
            vehicle_name = lp.get("vehicleName") or lp.get("vehicle", "")
            if not vehicle_name:
                continue

            # Case-insensitive match
            matched = self._match_vehicle(vehicle_name)
            if matched is None:
                continue

            vd = self._vehicle_data[matched]
            vd.connected_to_wallbox = lp.get("connected", False)
            vd.charging = lp.get("charging", False)

            # SoC from evcc (only when connected)
            evcc_soc = lp.get("vehicleSoc")
            if evcc_soc is not None and vd.connected_to_wallbox:
                vd.update_from_evcc(float(evcc_soc), vd.connected_to_wallbox, vd.charging)

    def _match_vehicle(self, name: str) -> Optional[str]:
        """Find configured vehicle name matching evcc vehicle name (case-insensitive)."""
        nl = name.lower()
        for k in self._vehicle_data:
            if k.lower() == nl:
                return k
        return None

    def get_pollable_names(self) -> List[str]:
        """Return names of vehicles that support active API polling."""
        return [
            name for name, p in self.providers.items()
            if getattr(p, "supports_active_poll", False)
        ]
