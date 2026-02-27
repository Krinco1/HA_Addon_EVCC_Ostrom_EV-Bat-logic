"""
Renault Vehicle Provider — v6 (Phase 9 fix).

Uses renault-api library to fetch SoC from Renault/Dacia vehicles.
Persists aiohttp session and RenaultClient across polls to avoid full re-auth each time.

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
import time
from datetime import datetime, timezone
from typing import Optional

from logging_util import log
from vehicles.base import VehicleData


class RenaultProvider:
    """Polls SoC from Renault cloud API using renault-api library with persistent session."""

    def __init__(self, config: dict):
        self.evcc_name = config.get("evcc_name") or config.get("name", "renault")
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.vin = config.get("vin")
        self.locale = config.get("locale", "de_DE")
        self.capacity_kwh = float(config.get("capacity_kwh", config.get("capacity", 22)))
        self.charge_power_kw = float(config.get("charge_power_kw", 7.4))
        # Persistent connection state
        self._session = None
        self._client = None
        self._vehicle_obj = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Backoff state
        self._failure_count: int = 0
        self._backoff_until: float = 0.0
        log("info", f"RenaultProvider: {self.evcc_name} ({self.capacity_kwh} kWh)")

    def is_in_backoff(self) -> bool:
        return time.time() < self._backoff_until

    def record_failure(self):
        self._failure_count += 1
        hours = min(2 ** self._failure_count, 24)  # 2h, 4h, 8h, 16h, 24h cap
        self._backoff_until = time.time() + hours * 3600
        log("warning", f"RenaultProvider {self.evcc_name}: backoff {hours}h (failure #{self._failure_count})")

    def record_success(self):
        if self._failure_count > 0:
            log("info", f"RenaultProvider {self.evcc_name}: recovered after {self._failure_count} failures")
        self._failure_count = 0
        self._backoff_until = 0.0

    def poll(self) -> Optional[VehicleData]:
        """Fetch SoC via renault-api using persistent event loop and session."""
        try:
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
            return self._loop.run_until_complete(self._async_poll())
        except Exception as e:
            self.record_failure()
            log("warning", f"RenaultProvider {self.evcc_name} poll error: {e}")
            return None

    async def _async_poll(self) -> Optional[VehicleData]:
        for attempt in range(2):  # max 1 retry after re-auth
            try:
                if self._client is None:
                    await self._init_client()
                battery = await self._vehicle_obj.get_battery_status()
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
                self.record_success()
                return v
            except Exception as e:
                # Check for 401-like auth errors
                is_auth_error = False
                if hasattr(e, 'status') and getattr(e, 'status', 0) == 401:
                    is_auth_error = True
                elif '401' in str(e) or 'unauthorized' in str(e).lower():
                    is_auth_error = True

                if is_auth_error and attempt == 0:
                    log("info", f"RenaultProvider {self.evcc_name}: auth error — re-authenticating")
                    self._client = None
                    self._vehicle_obj = None
                    continue
                raise
        return None

    async def _init_client(self):
        """Initialize persistent aiohttp session and RenaultClient."""
        from renault_api.renault_client import RenaultClient
        import aiohttp
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        self._client = RenaultClient(websession=self._session, locale=self.locale)
        await self._client.session.login(self.username, self.password)
        account_id = await self._get_account_id(self._client)
        account = await self._client.get_api_account(account_id)
        if self.vin:
            self._vehicle_obj = await account.get_api_vehicle(self.vin)
        else:
            vehicles = await account.get_vehicles()
            items = vehicles.vehicleLinks or []
            if not items:
                raise ValueError(f"No vehicles found for {self.evcc_name}")
            self._vehicle_obj = await account.get_api_vehicle(items[0].vin)

    async def _get_account_id(self, client) -> str:
        """Get the first MYRENAULT account ID."""
        person = await client.get_person()
        accounts = person.accounts or []
        for acc in accounts:
            if acc.accountType == "MYRENAULT":
                return acc.accountId
        if accounts:
            return accounts[0].accountId
        raise ValueError("No Renault account found")

    def close(self):
        """Close persistent session (called on shutdown)."""
        if self._session and not self._session.closed:
            if self._loop and not self._loop.is_closed():
                self._loop.run_until_complete(self._session.close())
        if self._loop and not self._loop.is_closed():
            self._loop.close()

    @property
    def supports_active_poll(self) -> bool:
        return bool(self.username and self.password)
