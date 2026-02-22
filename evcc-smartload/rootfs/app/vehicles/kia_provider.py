"""
KIA/Hyundai Vehicle Provider — v4 unchanged in v5.

Uses hyundai-kia-connect-api (ccapi) to fetch SoC.
Supports KIA, Hyundai, Genesis vehicles with connected services.

config.yaml example:
  vehicles:
    - name: KIA_EV9
      type: kia
      username: "email@example.com"
      password: "yourpassword"
      pin: "1234"              # optional, required for some regions
      region: 1                # 1=Europe, 2=Canada, 3=USA
      brand: 1                 # 1=KIA, 2=Hyundai, 3=Genesis
      vin: "KNDC..."           # optional, auto-detected
      capacity_kwh: 99.8
"""

import time
from datetime import datetime, timezone
from typing import Optional

from logging_util import log
from vehicles.base import VehicleData


class KiaProvider:
    """Polls SoC from KIA/Hyundai cloud API using hyundai-kia-connect-api."""

    REGION_EUROPE = 1
    REGION_CANADA = 2
    REGION_USA = 3

    def __init__(self, config: dict):
        self.evcc_name = config.get("evcc_name") or config.get("name", "kia")
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.pin = config.get("pin", "")
        self.region = int(config.get("region", self.REGION_EUROPE))
        self.brand = int(config.get("brand", 1))
        self.vin = config.get("vin")
        self.capacity_kwh = float(config.get("capacity_kwh", config.get("capacity", 64)))
        self.charge_power_kw = float(config.get("charge_power_kw", 11))
        self._manager = None
        self._last_init = 0
        log("info", f"KiaProvider: {self.evcc_name} ({self.capacity_kwh} kWh, region={self.region})")

    def poll(self) -> Optional[VehicleData]:
        """Fetch SoC from KIA/Hyundai API."""
        try:
            from hyundai_kia_connect_api import VehicleManager

            # Re-init manager every 2h to avoid session expiry
            now = time.time()
            if self._manager is None or (now - self._last_init) > 7200:
                self._manager = VehicleManager(
                    region=self.region,
                    brand=self.brand,
                    username=self.username,
                    password=self.password,
                    pin=self.pin,
                )
                self._manager.check_and_refresh_token()
                self._manager.update_all_vehicles_with_cached_state()
                self._last_init = now
            else:
                self._manager.check_and_refresh_token()
                self._manager.update_all_vehicles_with_cached_state()

            # Find vehicle
            vehicles = list(self._manager.vehicles.values())
            if not vehicles:
                log("warning", f"KiaProvider {self.evcc_name}: no vehicles in account")
                return None

            target = None
            if self.vin:
                target = self._manager.vehicles.get(self.vin)
            if target is None:
                target = vehicles[0]

            soc = target.ev_battery_percentage
            if soc is None:
                log("warning", f"KiaProvider {self.evcc_name}: SoC is None (not an EV?)")
                return None

            range_km = getattr(target, "ev_driving_range", None)

            v = VehicleData(
                name=self.evcc_name,
                capacity_kwh=self.capacity_kwh,
                charge_power_kw=self.charge_power_kw,
                provider_type="kia",
            )
            v.update_from_api(float(soc), range_km=float(range_km) if range_km else None)
            log("info", f"KiaProvider {self.evcc_name}: SoC={soc}% range={range_km}km")
            return v

        except ImportError:
            log("error", "hyundai-kia-connect-api not installed. Run: pip install hyundai-kia-connect-api")
            return None
        except Exception as e:
            log("warning", f"KiaProvider {self.evcc_name} poll error: {e}")
            self._manager = None  # Force re-init next time
            return None

    @property
    def supports_active_poll(self) -> bool:
        return bool(self.username and self.password)
