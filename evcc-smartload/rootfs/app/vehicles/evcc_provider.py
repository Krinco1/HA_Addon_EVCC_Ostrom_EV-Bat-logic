"""
evcc Vehicle Provider.

Fetches vehicle data from evcc API when vehicle is connected to loadpoint.
This is the fallback provider when no direct API is configured.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import requests

from .base import VehicleProvider, VehicleData

logger = logging.getLogger(__name__)


class EVCCProvider(VehicleProvider):
    """
    Provider that fetches vehicle data from evcc REST API.
    
    Only works when vehicle is physically connected to loadpoint!
    
    Config:
        evcc_name: Name in evcc config
        evcc_host: evcc hostname/IP (default: 192.168.1.66)
        evcc_port: evcc port (default: 7070)
        loadpoint_id: Loadpoint index, 0-based (default: 0)
        capacity_kwh: Battery capacity
    """
    
    PROVIDER_NAME = "evcc"
    
    def __init__(self, config: dict):
        super().__init__(config)
        
        self.evcc_host = config.get("evcc_host", "192.168.1.66")
        self.evcc_port = config.get("evcc_port", 7070)
        self.loadpoint_id = config.get("loadpoint_id", 0)
        
        self._base_url = f"http://{self.evcc_host}:{self.evcc_port}/api"
        self._authenticated = True  # No auth needed for evcc
    
    @classmethod
    def get_required_config(cls) -> list:
        return ["evcc_name"]
    
    @classmethod
    def is_available(cls) -> bool:
        """Always available - just needs network."""
        return True
    
    async def authenticate(self) -> bool:
        """No authentication needed for evcc API."""
        self._authenticated = True
        return True
    
    async def fetch_vehicle_data(self) -> Optional[VehicleData]:
        """Fetch vehicle data from evcc /api/state."""
        try:
            response = requests.get(f"{self._base_url}/state", timeout=10)
            response.raise_for_status()
            data = response.json()
            
            result = data.get("result", data)
            loadpoints = result.get("loadpoints", [])
            
            if not loadpoints or self.loadpoint_id >= len(loadpoints):
                logger.debug(f"[{self.PROVIDER_NAME}] No loadpoint {self.loadpoint_id}")
                return None
            
            lp = loadpoints[self.loadpoint_id]
            
            # Check if our vehicle is connected
            vehicle_name = lp.get("vehicleName", "")
            connected = lp.get("connected", False)
            
            if not connected:
                logger.debug(f"[{self.PROVIDER_NAME}] No vehicle connected to loadpoint {self.loadpoint_id}")
                return None
            
            # Check if it's our vehicle
            if vehicle_name and vehicle_name.lower() != self.evcc_name.lower():
                logger.debug(f"[{self.PROVIDER_NAME}] Different vehicle connected: {vehicle_name}")
                return None
            
            # Extract data
            soc = lp.get("vehicleSoc")
            if soc is not None:
                soc = float(soc)
            
            range_km = lp.get("vehicleRange")
            if range_km is not None:
                range_km = int(range_km)
            
            is_charging = lp.get("charging", False)
            is_plugged_in = connected
            
            # Odometer usually not available from evcc
            odometer = lp.get("vehicleOdometer")
            
            return VehicleData(
                soc=soc,
                range_km=range_km,
                is_charging=is_charging,
                is_plugged_in=is_plugged_in,
                odometer_km=odometer,
                timestamp=datetime.now(timezone.utc),
                raw_data={
                    "loadpoint_id": self.loadpoint_id,
                    "vehicle_name": vehicle_name,
                    "charge_power": lp.get("chargePower"),
                    "charged_energy": lp.get("chargedEnergy"),
                    "mode": lp.get("mode")
                }
            )
            
        except requests.RequestException as e:
            self._last_error = f"evcc API error: {e}"
            logger.error(f"[{self.PROVIDER_NAME}] {self._last_error}")
            return None
        except Exception as e:
            self._last_error = f"Error: {e}"
            logger.error(f"[{self.PROVIDER_NAME}] {self._last_error}")
            return None
    
    def get_all_vehicles_from_evcc(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all vehicles currently shown in evcc state.
        Returns dict of vehicle_name -> info
        """
        try:
            response = requests.get(f"{self._base_url}/state", timeout=10)
            response.raise_for_status()
            data = response.json()
            
            result = data.get("result", data)
            loadpoints = result.get("loadpoints", [])
            
            vehicles = {}
            for i, lp in enumerate(loadpoints):
                vehicle_name = lp.get("vehicleName")
                if vehicle_name and lp.get("connected"):
                    vehicles[vehicle_name] = {
                        "loadpoint_id": i,
                        "soc": lp.get("vehicleSoc"),
                        "range_km": lp.get("vehicleRange"),
                        "charging": lp.get("charging", False),
                        "connected": True,
                        "charge_power": lp.get("chargePower"),
                        "mode": lp.get("mode")
                    }
            
            return vehicles
            
        except Exception as e:
            logger.error(f"[{self.PROVIDER_NAME}] Failed to get vehicles: {e}")
            return {}
