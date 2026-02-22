# Coding Conventions

**Analysis Date:** 2026-02-22

## Naming Patterns

**Files:**
- All lowercase with underscores: `main.py`, `vehicle_monitor.py`, `influxdb_client.py`
- Class files match class names: `EvccClient` in `evcc_client.py`, `HolisticOptimizer` in `optimizer/holistic.py`
- No `__init__` files needed unless subdirectory has multiple modules

**Functions:**
- snake_case: `get_all_vehicles()`, `calculate_dynamic_discharge_limit()`, `_discretize_state()` (private)
- Prefix with underscore for private/internal functions: `_load_vehicle_providers()`, `_poll_loop()`, `_add()`
- Verbs at start of action functions: `apply()`, `optimize()`, `set()`, `load()`, `save()`
- Getter methods: `get_effective_soc()`, `get_all_vehicles()`, `get_vehicle()`
- Predicate methods: `is_data_stale()`, `is_data_stale_threshold_minutes`

**Variables:**
- snake_case throughout: `battery_soc`, `ev_connected`, `ev_capacity_kwh`, `lp_action`, `rl_agent`
- Abbreviations acceptable in domain context: `soc`, `kw`, `kwh`, `ev`, `pv`, `lp`, `rl`, `cfg`
- Private variables use underscore prefix: `_lock`, `_last_poll`, `_enabled`, `_data`, `_manager`, `_thread`
- Constants in UPPER_CASE: `STALE_THRESHOLD_MINUTES`, `STATE_SIZE = 31`, `N_ACTIONS = 35`

**Types:**
- PascalCase classes: `SystemState`, `VehicleStatus`, `VehicleData`, `EvccClient`, `DQNAgent`, `Controller`
- Dataclass suffix not required but data containers typically use `@dataclass` decorator
- No `I` prefix for interfaces (Python convention)

## Code Style

**Formatting:**
- No explicit formatter detected (no `.prettierrc`, `.pylintrc`, or similar)
- 4-space indentation standard (Python default)
- Lines appear to follow reasonable length (~100-120 chars typical)
- Imports organized but not strictly controlled

**Linting:**
- No linting configuration files detected
- No type hints enforcement (optional static typing in use)

**Import Organization:**

1. Standard library imports:
   - `import json`, `import logging`, `import os`, `import sys`, `import threading`, `import time`
   - `from collections import defaultdict, deque`
   - `from dataclasses import dataclass, field`
   - `from datetime import datetime, timezone, timedelta`
   - `from pathlib import Path`
   - `from typing import Dict, List, Optional, Tuple, etc.`

2. Third-party library imports:
   - `import numpy as np`
   - `import requests`
   - `import yaml`

3. Local module imports (relative):
   - `from config import Config, load_config`
   - `from logging_util import log`
   - `from state import Action, SystemState`
   - Package imports: `from vehicles.manager import VehicleManager`
   - `from web import WebServer`

**Path Aliases:**
- No aliases detected; direct relative imports used
- Absolute imports from `app/` root (e.g., `from config import Config` in any subdirectory)

## Error Handling

**Patterns:**

1. **Logging over exceptions** - Most errors logged and execution continues:
   ```python
   try:
       result = self._manager.poll_vehicle(name)
       self._last_poll[name] = time.time()
   except Exception as e:
       log("error", f"VehicleMonitor: {name} initial poll failed: {e}")
   ```

2. **Silent failures with defaults** - None returns or empty collections on error:
   ```python
   def get_state(self) -> Optional[Dict]:
       try:
           r = self.sess.get(f"{self.base_url}/api/state", timeout=15)
           data = r.json()
           return data.get("result", data)
       except Exception:
           return None
   ```

3. **Graceful degradation** - Features disabled rather than crashed:
   ```python
   if not self._enabled:
       return
   ```

4. **Defensive type checks** - Especially for external data:
   ```python
   manual = self.manual_soc
   if manual is not None:
       if isinstance(manual, dict):
           manual = manual.get("soc")
       if manual is not None and self.manual_soc_timestamp:
           try:
               manual = float(manual)
           except (TypeError, ValueError):
               manual = None
   ```

5. **HTTP errors logged as warnings** - Non-fatal network issues:
   ```python
   if resp.status_code == 401:
       log("warning", f"InfluxDB auth failed (401)")
   elif resp.status_code not in (200, 204):
       log("warning", f"InfluxDB write returned {resp.status_code}")
   ```

**Thread Safety:**
- Explicit locking with `threading.Lock()` for shared state:
  ```python
  self._lock = threading.Lock()
  with self._lock:
      self._data[key] = value
  ```

## Logging

**Framework:** Python standard `logging` module

**Patterns:**
- Centralized in `logging_util.py` with simple `log(level, msg)` function:
  ```python
  def log(level: str, msg: str):
      getattr(_logger, level, _logger.info)(msg)
  ```

- Called throughout as: `log("info", "message")`, `log("error", "error message")`, `log("debug", "debug info")`

- Log levels used:
  - `"info"` - Normal operation, state changes, lifecycle events
  - `"warning"` - Recoverable errors, configuration issues, skipped operations
  - `"debug"` - Detailed internal state (config keys loaded, discretization, etc.)
  - `"error"` - Exceptions, failed API calls, critical operations

- Common patterns:
  ```python
  log("info", f"VehicleMonitor: polling {name}...")
  log("warning", f"Could not load config: {e}, using defaults")
  log("error", f"InfluxDB connection error: {e}")
  log("debug", f"Loaded options: {list(raw.keys())}")
  ```

## Comments

**When to Comment:**
- Module docstrings explain purpose and major changes between versions
- No inline comments unless logic is non-obvious
- Comments typically explain the "why", not the "what" (code should be self-documenting)

**Example docstrings:**
```python
"""
Holistic LP Optimizer — v5.0

Percentile-based charge thresholds replace static price limits.
Same greedy scheduling logic, but now LP and RL speak the same language.

Battery actions (→ Action.battery_action):
    0 = hold
    1 = charge_p20  threshold = P20
    2 = charge_p40  threshold = P40
    ...
"""
```

**JSDoc/Type hints:**
- Function signatures include type hints: `def optimize(self, state: SystemState, tariffs: List[Dict]) -> Action:`
- Return types always specified when non-void
- No detailed docstring for parameters (types are explicit)

## Function Design

**Size:** Functions typically 20-60 lines
- Some utility functions 5-15 lines
- Complex logic split across helper methods (e.g., `calculate_reward()` ~70 lines is among longest)

**Parameters:**
- Keep under 5 parameters for most functions
- Use `Config` object for multiple configuration values rather than individual params
- State objects (`SystemState`, `VehicleData`) used to pass complex data
- Optional parameters use `Optional[Type] = None` pattern

**Return Values:**
- Use `None` for optional returns
- Dataclass instances for structured returns
- Lists/dicts with clear semantics (e.g., `Dict[str, float]` for vehicle charge needs)
- No implicit boolean returns from operations

## Module Design

**Exports:**
- All classes and top-level functions are importable
- Private functions/classes use leading underscore
- Main entry point: `main()` in `main.py`

**Barrel Files:**
- No barrel files; each module imported directly: `from config import Config`
- Package `__init__.py` files minimal (only seen in `optimizer/`, `vehicles/`, `web/`)

**Module responsibilities (single responsibility principle):**
- `config.py` - Configuration loading and defaults
- `state.py` - Data structures and state management
- `evcc_client.py` - EVCC API communication
- `controller.py` - Apply decisions to hardware
- `optimizer/holistic.py` - LP optimization logic
- `rl_agent.py` - DQN reinforcement learning
- `vehicle_monitor.py` - Vehicle polling and status
- `comparator.py` - LP vs RL comparison and rewards
- `web/server.py` - HTTP API and dashboard
- `logging_util.py` - Centralized logging

---

*Convention analysis: 2026-02-22*
