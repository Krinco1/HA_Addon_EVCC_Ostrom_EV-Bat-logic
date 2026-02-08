"""
KIA / Hyundai Bluelink Vehicle Provider.

Uses the hyundai_kia_connect_api library.
Install: pip install hyundai_kia_connect_api
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
    from hyundai_kia_connect_api import VehicleManager, Vehicle
    from hyundai_kia_connect_api.const import REGIONS, BRANDS
    HAS_KIA_API = True
except ImportError:
    HAS_KIA_API = False
    _log("warning", "hyundai_kia_connect_api not installed. KIA provider disabled.")


class KiaProvider(VehicleProvider):
    """
    Provider for KIA and Hyundai vehicles using Bluelink/UVO Connect.
    
    Config:
        evcc_name: Name in evcc config
        user: KIA Connect email
        password: KIA Connect password
        pin: Optional PIN (required for some features)
        vin: Optional VIN (if multiple vehicles)
        brand: 'kia' or 'hyundai' (default: kia)
        region: Region code (default: 1 = Europe)
        capacity_kwh: Battery capacity
    """
    
    PROVIDER_NAME = "kia"
    
    # Region mapping
    REGIONS_MAP = {
        "europe": 1,
        "canada": 2,
        "usa": 3,
        "china": 4,
        "australia": 5,
        "india": 6,
        "nz": 7,
        "brazil": 8
    }
    
    # Brand mapping
    BRANDS_MAP = {
        "kia": 1,
        "hyundai": 2,
        "genesis": 3
    }
    
    def __init__(self, config: dict):
        super().__init__(config)
        
        self.user = config.get("user", "")
        self.password = config.get("password", "")
        self.pin = config.get("pin", "")
        self.vin = config.get("vin", "")
        
        # Brand & Region
        brand_str = config.get("brand", "kia").lower()
        region_str = config.get("region", "europe").lower()
        
        self.brand = self.BRANDS_MAP.get(brand_str, 1)
        self.region = self.REGIONS_MAP.get(region_str, 1)
        
        self._manager: Optional['VehicleManager'] = None
        self._vehicle: Optional['Vehicle'] = None
        
        if not HAS_KIA_API:
            self._last_error = "hyundai_kia_connect_api not installed"
    
    @classmethod
    def get_required_config(cls) -> list:
        return ["evcc_name", "user", "password"]
    
    @classmethod
    def is_available(cls) -> bool:
        """Check if the required library is installed."""
        return HAS_KIA_API
    
    async def authenticate(self) -> bool:
        """Login to KIA Connect."""
        if not HAS_KIA_API:
            return False
        
        if not self.user or not self.password:
            self._last_error = "Missing user or password"
            return False
        
        try:
            _log("info", f"[{self.PROVIDER_NAME}] Authenticating {self.user}...")
            
            # Create vehicle manager
            self._manager = VehicleManager(
                region=self.region,
                brand=self.brand,
                username=self.user,
                password=self.password,
                pin=self.pin if self.pin else ""
            )
            
            # Run login in thread pool (blocking call)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._manager.check_and_refresh_token)
            
            # Get vehicles
            await loop.run_in_executor(None, self._manager.update_all_vehicles_with_cached_state)
            
            # Find our vehicle
            if self._manager.vehicles:
                if self.vin:
                    # Find by VIN
                    for vid, vehicle in self._manager.vehicles.items():
                        if vehicle.VIN == self.vin:
                            self._vehicle = vehicle
                            break
                else:
                    # Take first vehicle
                    self._vehicle = list(self._manager.vehicles.values())[0]
                
                if self._vehicle:
                    _log("info", f"[{self.PROVIDER_NAME}] Authenticated! Vehicle: {self._vehicle.name} ({self._vehicle.VIN})")
                    return True
                else:
                    self._last_error = f"Vehicle with VIN {self.vin} not found"
            else:
                self._last_error = "No vehicles found in account"
            
            return False
            
        except Exception as e:
            self._last_error = f"Auth failed: {e}"
            _log("error", f"[{self.PROVIDER_NAME}] {self._last_error}")
            return False
    
    async def fetch_vehicle_data(self) -> Optional[VehicleData]:
        """Fetch current vehicle state from KIA API."""
        if not HAS_KIA_API or not self._manager or not self._vehicle:
            return None
        
        try:
            loop = asyncio.get_event_loop()
            
            # Refresh token if needed
            await loop.run_in_executor(None, self._manager.check_and_refresh_token)
            
            # Get fresh data (cached from KIA servers)
            await loop.run_in_executor(None, self._manager.update_all_vehicles_with_cached_state)
            
            # Extract data
            vehicle = self._vehicle
            
            # SoC
            soc = None
            if hasattr(vehicle, 'ev_battery_percentage') and vehicle.ev_battery_percentage is not None:
                soc = float(vehicle.ev_battery_percentage)
            elif hasattr(vehicle, 'battery_level') and vehicle.battery_level is not None:
                soc = float(vehicle.battery_level)
            
            # Range
            range_km = None
            if hasattr(vehicle, 'ev_driving_range') and vehicle.ev_driving_range is not None:
                range_km = int(vehicle.ev_driving_range)
            
            # Charging status
            is_charging = False
            if hasattr(vehicle, 'ev_battery_is_charging'):
                is_charging = bool(vehicle.ev_battery_is_charging)
            
            # Plugged in
            is_plugged_in = False
            if hasattr(vehicle, 'ev_battery_is_plugged_in'):
                is_plugged_in = bool(vehicle.ev_battery_is_plugged_in)
            elif is_charging:
                is_plugged_in = True
            
            # Odometer
            odometer = None
            if hasattr(vehicle, 'odometer') and vehicle.odometer is not None:
                odometer = float(vehicle.odometer)
            
            # Data timestamp from vehicle
            timestamp = datetime.now(timezone.utc)
            if hasattr(vehicle, 'last_updated_at') and vehicle.last_updated_at:
                try:
                    timestamp = vehicle.last_updated_at
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                except:
                    pass
            
            return VehicleData(
                soc=soc,
                range_km=range_km,
                is_charging=is_charging,
                is_plugged_in=is_plugged_in,
                odometer_km=odometer,
                timestamp=timestamp,
                raw_data={
                    "vehicle_name": vehicle.name if hasattr(vehicle, 'name') else None,
                    "vin": vehicle.VIN if hasattr(vehicle, 'VIN') else None,
                    "model": vehicle.model if hasattr(vehicle, 'model') else None,
                }
            )
            
        except Exception as e:
            self._last_error = f"Fetch failed: {e}"
            _log("error", f"[{self.PROVIDER_NAME}] {self._last_error}")
            return None
    
    async def force_refresh(self) -> Optional[VehicleData]:
        """
        Force a refresh from the vehicle (wakes up car!).
        Use sparingly - may drain 12V battery and uses API quota.
        """
        if not HAS_KIA_API or not self._manager or not self._vehicle:
            return None
        
        try:
            _log("info", f"[{self.PROVIDER_NAME}] Forcing refresh for {self.evcc_name} (this wakes the car!)")
            
            loop = asyncio.get_event_loop()
            
            # This actually pings the car
            await loop.run_in_executor(
                None, 
                self._manager.force_refresh_vehicle_state,
                self._vehicle.id
            )
            
            # Wait a bit for data to propagate
            await asyncio.sleep(5)
            
            # Now fetch the updated data
            return await self.fetch_vehicle_data()
            
        except Exception as e:
            self._last_error = f"Force refresh failed: {e}"
            _log("error", f"[{self.PROVIDER_NAME}] {self._last_error}")
            return None


# Alias for Hyundai
class HyundaiProvider(KiaProvider):
    """Alias for KIA provider - same API, different brand default."""
    PROVIDER_NAME = "hyundai"
    
    def __init__(self, config: dict):
        config.setdefault("brand", "hyundai")
        super().__init__(config)
