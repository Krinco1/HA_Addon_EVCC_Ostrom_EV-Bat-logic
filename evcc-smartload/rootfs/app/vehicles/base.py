"""
Base classes for vehicle providers.
Each provider implements fetching SoC and other data from a specific vehicle API.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class VehicleData:
    """Standardized vehicle data returned by all providers."""
    soc: Optional[float] = None              # Battery SoC in %
    range_km: Optional[int] = None           # Estimated range in km
    is_charging: bool = False                # Currently charging?
    is_plugged_in: bool = False              # Connected to any charger?
    odometer_km: Optional[float] = None      # Odometer reading
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_data: Dict[str, Any] = field(default_factory=dict)  # Provider-specific extras
    
    def __post_init__(self):
        """Ensure timestamp is a datetime object."""
        if isinstance(self.timestamp, str):
            try:
                self.timestamp = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
            except:
                self.timestamp = datetime.now(timezone.utc)
        if self.timestamp and self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)
    
    @property
    def age_seconds(self) -> int:
        """How old is this data in seconds."""
        try:
            ts = self.timestamp
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return int((datetime.now(timezone.utc) - ts).total_seconds())
        except:
            return 0
    
    @property
    def is_stale(self) -> bool:
        """Data older than 4 hours is considered stale."""
        return self.age_seconds > 4 * 3600
    
    def to_dict(self) -> dict:
        ts = self.timestamp
        if isinstance(ts, str):
            ts_str = ts
        else:
            ts_str = ts.isoformat() if ts else None
        return {
            "soc": self.soc,
            "range_km": self.range_km,
            "is_charging": self.is_charging,
            "is_plugged_in": self.is_plugged_in,
            "odometer_km": self.odometer_km,
            "timestamp": ts_str,
            "age_seconds": self.age_seconds,
            "is_stale": self.is_stale
        }


@dataclass 
class VehicleState:
    """Complete vehicle state including metadata about data source."""
    name: str                                # evcc vehicle name
    evcc_name: str                           # Name in evcc config
    provider_type: str                       # 'kia', 'renault', 'gwm', 'evcc', 'manual'
    capacity_kwh: float                      # Battery capacity
    
    # Data
    data: Optional[VehicleData] = None
    
    # Source tracking
    data_source: str = "unknown"             # 'direct_api', 'evcc', 'cache', 'unknown'
    provider_available: bool = False         # Is direct API configured?
    provider_authenticated: bool = False     # Is direct API logged in?
    evcc_connected: bool = False             # Connected to evcc loadpoint?
    
    # Error tracking
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    consecutive_errors: int = 0
    
    @property
    def soc(self) -> Optional[float]:
        return self.data.soc if self.data else None
    
    @property
    def has_valid_soc(self) -> bool:
        """SoC is known and not too old."""
        return self.data is not None and self.data.soc is not None and not self.data.is_stale
    
    @property
    def charge_needed_kwh(self) -> float:
        """How much energy needed to reach 80%."""
        if self.soc is None:
            return 0
        target = 80
        return max(0, (target - self.soc) / 100 * self.capacity_kwh)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "evcc_name": self.evcc_name,
            "provider_type": self.provider_type,
            "capacity_kwh": self.capacity_kwh,
            "soc": self.soc,
            "data_source": self.data_source,
            "provider_available": self.provider_available,
            "provider_authenticated": self.provider_authenticated,
            "evcc_connected": self.evcc_connected,
            "charge_needed_kwh": round(self.charge_needed_kwh, 1),
            "has_valid_soc": self.has_valid_soc,
            "last_error": self.last_error,
            "data": self.data.to_dict() if self.data else None
        }


class VehicleProvider(ABC):
    """
    Abstract base class for vehicle API providers.
    
    Each provider (KIA, Renault, GWM, etc.) implements this interface.
    """
    
    PROVIDER_NAME: str = "base"
    
    def __init__(self, config: dict):
        """
        Initialize provider with configuration.
        
        Args:
            config: Provider-specific config (user, password, vin, etc.)
        """
        self.config = config
        self.evcc_name = config.get("evcc_name", "unknown")
        self.capacity_kwh = config.get("capacity_kwh", 50)
        
        self._authenticated = False
        self._last_data: Optional[VehicleData] = None
        self._last_fetch: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._consecutive_errors = 0
        
        logger.info(f"[{self.PROVIDER_NAME}] Initialized provider for {self.evcc_name}")
    
    @abstractmethod
    async def authenticate(self) -> bool:
        """
        Login to vehicle API.
        
        Returns:
            True if authentication successful
        """
        pass
    
    @abstractmethod
    async def fetch_vehicle_data(self) -> Optional[VehicleData]:
        """
        Fetch current vehicle state from API.
        
        Returns:
            VehicleData or None on error
        """
        pass
    
    @classmethod
    def get_provider_name(cls) -> str:
        """Return provider identifier."""
        return cls.PROVIDER_NAME
    
    @classmethod
    def get_required_config(cls) -> list:
        """Return list of required config keys."""
        return ["evcc_name"]
    
    async def get_data(self, force_refresh: bool = False) -> Optional[VehicleData]:
        """
        Get vehicle data, using cache if appropriate.
        
        Args:
            force_refresh: Bypass cache and fetch fresh data
            
        Returns:
            VehicleData or None
        """
        # Check if we need to authenticate
        if not self._authenticated:
            try:
                self._authenticated = await self.authenticate()
                if not self._authenticated:
                    self._last_error = "Authentication failed"
                    return self._last_data
            except Exception as e:
                self._last_error = f"Auth error: {e}"
                logger.error(f"[{self.PROVIDER_NAME}] {self._last_error}")
                return self._last_data
        
        # Check cache
        if not force_refresh and self._last_data and self._last_fetch:
            cache_age = (datetime.now(timezone.utc) - self._last_fetch).total_seconds()
            min_interval = self.config.get("min_interval_seconds", 300)  # 5 min default
            if cache_age < min_interval:
                logger.debug(f"[{self.PROVIDER_NAME}] Using cached data ({cache_age:.0f}s old)")
                return self._last_data
        
        # Fetch fresh data
        try:
            data = await self.fetch_vehicle_data()
            if data:
                self._last_data = data
                self._last_fetch = datetime.now(timezone.utc)
                self._last_error = None
                self._consecutive_errors = 0
                logger.info(f"[{self.PROVIDER_NAME}] Fetched SoC={data.soc}% for {self.evcc_name}")
            return data
        except Exception as e:
            self._consecutive_errors += 1
            self._last_error = str(e)
            logger.error(f"[{self.PROVIDER_NAME}] Fetch error: {e}")
            return self._last_data  # Return cached data on error
    
    def get_state(self) -> VehicleState:
        """Get complete vehicle state including metadata."""
        return VehicleState(
            name=self.evcc_name,
            evcc_name=self.evcc_name,
            provider_type=self.PROVIDER_NAME,
            capacity_kwh=self.capacity_kwh,
            data=self._last_data,
            data_source="direct_api" if self._last_data else "unknown",
            provider_available=True,
            provider_authenticated=self._authenticated,
            evcc_connected=False,  # Will be updated by manager
            last_error=self._last_error,
            consecutive_errors=self._consecutive_errors
        )
    
    @property
    def is_healthy(self) -> bool:
        """Provider is working without repeated errors."""
        return self._consecutive_errors < 3
