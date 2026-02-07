"""
Renault ZE Vehicle Provider.

Uses the renault-api library.
Install: pip install renault-api
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from .base import VehicleProvider, VehicleData

logger = logging.getLogger(__name__)

def _log(level: str, msg: str) -> None:
    """Simple logging."""
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level.upper():5}] {msg}", flush=True)


# Try to import the library
try:
    from renault_api.renault_client import RenaultClient
    from renault_api.credential_store import FileCredentialStore
    import aiohttp
    HAS_RENAULT_API = True
except ImportError:
    HAS_RENAULT_API = False
    _log("warning", "renault-api not installed. Renault provider disabled.")


class RenaultProvider(VehicleProvider):
    """
    Provider for Renault vehicles using MY Renault / ZE Services.
    
    Config:
        evcc_name: Name in evcc config
        user: MY Renault email
        password: MY Renault password
        vin: Optional VIN (if multiple vehicles)
        locale: Locale code (default: de_DE)
        capacity_kwh: Battery capacity
    """
    
    PROVIDER_NAME = "renault"
    
    def __init__(self, config: dict):
        super().__init__(config)
        
        self.user = config.get("user", "")
        self.password = config.get("password", "")
        self.vin = config.get("vin", "")
        self.locale = config.get("locale", "de_DE")
        
        self._client: Optional['RenaultClient'] = None
        self._account = None
        self._vehicle = None
        
        if not HAS_RENAULT_API:
            self._last_error = "renault-api not installed"
    
    @classmethod
    def get_required_config(cls) -> list:
        return ["evcc_name", "user", "password"]
    
    @classmethod
    def is_available(cls) -> bool:
        """Check if the required library is installed."""
        return HAS_RENAULT_API
    
    async def authenticate(self) -> bool:
        """Login to MY Renault."""
        if not HAS_RENAULT_API:
            return False
        
        if not self.user or not self.password:
            self._last_error = "Missing user or password"
            return False
        
        try:
            _log("info", f"[{self.PROVIDER_NAME}] Authenticating {self.user}...")
            
            # Store credentials for later use
            self._authenticated = True
            _log("info", f"[{self.PROVIDER_NAME}] Credentials stored, will authenticate on first fetch")
            return True
                    
        except Exception as e:
            self._last_error = f"Auth failed: {e}"
            _log("error", f"[{self.PROVIDER_NAME}] {self._last_error}")
            return False
    
    async def fetch_vehicle_data(self) -> Optional[VehicleData]:
        """Fetch current vehicle state from Renault API."""
        if not HAS_RENAULT_API:
            return None
        
        try:
            async with aiohttp.ClientSession() as websession:
                client = RenaultClient(websession=websession, locale=self.locale)
                await client.session.login(self.user, self.password)
                
                person = await client.get_person()
                
                # Find account
                account_id = None
                for acc in person.accounts:
                    if acc.accountType == "MYRENAULT":
                        account_id = acc.accountId
                        break
                if not account_id and person.accounts:
                    account_id = person.accounts[0].accountId
                
                account = await client.get_api_account(account_id)
                
                # Find vehicle
                vehicles = await account.get_vehicles()
                if not vehicles.vehicleLinks:
                    self._last_error = "No vehicles found"
                    return None
                    
                vin = self.vin or vehicles.vehicleLinks[0].vin
                vehicle = await account.get_api_vehicle(vin)
                
                # Get battery status
                battery_status = await vehicle.get_battery_status()
                
                soc = None
                range_km = None
                is_charging = False
                is_plugged_in = False
                timestamp = datetime.now(timezone.utc)
                
                if battery_status:
                    if hasattr(battery_status, 'batteryLevel') and battery_status.batteryLevel is not None:
                        soc = float(battery_status.batteryLevel)
                    
                    if hasattr(battery_status, 'batteryAutonomy') and battery_status.batteryAutonomy is not None:
                        range_km = int(battery_status.batteryAutonomy)
                    
                    if hasattr(battery_status, 'chargingStatus'):
                        # Renault charging status: 0=not charging, 1=charging, -1=error
                        is_charging = battery_status.chargingStatus == 1.0
                    
                    if hasattr(battery_status, 'plugStatus'):
                        # Plug status: 0=unplugged, 1=plugged
                        is_plugged_in = battery_status.plugStatus == 1
                    
                    if hasattr(battery_status, 'timestamp') and battery_status.timestamp:
                        try:
                            timestamp = battery_status.timestamp
                            if timestamp.tzinfo is None:
                                timestamp = timestamp.replace(tzinfo=timezone.utc)
                        except:
                            pass
                
                # Try to get cockpit data for odometer
                odometer = None
                try:
                    cockpit = await vehicle.get_cockpit()
                    if cockpit and hasattr(cockpit, 'totalMileage'):
                        odometer = float(cockpit.totalMileage)
                except:
                    pass
                
                _log("info", f"[{self.PROVIDER_NAME}] Got SoC={soc}% for {self.evcc_name}")
                
                return VehicleData(
                    soc=soc,
                    range_km=range_km,
                    is_charging=is_charging,
                    is_plugged_in=is_plugged_in,
                    odometer_km=odometer,
                    timestamp=timestamp,
                    raw_data={
                        "vin": vin,
                    }
                )
                
        except Exception as e:
            self._last_error = f"Fetch failed: {e}"
            _log("error", f"[{self.PROVIDER_NAME}] {self._last_error}")
            return None


# Alias for Dacia (same platform)
class DaciaProvider(RenaultProvider):
    """Alias for Renault provider - Dacia uses same API."""
    PROVIDER_NAME = "dacia"
