"""
Renault Vehicle Provider — v4 unchanged in v5.

Uses renault-api library to fetch SoC from Renault/Dacia vehicles.

config.yaml example:
  vehicles:
    - name: my_Twingo
      type: renault
      username: "email@example.com"
      password: "yourpassword"
      vin: "VF1ABC..."         # optional, auto-detected if only one car
      locale: "de_DE"          # optional, default de_DE
      capacity_kwh: 22
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from logging_util import log
from vehicles.base import VehicleData


class RenaultProvider:
    """Polls SoC from Renault cloud API using renault-api library."""

    def __init__(self, config: dict):
        self.evcc_name = config.get("evcc_name") or config.get("name", "renault")
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.vin = config.get("vin")
        self.locale = config.get("locale", "de_DE")
        self.capacity_kwh = float(config.get("capacity_kwh", config.get("capacity", 22)))
        self.charge_power_kw = float(config.get("charge_power_kw", 7.4))
        self._account = None
        self._vehicle = None
        log("info", f"RenaultProvider: {self.evcc_name} ({self.capacity_kwh} kWh)")

    def poll(self) -> Optional[VehicleData]:
        """Fetch SoC via renault-api (runs async loop internally)."""
        try:
            return asyncio.run(self._async_poll())
        except Exception as e:
            log("warning", f"RenaultProvider {self.evcc_name} poll error: {e}")
            return None

    async def _async_poll(self) -> Optional[VehicleData]:
        try:
            from renault_api.renault_client import RenaultClient
            import aiohttp

            async with aiohttp.ClientSession() as session:
                client = RenaultClient(websession=session, locale=self.locale)
                await client.session.login(self.username, self.password)

                account = await client.get_api_account(
                    await self._get_account_id(client)
                )

                if self.vin:
                    vehicle = await account.get_api_vehicle(self.vin)
                else:
                    vehicles = await account.get_vehicles()
                    items = vehicles.vehicleLinks or []
                    if not items:
                        log("warning", f"RenaultProvider {self.evcc_name}: no vehicles found")
                        return None
                    vehicle = await account.get_api_vehicle(items[0].vin)

                battery = await vehicle.get_battery_status()
                soc = battery.batteryLevel
                if soc is None:
                    return None

                v = VehicleData(
                    name=self.evcc_name,
                    capacity_kwh=self.capacity_kwh,
                    charge_power_kw=self.charge_power_kw,
                    provider_type="renault",
                )
                v.update_from_api(float(soc))
                log("info", f"RenaultProvider {self.evcc_name}: SoC={soc}%")
                return v

        except ImportError:
            log("error", "renault-api not installed. Run: pip install renault-api aiohttp")
            return None
        except Exception as e:
            log("warning", f"RenaultProvider {self.evcc_name} async error: {e}")
            return None

    async def _get_account_id(self, client) -> str:
        """Get the first account ID."""
        person = await client.get_person()
        accounts = person.accounts or []
        for acc in accounts:
            if acc.accountType == "MYRENAULT":
                return acc.accountId
        if accounts:
            return accounts[0].accountId
        raise ValueError("No Renault account found")

    @property
    def supports_active_poll(self) -> bool:
        return bool(self.username and self.password)
