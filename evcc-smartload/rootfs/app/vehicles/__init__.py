"""
SmartPrice Vehicle Providers.

Modular system for fetching vehicle data from various APIs.

Usage:
    from vehicles import VehicleManager
    
    config = {
        "poll_interval_minutes": 30,
        "providers": [
            {
                "evcc_name": "KIA_EV9",
                "type": "kia",
                "user": "email@example.com",
                "password": "secret",
                "capacity_kwh": 99.8
            },
            {
                "evcc_name": "my_Twingo",
                "type": "renault",
                "user": "email@example.com",
                "password": "secret",
                "capacity_kwh": 22
            }
        ]
    }
    
    manager = VehicleManager(config)
    manager.start_polling()
    
    # Get vehicle state
    state = manager.get_vehicle("KIA_EV9")
    print(f"SoC: {state.soc}%")

Supported providers:
    - kia: KIA Connect / Bluelink (requires: pip install hyundai_kia_connect_api)
    - hyundai: Hyundai Bluelink (alias for kia)
    - renault: MY Renault / ZE Services (requires: pip install renault-api)
    - dacia: Dacia (alias for renault)
    - evcc: Fallback - data from evcc API when connected
    - custom: User-provided script
    - manual: No API, only evcc data or defaults
"""

from .base import VehicleProvider, VehicleData, VehicleState
from .manager import VehicleManager

# Import providers (they register themselves)
try:
    from .kia_provider import KiaProvider, HyundaiProvider
except ImportError:
    pass

try:
    from .renault_provider import RenaultProvider, DaciaProvider
except ImportError:
    pass

from .evcc_provider import EVCCProvider
from .custom_provider import CustomProvider, ManualProvider

__all__ = [
    "VehicleManager",
    "VehicleProvider",
    "VehicleData",
    "VehicleState",
    "KiaProvider",
    "HyundaiProvider", 
    "RenaultProvider",
    "DaciaProvider",
    "EVCCProvider",
    "CustomProvider",
    "ManualProvider",
]

__version__ = "1.0.0"
