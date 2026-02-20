"""
vehicles package for EVCC-Smartload.

Provides vehicle data providers and the VehicleManager coordinator.

Usage:
    from vehicles.manager import VehicleManager
    from vehicles.base import VehicleData

Provider types (configured via vehicles.yaml):
    - kia / hyundai / genesis  → KiaProvider (hyundai-kia-connect-api)
    - renault                  → RenaultProvider (renault-api)
    - custom                   → CustomProvider (configurable HTTP)
    - evcc                     → EvccProvider (evcc state only, no active poll)
"""

from vehicles.base import VehicleData
from vehicles.manager import VehicleManager

__all__ = ["VehicleData", "VehicleManager"]
