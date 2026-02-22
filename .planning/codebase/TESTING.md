# Testing Patterns

**Analysis Date:** 2026-02-22

## Test Framework

**Runner:**
- No test framework detected (pytest, unittest, or similar not configured)
- No test files found in codebase

**Assertion Library:**
- Not applicable (no tests present)

**Run Commands:**
- No test suite exists
- No test configuration files (pytest.ini, setup.cfg, tox.ini, etc.)

## Test File Organization

**Location:**
- No test directory structure present
- No `tests/`, `test/`, or `*_test.py` files found

**Naming:**
- Not applicable

**Structure:**
- Not applicable

## Mocking

**Framework:**
- Not used (no test framework)

**Patterns:**
- Not applicable

**What to Mock:**
- Not applicable

**What NOT to Mock:**
- Not applicable

## Fixtures and Factories

**Test Data:**
- No fixture files present
- Configuration examples provided in YAML: `vehicles.yaml.example`, `drivers.yaml.example`
- In-memory data structures used during runtime for testing

**Location:**
- Example configurations in `rootfs/app/*.yaml.example`

## Coverage

**Requirements:**
- Not enforced (no coverage tools configured)

**View Coverage:**
- Not applicable

## Test Types

**Unit Tests:**
- Not implemented
- Recommendation: Test individual components like:
  - `config.Config` dataclass with various input combinations
  - `state.SystemState.to_vector()` normalization logic
  - `optimizer.HolisticOptimizer.optimize()` decision logic
  - `rl_agent.DQNAgent._discretize_state()` discretization consistency
  - `controller.Controller.calculate_dynamic_discharge_limit()` calculations

**Integration Tests:**
- Not implemented
- Recommendation: Test end-to-end flows:
  - Data collection pipeline: `DataCollector.get_current_state()`
  - Decision loop: optimizer + RL agent + controller
  - Vehicle monitor polling and state updates
  - API endpoints (`web/server.py` handlers)

**E2E Tests:**
- Not used

## Manual Testing Approach

The codebase relies on **runtime validation** rather than automated tests:

**Validation mechanisms in code:**

1. **Type hints for IDE checking** - Functions use `Optional[Type]`, `List[Dict]`, etc.
   ```python
   def get_effective_soc(self) -> float:
   def optimize(self, state: SystemState, tariffs: List[Dict]) -> Action:
   ```

2. **Defensive type checking** - Runtime verification of external data:
   ```python
   if isinstance(manual, dict):
       manual = manual.get("soc")
   if manual is not None and self.manual_soc_timestamp:
       try:
           manual = float(manual)
       except (TypeError, ValueError):
           manual = None
   ```

3. **Logging for observability** - All major operations logged:
   ```python
   log("info", f"VehicleMonitor: {name} SoC={result.get_effective_soc():.1f}% (source={result.data_source})")
   log("info", f"RL: {learning_steps} steps, ε={rl_agent.epsilon:.3f}")
   ```

4. **Health check endpoint** - `/health` API returns `{"status": "ok"}`:
   ```python
   elif path == "/health":
       self._json({"status": "ok", "version": VERSION})
   ```

5. **State snapshots in InfluxDB** - All decisions logged with state:
   ```python
   fields = {
       "battery_soc": float(state.battery_soc),
       "battery_action": int(action.battery_action),
       "price_ct": round(state.current_price * 100, 2),
   }
   self.write("smartload_state", fields)
   ```

6. **Decision log with cycle summaries** - Recent operations visible in API:
   ```python
   def get_last_cycle_summary(self) -> dict:
       return {
           "observations": [...],
           "plans": [...],
           "actions": [...],
       }
   ```

## Common Testing Patterns

**Data validation:**
- `ManualSocStore.get()` validates return type (v5.0.2 fix converted dict to float)
- `VehicleStatus.get_effective_soc()` handles multiple data sources with fallbacks

**Boundary testing:**
- `np.clip()` used extensively to constrain values: `np.clip(self.battery_power / 5000, -1, 1)`
- Price percentile calculations validated before use: `state.price_percentiles.get(20, state.current_price)`

**State consistency checks:**
- Vehicle polling tracks `last_poll` timestamp; data considered stale if `> 60min`
- Battery SoC constraints enforced: minimum 10%, maximum 90% normally
- EV target SoC configurable but validated against capacity

**Error injection readiness:**
- Configuration loading has fallback to defaults on any error:
  ```python
  try:
      with open(OPTIONS_PATH, "r") as f:
          raw = json.load(f)
  except Exception as e:
      log("warning", f"Could not load config: {e}, using defaults")
      cfg = Config()  # All defaults
  ```

- HTTP clients handle connection errors gracefully:
  ```python
  except requests.exceptions.ConnectionError as e:
      log("warning", f"InfluxDB connection error: {e}")
  except Exception as e:
      log("warning", f"InfluxDB write error: {e}")
  ```

## Recommended Testing Structure for Future

Given the current architecture, testing should follow this structure:

**Unit tests** (`tests/unit/`):
- `test_config.py` - Configuration loading, defaults, merging
- `test_state.py` - State vector normalization, SOC calculations, percentiles
- `test_optimizer.py` - LP decision logic, threshold comparisons
- `test_rl_agent.py` - Action discretization, Q-table updates, epsilon decay
- `test_controller.py` - Action application, limit calculations

**Integration tests** (`tests/integration/`):
- `test_data_collection.py` - Full state collection pipeline
- `test_decision_loop.py` - One complete decision cycle
- `test_vehicle_monitor.py` - Polling, caching, manual SoC override
- `test_web_api.py` - All HTTP endpoints with sample responses

**Fixtures** (`tests/fixtures/`):
- `state_fixtures.py` - Sample `SystemState` objects at various conditions
- `config_fixtures.py` - Various `Config` scenarios
- `vehicle_fixtures.py` - Mock vehicle data at different SOCs
- `tariff_fixtures.py` - Sample price forecasts and patterns

**Use pytest** for consistency with Python ecosystem:
- Configuration in `pyproject.toml` or `pytest.ini`
- `tests/` directory at repo root
- Run: `pytest tests/` or `pytest tests/ -cov=app` for coverage

---

*Testing analysis: 2026-02-22*
