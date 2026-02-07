"""
Vehicle Manager.

Orchestrates all vehicle providers, handles caching, matching with evcc, and data aggregation.
"""

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Type

from .base import VehicleProvider, VehicleData, VehicleState


def _log(level: str, msg: str) -> None:
    """Simple logging that works with Home Assistant."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level.upper():5}] {msg}", flush=True)


logger = logging.getLogger(__name__)


class VehicleManager:
    """
    Manages all vehicle providers and aggregates data.
    
    Features:
    - Dynamic provider loading
    - Automatic evcc matching
    - Data caching with staleness tracking
    - Fallback hierarchy (direct API -> evcc -> cache)
    - Background polling
    """
    
    def __init__(self, config: dict, evcc_host: str = "192.168.1.66", evcc_port: int = 7070):
        """
        Initialize the vehicle manager.
        
        Args:
            config: Vehicle configuration from addon config
            evcc_host: evcc server host
            evcc_port: evcc server port
        """
        self.evcc_host = evcc_host
        self.evcc_port = evcc_port
        
        # Polling settings
        self.poll_interval_minutes = config.get("poll_interval_minutes", 30)
        self.poll_on_connect = config.get("poll_on_connect", True)
        
        # Provider registry
        self._provider_classes: Dict[str, Type[VehicleProvider]] = {}
        self._register_builtin_providers()
        
        # Active providers
        self._providers: Dict[str, VehicleProvider] = {}
        
        # Vehicle states (evcc_name -> VehicleState)
        self._states: Dict[str, VehicleState] = {}
        
        # Cache of last known evcc connected vehicles
        self._evcc_connected: Dict[str, dict] = {}
        self._last_evcc_check: Optional[datetime] = None
        
        # Background polling
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        
        # Initialize providers from config
        self._init_providers(config.get("providers", []))
        
        _log("info", f"VehicleManager initialized with {len(self._providers)} providers")
    
    def _register_builtin_providers(self):
        """Register all built-in provider classes."""
        from .kia_provider import KiaProvider, HyundaiProvider
        from .renault_provider import RenaultProvider, DaciaProvider
        from .evcc_provider import EVCCProvider
        from .custom_provider import CustomProvider, ManualProvider
        
        self._provider_classes = {
            "kia": KiaProvider,
            "hyundai": HyundaiProvider,
            "renault": RenaultProvider,
            "dacia": DaciaProvider,
            "evcc": EVCCProvider,
            "custom": CustomProvider,
            "manual": ManualProvider,
        }
    
    def register_provider(self, name: str, provider_class: Type[VehicleProvider]):
        """Register a custom provider class."""
        self._provider_classes[name.lower()] = provider_class
        _log("info", f"Registered provider: {name}")
    
    def _init_providers(self, provider_configs: List[dict]):
        """Initialize providers from config."""
        for cfg in provider_configs:
            try:
                evcc_name = cfg.get("evcc_name")
                provider_type = cfg.get("type", "manual").lower()
                
                if not evcc_name:
                    _log("warning", f"Provider config missing evcc_name: {cfg}")
                    continue
                
                if provider_type not in self._provider_classes:
                    _log("warning", f"Unknown provider type: {provider_type}")
                    provider_type = "manual"
                
                provider_class = self._provider_classes[provider_type]
                
                # Check if provider library is available
                if hasattr(provider_class, 'is_available') and not provider_class.is_available():
                    _log("warning", f"Provider {provider_type} not available (missing library)")
                    # Fallback to evcc provider
                    provider_class = self._provider_classes["evcc"]
                    cfg["evcc_host"] = self.evcc_host
                    cfg["evcc_port"] = self.evcc_port
                
                # Add evcc connection info for evcc provider
                if provider_type == "evcc":
                    cfg["evcc_host"] = self.evcc_host
                    cfg["evcc_port"] = self.evcc_port
                
                provider = provider_class(cfg)
                self._providers[evcc_name] = provider
                
                # Initialize state
                self._states[evcc_name] = VehicleState(
                    name=evcc_name,
                    evcc_name=evcc_name,
                    provider_type=provider_type,
                    capacity_kwh=cfg.get("capacity_kwh", 50),
                    provider_available=True
                )
                
                _log("info", f"Initialized {provider_type} provider for {evcc_name}")
                
            except Exception as e:
                _log("error", f"Failed to init provider: {e}")
    
    async def refresh_vehicle(self, evcc_name: str, force: bool = False) -> Optional[VehicleState]:
        """
        Refresh data for a specific vehicle.
        
        Args:
            evcc_name: Vehicle name in evcc
            force: Force refresh even if cache is fresh
            
        Returns:
            Updated VehicleState or None
        """
        if evcc_name not in self._providers:
            _log("warning", f"No provider for vehicle: {evcc_name}")
            return None
        
        provider = self._providers[evcc_name]
        state = self._states.get(evcc_name)
        
        _log("info", f"[{provider.PROVIDER_NAME}] Fetching data for {evcc_name}...")
        
        try:
            # Try direct API first
            data = await provider.get_data(force_refresh=force)
            
            if data and data.soc is not None:
                state.data = data
                state.data_source = "direct_api"
                state.provider_authenticated = provider._authenticated
                state.last_error = None
                state.consecutive_errors = 0
                _log("info", f"[{provider.PROVIDER_NAME}] ✓ Got SoC={data.soc}% for {evcc_name}")
            else:
                _log("info", f"[{provider.PROVIDER_NAME}] No data from API, trying evcc fallback...")
                # Fallback to evcc if connected
                evcc_data = await self._get_from_evcc(evcc_name)
                if evcc_data and evcc_data.soc is not None:
                    state.data = evcc_data
                    state.data_source = "evcc"
                    state.evcc_connected = True
                    _log("info", f"[{provider.PROVIDER_NAME}] Got SoC={evcc_data.soc}% for {evcc_name} from evcc")
                elif state.data:
                    # Keep cached data
                    state.data_source = "cache"
                    _log("debug", f"Using cached SoC={state.data.soc}% for {evcc_name}")
                else:
                    state.data_source = "unknown"
            
            state.last_error = provider._last_error
            
        except Exception as e:
            _log("error", f"Error refreshing {evcc_name}: {e}")
            state.last_error = str(e)
            state.consecutive_errors += 1
        
        return state
    
    async def _get_from_evcc(self, evcc_name: str) -> Optional[VehicleData]:
        """Get vehicle data from evcc API if connected."""
        from .evcc_provider import EVCCProvider
        
        evcc_provider = EVCCProvider({
            "evcc_name": evcc_name,
            "evcc_host": self.evcc_host,
            "evcc_port": self.evcc_port
        })
        
        return await evcc_provider.fetch_vehicle_data()
    
    async def refresh_all(self, force: bool = False) -> Dict[str, VehicleState]:
        """
        Refresh all vehicles.
        
        Args:
            force: Force refresh for all
            
        Returns:
            Dict of evcc_name -> VehicleState
        """
        _log("info", f"Refreshing {len(self._providers)} vehicle providers...")
        
        for name in self._providers.keys():
            _log("info", f"  Refreshing {name}...")
            try:
                await self.refresh_vehicle(name, force=force)
            except Exception as e:
                _log("error", f"  Error refreshing {name}: {e}")
        
        # Update evcc connection status
        await self._update_evcc_status()
        
        return self._states.copy()
    
    async def _update_evcc_status(self):
        """Check evcc for connected vehicles."""
        from .evcc_provider import EVCCProvider
        
        evcc_provider = EVCCProvider({
            "evcc_name": "_status_check",
            "evcc_host": self.evcc_host,
            "evcc_port": self.evcc_port
        })
        
        connected = evcc_provider.get_all_vehicles_from_evcc()
        self._evcc_connected = connected
        self._last_evcc_check = datetime.now(timezone.utc)
        
        # Update connection status in states
        for name, state in self._states.items():
            state.evcc_connected = name in connected
            
            # If connected and we have fresh data from evcc, update
            if name in connected:
                evcc_info = connected[name]
                if evcc_info.get("soc") is not None:
                    # Only update if our data is older
                    if not state.data or state.data.is_stale:
                        state.data = VehicleData(
                            soc=evcc_info.get("soc"),
                            range_km=evcc_info.get("range_km"),
                            is_charging=evcc_info.get("charging", False),
                            is_plugged_in=True
                        )
                        state.data_source = "evcc"
    
    def get_vehicle(self, evcc_name: str) -> Optional[VehicleState]:
        """Get current state for a vehicle (from cache)."""
        return self._states.get(evcc_name)
    
    def get_all_vehicles(self) -> Dict[str, VehicleState]:
        """Get all vehicle states."""
        return self._states.copy()
    
    def get_charge_needs(self, target_soc: int = 80) -> Dict[str, float]:
        """
        Calculate charge needed for all vehicles.
        
        Args:
            target_soc: Target SoC percentage
            
        Returns:
            Dict of evcc_name -> kWh needed
        """
        needs = {}
        for name, state in self._states.items():
            if state.soc is not None:
                need = max(0, (target_soc - state.soc) / 100 * state.capacity_kwh)
                needs[name] = round(need, 1)
            else:
                # Unknown SoC - assume needs charging
                needs[name] = 0  # Conservative: don't plan for unknown
        return needs
    
    # === Background Polling ===
    
    def start_polling(self):
        """Start background polling thread."""
        if self._running:
            return
        
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        _log("info", f"Vehicle polling started (interval: {self.poll_interval_minutes}min)")
    
    def stop_polling(self):
        """Stop background polling."""
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
    
    def _poll_loop(self):
        """Background polling loop."""
        _log("info", "Vehicle poll loop started")
        
        while self._running:
            try:
                _log("info", "Starting vehicle API poll...")
                
                # Run async refresh in new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    loop.run_until_complete(self.refresh_all())
                    _log("info", "Vehicle poll completed successfully")
                except Exception as e:
                    _log("error", f"Error in refresh_all: {e}")
                finally:
                    loop.close()
                
            except Exception as e:
                _log("error", f"Poll loop error: {e}")
            
            # Sleep in small increments so we can stop quickly
            _log("debug", f"Sleeping {self.poll_interval_minutes} minutes until next poll")
            for _ in range(self.poll_interval_minutes * 60):
                if not self._running:
                    break
                time.sleep(1)
    
    def trigger_immediate_refresh(self, evcc_name: Optional[str] = None):
        """Trigger an immediate refresh (e.g., when vehicle connects)."""
        async def _refresh():
            if evcc_name:
                await self.refresh_vehicle(evcc_name, force=True)
            else:
                await self.refresh_all(force=True)
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_refresh())
            else:
                loop.run_until_complete(_refresh())
        except RuntimeError:
            # No event loop - create one
            asyncio.run(_refresh())
    
    # === API Response Helpers ===
    
    def to_dict(self) -> dict:
        """Get full status as dict for API response."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "poll_interval_minutes": self.poll_interval_minutes,
            "providers_registered": list(self._provider_classes.keys()),
            "vehicles": {
                name: state.to_dict() 
                for name, state in self._states.items()
            },
            "evcc_connected_vehicles": list(self._evcc_connected.keys()),
            "charge_needs": self.get_charge_needs()
        }
