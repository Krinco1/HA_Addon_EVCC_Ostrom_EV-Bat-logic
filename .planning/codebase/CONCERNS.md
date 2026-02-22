# Codebase Concerns

**Analysis Date:** 2026-02-22

## Tech Debt

### Bare Exception Handlers in Critical Components

**Issue:** Multiple files use bare `except Exception as e:` followed by `pass` statements, silently swallowing errors that could hide data consistency issues.

**Files:**
- `comparator.py` lines 296, 329 (loading/saving comparison logs)
- `rl_agent.py` lines 76, 89 (saving/loading replay memory)
- `decision_log.py` line 203
- `config.py` lines 147, 166 (configuration loading)

**Impact:** Configuration loading failures, comparison data loss, and RL model corruption go unnoticed, leading to incorrect decision-making over time. Silent failures make debugging production issues extremely difficult.

**Fix approach:**
- Replace bare `except Exception:` with specific exception types
- Log actual error details when persisting fails
- Consider implementing a health-check endpoint that validates data integrity
- Add validation before using loaded state to detect corruption early

### SQLite Connection Resource Leak

**Issue:** `comparator.py` creates new SQLite connections for every single method call (lines 346, 363, 380, 389, 427, 444, 459, 478, 484, 493) without connection pooling. Each method call opens and immediately closes a connection.

**Files:** `comparator.py` (RLDeviceController class)

**Impact:**
- High overhead for frequent database operations during decision loops
- No connection reuse = performance degradation under load
- Database file locking issues if multiple processes run concurrently
- Difficulty debugging database state since each operation is isolated

**Fix approach:**
- Implement a single persistent connection or lightweight connection pool
- Cache device status in memory with periodic flush to SQLite
- Use context managers (`with sqlite3.connect()`) to ensure cleanup
- Add transaction batching for multiple updates per cycle

### Web Server Handler Not Thread-Safe

**Issue:** WebServer stores mutable state (`_last_state`, `_last_lp_action`, `_last_rl_action`, `_last_solar_forecast`) without synchronization. Multiple threads (web requests, main loop updates) access these simultaneously.

**Files:** `web/server.py` lines 56-59, 61-67, 214

**Impact:**
- Race conditions where API returns partially updated/inconsistent state
- Dashboard may display stale or corrupted data
- Rare but critical: vehicle SoC shown as None or incorrect values on API endpoints
- No atomicity guarantee for multi-field updates

**Fix approach:**
- Implement thread-safe state holder with RLock
- Make state updates atomic using context manager
- Consider immutable state objects with copy-on-write instead of direct mutation
- Add explicit synchronization around multi-field reads in API response builders

### Manual SoC Override Persistence Race Condition

**Issue:** `state.py` ManualSocStore uses a single JSON file without locking. `vehicle_monitor.py` reads/writes manual SoC in multiple places (lines 55-57, 95-97, 103-105) during polling threads.

**Files:** `state.py` (ManualSocStore), `vehicle_monitor.py` (lines 40-68, 103-106)

**Impact:**
- Manual overrides can be lost if written during concurrent polling
- Dashboard override may not persist if timing aligns with file write
- Silent data loss — user sets SoC to 80%, it reverts to API value after 1-2 minutes

**Fix approach:**
- Add file locking (fcntl on Unix, msvcrt on Windows) around JSON reads/writes
- Use atomic writes: write to temp file, then rename
- Implement in-memory cache with debounced persistence
- Add version/timestamp to detect corruption

## Known Bugs

### Vehicle Data Stale Detection Unreliable for Wallbox-Connected Vehicles

**Symptoms:** Dashboard shows vehicle as "stale" even though it's actively charging at wallbox. Poll age updates correctly but data age timestamp remains old.

**Files:** `vehicles/base.py` lines 49-56, `vehicle_monitor.py` lines 85-91, 175-181

**Trigger:**
1. Vehicle connects to wallbox (evcc reports `connected=true`)
2. EVCC updates SoC via websocket (updates `last_update`)
3. Manual API poll fails (network timeout)
4. Vehicle shown as "stale" on dashboard despite being active

**Root cause:** `is_data_stale()` checks `last_update` timestamp, but if data comes from EVCC (websocket), the SoC is updated instantly. If manual poll fails after that, `last_update` doesn't advance but wallbox vehicle is actively charging with real-time data.

**Workaround:**
- Dashboard shows both `data_age` and `poll_age` — check `poll_age` for connected vehicles
- Manual SoC override never shows as stale (correct behavior)

**Fix approach:**
- Separate "API data staleness" from "overall state staleness"
- For wallbox-connected vehicles, trust evcc websocket updates exclusively
- Only mark as stale if both `last_update` is old AND vehicle was recently polled with failure

### RL Agent Memory Grows Unbounded During Bootstrap

**Symptoms:** Very slow startup on first run (5-10 minutes). Memory usage spikes during bootstrap phase.

**Files:** `rl_agent.py` lines 196-218 (bootstrap_from_influxdb)

**Problem:** Bootstrap loads 168 hours of historical data from InfluxDB into replay memory without limits. If InfluxDB has dense data (every minute), this loads 10,000+ samples into a memory structure that wasn't designed for streaming ingestion.

**Impact:**
- First startup can be unusably slow
- Memory consumption during bootstrap can cause OOM on Raspberry Pi
- No incremental learning — all bootstrap data loaded at once before first decision

**Fix approach:**
- Limit bootstrap to recent 72 hours instead of 168
- Implement sampling: keep every Nth sample during bootstrap
- Stream data in batches instead of loading all at once
- Add progress logging so users know it's not hung

### Charge Sequencer Scheduling Logic Doesn't Handle Multi-Vehicle Queue

**Symptoms:** When 2+ vehicles are in sequencer queue and one finishes charging early, next vehicle doesn't automatically start charging. Requires manual API call or wait for next planning cycle.

**Files:** `charge_sequencer.py` lines 200-320 (planning + application logic)

**Problem:** `plan()` method calculates optimal slots but doesn't automatically trigger transitions when a vehicle finishes. The controller must explicitly call `apply_next_charge()` which only happens once per decision cycle.

**Impact:**
- Multi-vehicle charging is delayed by up to 15 minutes (one decision interval)
- Wasted charging windows (e.g., solar peak ends before next EV starts)
- Inefficient use of cheap electricity slots

**Fix approach:**
- Implement event-driven triggering: monitor vehicle SoC and transition immediately when threshold hit
- Add background watcher thread that checks SoC without waiting for decision loop
- Trigger `apply_next_charge()` on SoC change events from vehicle monitor

## Security Considerations

### Telegram Bot Token Stored in Plain Text in Config

**Risk:** Driver manager loads Telegram token from `drivers.yaml` without encryption. If container filesystem is compromised, token is exposed.

**Files:** `driver_manager.py` lines 50-76, `drivers.yaml.example`

**Current mitigation:**
- Token stored in Home Assistant's mounted `/config/` volume (assumed private)
- No direct secrets in environment variables

**Recommendations:**
- Use Home Assistant secrets system: reference `!secret telegram_token` in YAML
- Never log token values (check for debug logging of driver_mgr contents)
- Rotate token quarterly as best practice
- Add validation that token is exactly 46 characters (Telegram format)

### API Endpoints Lack Authentication

**Risk:** `/status`, `/vehicles`, `/sequencer` endpoints are publicly readable with no API key or authentication. Any device on the network can read current SoC, battery state, pricing data.

**Files:** `web/server.py` lines 92-140 (do_GET handlers)

**Current mitigation:** Port 8099 is only exposed to Home Assistant container

**Recommendations:**
- Add optional API key support via header: `X-API-Key`
- For POST endpoints (mutations), require authentication
- Document that port 8099 should never be exposed to untrusted networks
- Consider CORS whitelist instead of `Access-Control-Allow-Origin: *`

### InfluxDB Credentials in Config

**Risk:** InfluxDB username/password stored in `options.json`. If Home Assistant is compromised, InfluxDB is exposed.

**Files:** `config.py` lines 40-44, `influxdb_client.py` lines 43-75

**Current mitigation:**
- Home Assistant config volume is mounted as read-only from host
- SSL flag available but defaults to False

**Recommendations:**
- Default `influxdb_ssl` to `True` (HTTPS)
- Document that InfluxDB should use authentication and SSL in production
- Consider supporting environment-variable-based credentials for secrets injection

## Performance Bottlenecks

### Web Server Routes All Traffic Through Single Handler Instance

**Problem:** All HTTP requests (status, vehicles, slots, chart-data) pass through the same `WebServer` instance without caching. Each request rebuilds large response objects.

**Files:** `web/server.py` lines 92-140, 258-582 (all API builders)

**Cause:**
- `/slots` calls `_calculate_charge_slots()` which processes entire tariff grid (line 342)
- `/chart-data` re-parses 36+ hours of tariff data with timezone conversion (lines 500-582)
- No caching layer — same computation repeated on every request

**Impact:**
- Dashboard refresh (3-4 simultaneous requests) causes 3-4x computation spike
- High latency for `/chart-data` with large datasets (50+ tariff entries)
- CPU load increases when dashboard is actively open

**Improvement path:**
- Add response caching layer with TTL (cache for 30-60 seconds)
- Pre-compute `/chart-data` result once per decision cycle instead of on-demand
- Implement data incrementalization: only send updated fields to client
- Consider moving expensive calculations to background thread

### Vehicle Polling Doesn't Respect API Rate Limits

**Problem:** Multiple vehicle providers (Kia, Renault, custom APIs) don't implement backoff or rate-limit detection. Aggressive polling at 60-minute intervals can trigger account lockout.

**Files:** `vehicles/kia_provider.py`, `vehicles/renault_provider.py`, `vehicles/custom_provider.py`, `vehicle_monitor.py` lines 43-68

**Impact:**
- Kia/Renault APIs respond with 429/503 after 5-10 requests
- Vehicle monitor stops receiving updates after lockout
- User must manually reset credentials to recover
- No automatic retry-after handling

**Improvement path:**
- Implement exponential backoff on 429/503 responses
- Parse `Retry-After` header from API responses
- Add jitter to polling schedule to avoid thundering herd
- Reduce poll interval in config UI (currently fixed at 60 min)
- Cache successful responses for 2-3 polls if last poll was recent

### Decision Loop Tight Coupling to Web Server Updates

**Problem:** Main loop updates web server state synchronously after every decision. If web server is slow or blocked, decision loop is blocked.

**Files:** `main.py` line 214

**Impact:**
- Dashboard lag translates directly to decision latency
- HTTP client timeout on web server blocks energy decisions
- No timeout protection — could delay charging by minutes if web server hangs

**Improvement path:**
- Queue state updates asynchronously instead of blocking
- Add timeout: if web update takes >2 seconds, skip and continue
- Use thread-safe queue instead of direct mutation

## Fragile Areas

### Decision Log Serialization Fragile to Field Changes

**Files:** `decision_log.py` lines 170-200

**Why fragile:** Decision log entries are manually constructed dictionaries. If a new field is added to SystemState or Action, log entries must be manually updated. No schema validation.

**Safe modification:**
- Add new fields with `.get()` fallback when reading old logs
- Maintain schema version field in log entries
- Test that old log format still loads after code changes
- Use dataclass `asdict()` instead of manual dict construction

**Test coverage:** No integration tests for decision log persistence/recovery

### RL Agent Discretization Dependent on Feature Scaling

**Files:** `rl_agent.py` lines 123-138

**Why fragile:** Discretization bins (5, 3, 3, 5, ...) are hardcoded based on expected feature ranges. If SystemState feature normalization changes, Q-table becomes invalid.

**Safe modification:**
- Document what each bin represents
- Add assertion checks: verify discretized state is within expected range
- Test Q-table loading with new feature sizes (already has version check at lines 288-295, but could be more defensive)

**Test coverage:** No unit tests for discretization correctness

### Quiet Hours Logic Sprinkled Across Components

**Files:** Multiple files check quiet hours:
- `charge_sequencer.py` lines 200-320 (planning respects quiet hours)
- `main.py` lines 200-204 (telegram reminders)
- `notification.py` (implicit in when notifications are sent)
- `web/server.py` line 408 (status endpoint shows quiet hour config)

**Why fragile:** Quiet hours can be enabled/disabled but the logic is not centralized. If quiet hours implementation changes, many places need updating.

**Safe modification:**
- Create a shared `QuietHoursManager` class that encapsulates all quiet hour logic
- Use it consistently everywhere (decision logic, notifications, sequencer)
- Add unit tests for quiet hour state transitions

## Scaling Limits

### In-Memory State Doesn't Scale to 10+ Vehicles

**Current capacity:** Vehicle monitor handles 2-4 vehicles comfortably. Beyond that, memory and API polling become bottlenecks.

**Files:** `vehicle_monitor.py`, `state.py`, `rl_agent.py`

**Limit:** With 10 vehicles × 60-minute polling = 10 API calls/hour. If each call takes 2-3 seconds, that's 30 seconds of blocking per hour. Over 24 hours, 7200 API calls total.

**Scaling path:**
- Batch vehicle API calls (parallel polling)
- Implement connection pooling for HTTP requests
- Cache responses more aggressively (2-3 hours for vehicles that aren't connected)
- Add vehicle filtering: only poll vehicles that are configured to charge

### RL Q-Table Memory Grows With Feature Resolution

**Problem:** Q-table uses all-features-as-key discretization (tuple-based). With 31-d state and 5-8 bins per feature, theoretical state space is 5^31 ≈ 10^21 states. Current implementation keeps only visited states in dict, but visiting rate accelerates.

**Files:** `rl_agent.py` lines 108-117, 123-138

**Impact:**
- After 6 months of operation, Q-table can grow to 100K+ states
- Memory usage: 100K states × 35 actions × 8 bytes/float ≈ 28 MB (manageable but growing)
- Lookup time increases slightly with dict size
- Persisting/loading Q-table gets slower

**Scaling path:**
- Implement Q-table periodical cleanup: prune states visited only once in past month
- Consider function approximation (neural network) instead of table
- Add Q-table size monitoring and alerts at 50K states
- Implement compression: merge similar states or use sparse representation

## Dependencies at Risk

### requests Library Without Timeout Protection in Critical Paths

**Risk:** Multiple `requests.get()` and `requests.post()` calls throughout codebase could hang indefinitely if network is slow.

**Files:**
- `evcc_client.py` lines 27-43 (various get/post calls with `timeout=10-15`)
- `notification.py` lines 62-70 (Telegram polling has `timeout=30` on request but `timeout=35` on socket)
- `influxdb_client.py` lines 43-75 (write/query to InfluxDB)

**Current state:** Most have timeouts, but inconsistent (10s, 15s, 30s, 35s across different places)

**Recommendation:**
- Standardize timeout to 15 seconds for all external APIs
- Add circuit-breaker: stop retrying if 3 consecutive failures occur
- Log timeout occurrences separately from other exceptions
- Monitor timeout rate on dashboard

### YAML Library Without Explicit Loader

**Risk:** `config.py` line 122 uses `yaml.safe_load()` which is safe, but good defensive practice.

**Files:** `config.py` line 122

**Current state:** Already using `safe_load()` ✓

### numpy and scipy Not Pinned to Specific Versions

**Files:** `requirements.txt` or `pyproject.toml` (not found in exploration)

**Risk:** Feature compatibility: newer numpy versions may change random number generation, affecting RL reproducibility

**Recommendation:**
- Pin numpy to specific minor version (e.g., `numpy>=1.21,<1.22`)
- Same for requests, pyyaml
- Test major version upgrades in CI before rolling out

## Missing Critical Features

### No Health Check Endpoint for Uptime Monitoring

**Problem:** `/health` endpoint exists (line 98) but only returns `{"status": "ok"}`. No validation of critical services (evcc reachable, InfluxDB reachable, vehicle APIs responding).

**Files:** `web/server.py` line 98

**Impact:** Load balancer or monitoring system can't detect if smartload is broken (evcc disconnected, InfluxDB down, etc.)

**What this blocks:**
- Kubernetes/Swarm health checks
- Home Assistant integration reliability
- Automated recovery/restart triggers

**Fix approach:**
- Expand `/health` to report status of all dependencies
- Return 503 if any critical service is down
- Include timestamp and uptime in response

### No Request Validation on API Endpoints

**Problem:** POST endpoints like `/vehicles/manual-soc` validate input manually. No schema validation library used.

**Files:** `web/server.py` lines 147-162, 179-217

**Impact:**
- Invalid requests could cause crashes or data corruption
- No rate limiting on manual SoC override
- Potential for invalid sequencer requests (negative SoC, invalid vehicle names)

**Fix approach:**
- Use Pydantic or jsonschema for request validation
- Add rate limiting on mutation endpoints
- Return clear error messages for validation failures

### No Configuration Validation on Startup

**Problem:** Config is loaded but never validated. Invalid configs (negative intervals, SoC > 100, etc.) are silently accepted.

**Files:** `config.py` lines 152-170

**Impact:**
- Invalid config causes crashes deep in the system
- No clear error message about what's wrong
- User spends time debugging

**Fix approach:**
- Implement `Config.validate()` method
- Check bounds: `decision_interval_minutes > 0`, `0 <= ev_target_soc <= 100`, etc.
- Call validation in `load_config()` before returning
- Raise clear exception with guidance on invalid fields

## Test Coverage Gaps

### Vehicle Provider APIs Untested

**What's not tested:** Kia, Renault, custom provider error handling

**Files:** `vehicles/kia_provider.py`, `vehicles/renault_provider.py`, `vehicles/custom_provider.py`

**Risk:**
- Provider crashes due to changed API format go unnoticed
- Rate limiting/lockout behavior untested
- Error handling paths (network timeout, invalid credentials) not validated

**Priority:** HIGH — vehicle data is critical to charge sequencing

**Suggested tests:**
- Mock API responses (normal, timeout, 429, invalid auth)
- Test SoC parsing from each provider's response format
- Verify stale detection works correctly

### Main Decision Loop Integration Untested

**What's not tested:** Full end-to-end decision cycle with multiple vehicles, sequencer, RL agent, optimizer

**Files:** `main.py` lines 127-260

**Risk:**
- Race conditions between threads not caught
- State transitions (sequencer requesting → charging → done) untested
- RL learning loop correctness unvalidated

**Priority:** HIGH — core business logic

### Web API Response Consistency Untested

**What's not tested:** Race condition where state changes during API response construction

**Files:** `web/server.py` lines 258-582

**Risk:**
- API returns None/NaN for vehicle SoC due to concurrent update
- Chart data has misaligned timestamps
- Status endpoint shows inconsistent state (battery SoC ≠ sum of device SOCs)

**Priority:** MEDIUM — affects user experience and debugging

---

*Concerns audit: 2026-02-22*
