"""
Custom Vehicle Provider.

Allows integration of user-provided scripts for vehicles without official API support.
The script must output JSON to stdout with at least a 'soc' field.
"""

import asyncio
import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Optional

from .base import VehicleProvider, VehicleData

logger = logging.getLogger(__name__)


class CustomProvider(VehicleProvider):
    """
    Provider that executes a custom script to get vehicle data.
    
    The script should output JSON to stdout:
    {
        "soc": 72,
        "range_km": 280,
        "is_charging": false,
        "is_plugged_in": false,
        "odometer_km": 12345
    }
    
    Config:
        evcc_name: Name in evcc config
        script: Path to script or command
        script_args: Optional list of arguments
        timeout: Script timeout in seconds (default: 30)
        capacity_kwh: Battery capacity
    """
    
    PROVIDER_NAME = "custom"
    
    def __init__(self, config: dict):
        super().__init__(config)
        
        self.script = config.get("script", "")
        self.script_args = config.get("script_args", [])
        self.timeout = config.get("timeout", 30)
        self.env_vars = config.get("env", {})
        
        if not self.script:
            self._last_error = "No script configured"
    
    @classmethod
    def get_required_config(cls) -> list:
        return ["evcc_name", "script"]
    
    @classmethod
    def is_available(cls) -> bool:
        """Always available."""
        return True
    
    async def authenticate(self) -> bool:
        """No authentication needed - script handles it."""
        if not self.script:
            return False
        self._authenticated = True
        return True
    
    async def fetch_vehicle_data(self) -> Optional[VehicleData]:
        """Execute script and parse JSON output."""
        if not self.script:
            return None
        
        try:
            # Build command
            cmd = [self.script] + self.script_args
            
            logger.debug(f"[{self.PROVIDER_NAME}] Executing: {' '.join(cmd)}")
            
            # Run script
            loop = asyncio.get_event_loop()
            
            def run_script():
                import os
                env = os.environ.copy()
                env.update(self.env_vars)
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    env=env
                )
                return result
            
            result = await loop.run_in_executor(None, run_script)
            
            if result.returncode != 0:
                self._last_error = f"Script failed: {result.stderr}"
                logger.error(f"[{self.PROVIDER_NAME}] {self._last_error}")
                return None
            
            # Parse JSON output
            output = result.stdout.strip()
            if not output:
                self._last_error = "Script produced no output"
                return None
            
            data = json.loads(output)
            
            # Extract fields
            soc = data.get("soc")
            if soc is not None:
                soc = float(soc)
            
            range_km = data.get("range_km")
            if range_km is not None:
                range_km = int(range_km)
            
            odometer = data.get("odometer_km")
            if odometer is not None:
                odometer = float(odometer)
            
            # Parse timestamp if provided
            timestamp = datetime.now(timezone.utc)
            if "timestamp" in data:
                try:
                    ts = data["timestamp"]
                    if isinstance(ts, str):
                        timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    elif isinstance(ts, (int, float)):
                        timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
                except:
                    pass
            
            return VehicleData(
                soc=soc,
                range_km=range_km,
                is_charging=data.get("is_charging", False),
                is_plugged_in=data.get("is_plugged_in", False),
                odometer_km=odometer,
                timestamp=timestamp,
                raw_data=data
            )
            
        except subprocess.TimeoutExpired:
            self._last_error = f"Script timed out after {self.timeout}s"
            logger.error(f"[{self.PROVIDER_NAME}] {self._last_error}")
            return None
        except json.JSONDecodeError as e:
            self._last_error = f"Invalid JSON output: {e}"
            logger.error(f"[{self.PROVIDER_NAME}] {self._last_error}")
            return None
        except Exception as e:
            self._last_error = f"Script error: {e}"
            logger.error(f"[{self.PROVIDER_NAME}] {self._last_error}")
            return None


class ManualProvider(VehicleProvider):
    """
    Provider for vehicles without any API.
    
    Only provides data from evcc when connected, otherwise unknown.
    Useful for vehicles where the manufacturer doesn't offer an API.
    
    Config:
        evcc_name: Name in evcc config
        capacity_kwh: Battery capacity
        default_soc: Optional default SoC to assume when unknown
    """
    
    PROVIDER_NAME = "manual"
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.default_soc = config.get("default_soc")
        self._authenticated = True
    
    @classmethod
    def get_required_config(cls) -> list:
        return ["evcc_name"]
    
    @classmethod
    def is_available(cls) -> bool:
        return True
    
    async def authenticate(self) -> bool:
        return True
    
    async def fetch_vehicle_data(self) -> Optional[VehicleData]:
        """Manual provider has no data source - returns default or None."""
        if self.default_soc is not None:
            return VehicleData(
                soc=self.default_soc,
                range_km=None,
                is_charging=False,
                is_plugged_in=False,
                timestamp=datetime.now(timezone.utc),
                raw_data={"source": "default_value"}
            )
        return None
