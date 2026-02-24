# Phase 2: Vehicle Reliability - Research

**Researched:** 2026-02-22
**Domain:** Vehicle SoC event-driven refresh, charge sequencer completion detection, RL bootstrap memory management
**Confidence:** HIGH (analysis of live codebase — all bugs are directly traceable in the source)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RELI-01 | Vehicle SoC is correct and current when the vehicle is connected to the wallbox | Connection-triggered refresh via `trigger_refresh()` — the mechanism exists but is never invoked automatically on connect events; must be wired to evcc loadpoint `connected` state change detection |
| RELI-02 | Charge Sequencer switches immediately to next vehicle when current vehicle finishes (no 15-minute delay) | `sequencer.update_soc()` is never called automatically; sequencer's `need_kwh` stays stale until the next full `plan()` call; fix is to call `update_soc()` on every decision cycle and detect completion within-cycle |
| RELI-05 | RL Bootstrap caps memory use and logs progress | `bootstrap_from_influxdb()` loads all rows in one shot with no progress log; cap by processing in bounded chunks and emitting "Loading history: N/M records" at regular intervals |
</phase_requirements>

---

## Summary

Phase 2 fixes three independent reliability bugs that were accepted as blockers in STATE.md: SoC staleness (RELI-01), charge sequencer slow handoff (RELI-02), and silent RL bootstrap (RELI-05). All three bugs are diagnosable by reading the existing code; no external library research is needed. The fixes are surgical and use only Python stdlib.

**RELI-01 root cause:** `VehicleMonitor.trigger_refresh()` is never called when a vehicle connects. The API poll runs on a 60-minute timer. When a Kia or Renault connects to the wallbox mid-cycle, the displayed SoC is the last API poll value (up to 60 minutes stale). evcc does report `vehicleSoc` in the loadpoint state, and `update_from_evcc()` correctly writes it to `VehicleData.soc` — but only for vehicles whose API poll sets a stale value before they connect. The real fix is to detect the transition from `connected=False` to `connected=True` in `update_from_evcc()` and call `trigger_refresh()` immediately for vehicles with API providers, so the SoC from the vehicle API (not just evcc's last cached value) is retrieved within the same decision cycle.

**RELI-02 root cause:** `ChargeSequencer.update_soc()` is never called from the main decision loop. The sequencer's `need_kwh` field is initialised at `add_request()` time and must be updated as charging progresses. Without `update_soc()` being called, a vehicle can reach 100% SoC but its `ChargeRequest.status` stays `"scheduled"` indefinitely. The sequencer's `_rank_vehicles()` keeps giving the finished vehicle priority (it is connected). When `plan()` is eventually called, `expire_old_requests()` only expires requests older than 36 hours or with status `"done"` — and status only becomes `"done"` if `update_soc()` is called with `need_kwh < 0.5`. The fix: call `sequencer.update_soc(vehicle_name, current_soc)` for every connected vehicle every decision cycle. Additionally, detect disconnection events to mark requests as done or remove them.

**RELI-05 root cause:** `bootstrap_from_influxdb()` fetches all rows at once into a Python list and iterates silently. On a Raspberry Pi with months of history (e.g. 8760h = 1 year = up to 8760 rows), this is manageable in RAM (8760 dicts × ~200 bytes each ≈ 1.7 MB). The actual risk is the `ReplayMemory` with `rl_memory_size=10000` entries, each containing two 31-d float32 numpy arrays (31×4 bytes × 2 ≈ 248 bytes per entry) plus overhead ≈ ~10 MB total. More critically: if `hours` is ever increased to months, the InfluxDB response could be large; and the complete absence of logging makes startup appear frozen on a slow Pi (startup can take 2-3 minutes with a cold ARM filesystem). The fix: add chunked fetching with a configurable row cap (`rl_bootstrap_max_records`, default 1000), and emit progress logs every 100 records.

**Primary recommendation:** Three surgical fixes — (1) connection-event detection triggers immediate vehicle API refresh, (2) sequencer update_soc called every cycle from the main loop, (3) bootstrap logs progress and caps record count.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `threading.Lock` | stdlib | Guard `_prev_connected` dict in VehicleMonitor | Already used throughout; lightweight, no dependencies |
| `time.time()` | stdlib | Timestamp last connection event for stale detection | Already in use in `_poll_loop` |
| `logging_util.log` | project | Progress reporting during bootstrap | Already used for all diagnostic output |
| `sys.getsizeof` | stdlib (optional) | Memory diagnostics during testing | Only for validation; not production code |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `resource` (stdlib) | Unix only | Get peak RSS for memory verification | Use in tests only; not available on Windows |
| `numpy` | already installed | Array operations in bootstrap | Already in Dockerfile; no new dep |

**Installation:** No new packages. All fixes use Python stdlib and existing project modules.

---

## Architecture Patterns

### Recommended Changes (Minimal Surgical Scope)

```
evcc-smartload/rootfs/app/
├── vehicle_monitor.py   # MODIFIED: connection-event detection + trigger_refresh()
├── main.py              # MODIFIED: sequencer.update_soc() call in decision loop
└── rl_agent.py          # MODIFIED: bootstrap progress logging + record cap
```

No new files needed. All three fixes are contained changes within existing files.

### Pattern 1: Connection-Event Detection in VehicleMonitor

**What:** Track `connected_to_wallbox` state per vehicle across `update_from_evcc()` calls. When a vehicle transitions from `False` to `True`, immediately call `trigger_refresh()` for that vehicle (if it has an API provider).

**When to use:** Anytime evcc reports a loadpoint connection change. The `update_from_evcc()` call already runs on every data collection cycle (every 60 seconds via `DataCollector`).

**Key constraint:** `trigger_refresh()` only adds the vehicle name to `_refresh_requested` set — the actual API poll happens in `_poll_loop()` on its 30-second check cycle. So the refresh happens within 30 seconds of connection detection. This is well within "the same decision cycle" (15 minutes).

**Example:**

```python
# vehicle_monitor.py — VehicleMonitor.__init__() addition:
self._prev_connected: Dict[str, bool] = {}   # name → last known connected state

# vehicle_monitor.py — update_from_evcc() addition (after VehicleManager call):
def update_from_evcc(self, evcc_state: dict):
    """Pass evcc state to vehicle manager and detect connection events."""
    try:
        self._manager.update_from_evcc(evcc_state)
        # Re-apply manual SoC overrides
        for name, v in self._manager.get_all_vehicles().items():
            manual = self.manual_store.get(name)
            v.manual_soc = manual

        # Connection-event detection: trigger immediate API refresh on connect
        for name, v in self._manager.get_all_vehicles().items():
            prev = self._prev_connected.get(name, False)
            if v.connected_to_wallbox and not prev:
                # Just connected: trigger immediate poll if this vehicle has an API
                if name in self._manager.get_pollable_names():
                    log("info", f"VehicleMonitor: {name} connected — triggering immediate SoC refresh")
                    self.trigger_refresh(name)
            self._prev_connected[name] = v.connected_to_wallbox

    except Exception as e:
        log("error", f"VehicleMonitor update_from_evcc error: {e}")
```

**Why this works:** `get_pollable_names()` returns only vehicles with `supports_active_poll=True` (Kia, Renault providers). For evcc-only vehicles, `trigger_refresh()` is not called — evcc already reports their current SoC in the loadpoint data, so no extra poll is needed.

### Pattern 2: Sequencer SoC Sync in Main Decision Loop

**What:** After `all_vehicles = vehicle_monitor.get_all_vehicles()`, iterate connected vehicles and call `sequencer.update_soc()` for any vehicle in the sequencer's `requests` dict. This ensures the sequencer's internal `need_kwh` and `status` reflect the current SoC every cycle.

**When to use:** Every decision cycle, immediately before `sequencer.plan()`.

**Example:**

```python
# main.py — inside the while True: loop, before sequencer.plan():

if sequencer is not None:
    # Sync current SoC into sequencer for all vehicles with active requests
    for vname, vdata in all_vehicles.items():
        if vname in sequencer.requests:
            current_soc = vdata.get_effective_soc()
            sequencer.update_soc(vname, current_soc)
            # Also remove request if vehicle has disconnected
            if not vdata.connected_to_wallbox and sequencer.requests[vname].status == "done":
                sequencer.remove_request(vname)
                log("info", f"Sequencer: {vname} disconnected and done — request removed")

    connected_vehicle = next(
        (n for n, v in all_vehicles.items() if v.connected_to_wallbox), None
    )
    sequencer.plan(tariffs, solar_forecast, connected_vehicle, now)
    sequencer.apply_to_evcc(now)
```

**Why this works:** `ChargeRequest.status` becomes `"done"` in `update_soc()` when `need_kwh < 0.5`. On the next `plan()` call, `expire_old_requests()` removes done requests. `apply_to_evcc()` then finds no active slot for the finished vehicle and (if another vehicle is scheduled) activates the next one. This completes within one decision cycle (15 minutes).

**Edge case — disconnection without done:** If a vehicle disconnects before reaching target SoC (user takes the car), the request stays pending. This is correct — it can be re-scheduled. The `expire_old_requests()` will clean it up after 36 hours.

### Pattern 3: RL Bootstrap with Progress Logging and Record Cap

**What:** Fetch InfluxDB history in bounded batches, log progress every N records, stop after `max_records`. Return early with a log message if the record count exceeds the cap.

**When to use:** `bootstrap_from_influxdb()` in `rl_agent.py`. Only called on fresh install (no saved model).

**Memory analysis:**
- Each history row from InfluxDB is one Python dict: 3 keys × ~50 bytes avg = ~150 bytes per row
- At 1000 rows: ~150 KB for the raw list — negligible
- Per bootstrap iteration: two 31-d float32 numpy arrays (2 × 31 × 4 = 248 bytes) + scalars ≈ 300 bytes per processed record
- At 1000 records: ~300 KB peak during processing
- `ReplayMemory` at 10000 capacity: 10000 × (248 + overhead) ≈ ~5-10 MB — acceptable
- On Raspberry Pi 4 with 4 GB RAM: even 10000 records is completely safe
- On Raspberry Pi 3 with 1 GB RAM: same, well within budget

**Example:**

```python
# rl_agent.py — bootstrap_from_influxdb() replacement:

def bootstrap_from_influxdb(self, influx, hours: int = 168,
                             max_records: int = 1000) -> int:
    """Bootstrap Q-table from historical InfluxDB data.

    Args:
        influx: InfluxDBClient instance
        hours: History window to fetch (default: 7 days = 168h)
        max_records: Maximum records to process (memory guard, default: 1000)
    """
    try:
        log("info", f"RL bootstrap: fetching up to {hours}h of InfluxDB history...")
        data = influx.get_history_hours(hours)
        if not data:
            log("info", "RL bootstrap: no history available — starting fresh")
            return 0

        total = min(len(data), max_records)
        if len(data) > max_records:
            log("warning",
                f"RL bootstrap: {len(data)} records found, capping at {max_records} "
                f"(set rl_bootstrap_max_records in config to increase)")

        log("info", f"RL bootstrap: processing {total} records...")
        learned = 0
        prev = None

        for i, point in enumerate(data[:max_records]):
            # Progress log every 100 records (so user sees startup is active)
            if i > 0 and i % 100 == 0:
                log("info", f"RL bootstrap: Loading history: {i}/{total} records")

            try:
                battery_soc = point.get("battery_soc") or 50
                price = point.get("price") or point.get("price_ct", 30) / 100
                state_vec = np.zeros(self.STATE_SIZE)
                state_vec[0] = battery_soc / 100
                state_vec[3] = price / 0.5
                if prev:
                    delta = battery_soc - (prev.get("battery_soc") or 50)
                    prev_price = prev.get("price") or prev.get("price_ct", 30) / 100
                    if delta > 2 and prev_price < 0.25:
                        aidx = self._tuple_to_action(2, 0)
                        reward = 0.5
                    elif delta < -2 and prev_price > 0.30:
                        aidx = self._tuple_to_action(6, 0)
                        reward = 0.3
                    elif delta > 2 and prev_price > 0.35:
                        aidx = self._tuple_to_action(2, 0)
                        reward = -0.3
                    else:
                        aidx = self._tuple_to_action(0, 0)
                        reward = 0
                    prev_vec = np.zeros(self.STATE_SIZE)
                    prev_vec[0] = (prev.get("battery_soc") or 50) / 100
                    prev_vec[3] = prev_price / 0.5
                    sk = self._discretize_state(prev_vec)
                    nk = self._discretize_state(state_vec)
                    target = reward + self.gamma * np.max(self.q_table[nk])
                    self.q_table[sk][aidx] += (
                        self.learning_rate * 0.3 * (target - self.q_table[sk][aidx])
                    )
                    learned += 1
                prev = point
            except Exception:
                continue

        log("info", f"RL bootstrap: complete — {learned}/{total} experiences loaded")
        return learned
    except Exception as e:
        log("warning", f"RL bootstrap from InfluxDB failed: {e}")
        return 0
```

**Progress log output example:**
```
RL bootstrap: fetching up to 168h of InfluxDB history...
RL bootstrap: processing 167 records...
RL bootstrap: complete — 166/167 experiences loaded
```
For large histories (if hours is increased):
```
RL bootstrap: fetching up to 8760h of InfluxDB history...
RL bootstrap: 8760 records found, capping at 1000
RL bootstrap: processing 1000 records...
RL bootstrap: Loading history: 100/1000 records
RL bootstrap: Loading history: 200/1000 records
...
RL bootstrap: Loading history: 900/1000 records
RL bootstrap: complete — 999/1000 experiences loaded
```

### Anti-Patterns to Avoid

- **Polling inside `update_from_evcc()`:** Never call `self._manager.poll_vehicle(name)` directly from `update_from_evcc()`. Polling is I/O and must happen in `_poll_loop()`, not in the data collection synchronous path. Use `trigger_refresh()` which safely signals the background thread.
- **Removing sequencer requests when vehicle is done but still connected:** A vehicle may reach target SoC but remain physically connected. Keep the request in `status="done"` until disconnect. Only remove on explicit `remove_request()` or when `expire_old_requests()` cleans it up. The `apply_to_evcc()` method already handles this — it checks `_get_active_slot(now)` which has no slot for a done vehicle.
- **Infinite bootstrap without cap:** Never remove the `max_records` cap from bootstrap. If the InfluxDB query returns 50000 rows (years of history at 15-min granularity), the Python list alone would be 50000 × 150B ≈ 7.5 MB, but the per-iteration numpy array allocation would spike memory before GC runs. The cap prevents this.
- **Loading `get_history_hours()` result into a large in-memory list without a count check:** The InfluxDB `get_history_hours()` method currently does a `GROUP BY time(1h)` which bounds results to `hours` rows. If the query is ever changed to finer granularity, the row count explodes. The `max_records` cap in bootstrap is the safety valve.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Connection event detection | Custom evcc websocket subscription | Connection-state diff in `update_from_evcc()` | evcc REST API is already polled every 60s — detecting transitions in existing data is zero-cost, no new protocol |
| Sequencer SoC sync | Background thread watching vehicle SoC | Inline `update_soc()` in main decision loop | Decision loop already has current SoC data from `get_all_vehicles()` — no extra I/O needed |
| Memory measurement | psutil or custom memory tracker | `max_records` hard cap | Hard cap is simpler, deterministic, and works on Alpine without additional dependencies |
| Progress bar UI | Rich/tqdm | `log("info", f"Loading history: {i}/{total}")` | Container logs are the user interface on HA add-ons; text progress is sufficient and zero overhead |

**Key insight:** All three bugs are missing "wiring" bugs — the mechanisms exist (trigger_refresh, update_soc, progress logging) but are not called in the right places. The fixes are connecting existing machinery, not building new machinery.

---

## Common Pitfalls

### Pitfall 1: trigger_refresh() Race with _poll_loop()

**What goes wrong:** `trigger_refresh(name)` adds to `_refresh_requested` while `_poll_loop()` is mid-iteration clearing the set. The name is added after the clear, so the refresh is deferred another 30 seconds.

**Why it happens:** `_poll_loop()` reads `refresh_now = set(self._refresh_requested)` then clears `_refresh_requested` under `_lock`. If `trigger_refresh()` runs between the read and clear (both happen inside `with self._lock`), there's no race — the lock protects this. BUT if `trigger_refresh()` runs after the `clear()` call (which also happens inside `with self._lock`), the new name is correctly placed for the next 30-second cycle. The timing is: worst case, the refresh happens 30 seconds later. This is acceptable.

**How to avoid:** No additional fix needed — the existing `_lock` in `VehicleMonitor` already protects `_refresh_requested`. The worst-case delay is one 30-second poll cycle (vs. the next 60-minute scheduled poll). This satisfies RELI-01.

**Warning signs:** Log shows "triggering immediate SoC refresh" for a vehicle but the SoC update log appears 30+ seconds later — this is normal.

### Pitfall 2: Sequencer Removes Request Before Charging Stops

**What goes wrong:** `update_soc()` is called with a SoC ≥ target, setting status to `"done"`. On the next `expire_old_requests()` call (inside `plan()`), the request is removed. `apply_to_evcc()` then sets the loadpoint to `"off"`. But if the vehicle is still physically connected and the wallbox was already in `"pv"` or `"minpv"` mode, setting it to `"off"` may interrupt ongoing charging unnecessarily.

**Why it happens:** SoC reporting can fluctuate ±1-2% — a vehicle at 79% SoC may briefly report 80% (target) and trigger premature done status.

**How to avoid:** Keep the existing `need_kwh < 0.5` threshold in `update_soc()` (not SoC ≥ target). This requires 0.5 kWh or less remaining — roughly 1% SoC on a 50 kWh battery — providing hysteresis against SoC jitter.

**Warning signs:** Wallbox switches to `"off"` prematurely; vehicle SoC drops slightly after reaching target and starts charging again at a higher-priced slot.

### Pitfall 3: Price Field Name Mismatch in Bootstrap

**What goes wrong:** `influx.get_history_hours()` returns dicts with key `"price_ct"` (in ct/kWh), but `bootstrap_from_influxdb()` accesses `point.get("price")` (in EUR/kWh) and falls back to `0.30`. Every history record uses the 0.30 fallback, making bootstrap useless.

**Why it happens:** Looking at `influxdb_client.py` line 111-134: the query selects `mean(price_ct)` but the returned dict uses key `"price_ct"` (set at line 132 as `"price_ct": row[1]`). The bootstrap function uses `point.get("price")` — a different key. So every record's price is 0.30 (the fallback).

**How to avoid:** In the fixed bootstrap, use `point.get("price_ct", 30) / 100` to convert ct/kWh → EUR/kWh. The existing bug means all bootstrapped experiences used `price=0.30` — technically not catastrophic (the Q-table just learns from 0.30 as a constant price), but wrong. The fix also corrects historical learning quality.

**Warning signs:** Bootstrap logs "N experiences loaded" but RL agent behavior is price-blind (always uses fallback action).

### Pitfall 4: _prev_connected Dict Not Thread-Safe

**What goes wrong:** `_prev_connected` is written in `update_from_evcc()` (called from `DataCollector._collect_once()` thread) and potentially read from `_poll_loop()` thread.

**Why it happens:** `_prev_connected` is a plain dict without a lock.

**How to avoid:** `_prev_connected` is only written in `update_from_evcc()` and only read in `update_from_evcc()` — it is never accessed from `_poll_loop()`. The `_poll_loop()` only reads `_manager.get_pollable_names()` and `_refresh_requested`. So `_prev_connected` is single-threaded by design. No additional lock needed.

**Warning signs:** None — this is a non-issue if the dict is only accessed from `update_from_evcc()`.

### Pitfall 5: Bootstrap Called When InfluxDB Is Not Configured

**What goes wrong:** `bootstrap_from_influxdb(influx, hours=168)` is called even if `influx._enabled` is `False`. The `get_history_hours()` method correctly returns `[]` when `not self._enabled`, so this is safe — bootstrap returns 0 silently.

**Why it happens:** `main.py` line 131-135 calls bootstrap whenever `rl_agent.load()` returns `False`. On fresh install with no InfluxDB, `influx._enabled=False`, so `get_history_hours()` returns `[]`, bootstrap returns 0, no log emitted.

**How to avoid:** Add a guard log: if `not influx._enabled`, log "RL bootstrap: InfluxDB not configured — skipping". This makes the startup log clearer.

**Warning signs:** No "bootstrap" log appears at startup even though it should — user assumes something is wrong.

---

## Code Examples

Verified patterns from existing codebase analysis:

### RELI-01: Minimal Connection-Event Detection

```python
# vehicle_monitor.py — VehicleMonitor.__init__() — add this line:
self._prev_connected: Dict[str, bool] = {}

# vehicle_monitor.py — update_from_evcc() — replace existing method:
def update_from_evcc(self, evcc_state: dict):
    """Pass evcc state to vehicle manager and detect connection events."""
    try:
        self._manager.update_from_evcc(evcc_state)
        # Re-apply manual SoC overrides
        for name, v in self._manager.get_all_vehicles().items():
            manual = self.manual_store.get(name)
            v.manual_soc = manual

        # Detect vehicle connection events → trigger immediate API refresh
        pollable = set(self._manager.get_pollable_names())
        for name, v in self._manager.get_all_vehicles().items():
            was_connected = self._prev_connected.get(name, False)
            if v.connected_to_wallbox and not was_connected and name in pollable:
                log("info", f"VehicleMonitor: {name} connected — triggering immediate SoC refresh")
                self.trigger_refresh(name)
            self._prev_connected[name] = v.connected_to_wallbox

    except Exception as e:
        log("error", f"VehicleMonitor update_from_evcc error: {e}")
```

### RELI-02: Sequencer SoC Sync Before plan()

```python
# main.py — inside while True: loop, before the "if sequencer is not None:" block
# that calls sequencer.plan() — insert this SoC sync:

if sequencer is not None:
    # Sync current SoC into all active sequencer requests every cycle
    for vname, vdata in all_vehicles.items():
        if vname in sequencer.requests:
            sequencer.update_soc(vname, vdata.get_effective_soc())

    connected_vehicle = next(
        (n for n, v in all_vehicles.items() if v.connected_to_wallbox), None
    )
    sequencer.plan(tariffs, solar_forecast, connected_vehicle, now)
    sequencer.apply_to_evcc(now)
    # ... rest of sequencer block unchanged
```

### RELI-05: Bootstrap with Progress and Cap

```python
# rl_agent.py — add config field to Config:
# rl_bootstrap_max_records: int = 1000

# rl_agent.py — bootstrap_from_influxdb() signature change:
def bootstrap_from_influxdb(self, influx, hours: int = 168,
                             max_records: int = 1000) -> int:
    # ... (full implementation in Pattern 3 above)

# main.py — update bootstrap call to pass config value:
if not rl_agent.load():
    max_rec = getattr(cfg, "rl_bootstrap_max_records", 1000)
    bootstrapped = rl_agent.bootstrap_from_influxdb(influx, hours=168,
                                                     max_records=max_rec)
```

### Price Field Fix in Bootstrap (Pitfall 3)

```python
# Current bug in bootstrap_from_influxdb():
price = point.get("price") or 0.30   # BUG: key is "price_ct", not "price"

# Fixed version:
price_ct = point.get("price_ct") or point.get("price")
if price_ct is None:
    price = 0.30
elif price_ct > 1.0:          # it's in ct/kWh (e.g. 28.5), convert to EUR/kWh
    price = price_ct / 100
else:                          # already in EUR/kWh (legacy field)
    price = price_ct
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| API poll every 60 min (fixed timer) | Timer poll + immediate trigger on connect event | v6 Phase 2 | SoC current within 30s of vehicle connection |
| Sequencer state updated only at add_request() time | Sequencer SoC sync every decision cycle (15 min) | v6 Phase 2 | Handoff within one 15-min cycle instead of waiting hours |
| Bootstrap: silent, no progress, no cap | Bootstrap: capped at 1000 records, progress log every 100 | v6 Phase 2 | Startup never appears frozen; memory bounded regardless of history size |
| Bootstrap reads `price` key (always falls back to 0.30) | Bootstrap reads `price_ct` key and converts | v6 Phase 2 | Historical learning uses actual price data |

**Deprecated/outdated:**
- The `hours=168` default in `bootstrap_from_influxdb()` signature is preserved. The `max_records` cap is the memory guard, not the `hours` parameter — this distinction matters if operators increase history window without increasing the cap.

---

## Open Questions

1. **Does evcc's `vehicleSoc` update in real-time during charging?**
   - What we know: evcc's `/api/state` loadpoint data includes `vehicleSoc`. This is updated by evcc from its own vehicle polling — evcc polls the vehicle directly via its own vehicle template (e.g. Kia, Renault). SmartLoad's separate API poll (via Kia/Renault provider) is a duplicate channel.
   - What's unclear: Whether evcc's `vehicleSoc` is continuously updated during active charging (real-time from CAN/OBD) or only from evcc's own polling interval (default 5-15 min in evcc). If evcc updates `vehicleSoc` live from the wallbox, the `trigger_refresh()` for API providers is less critical (evcc already has the correct value).
   - Recommendation: Implement `trigger_refresh()` regardless — it's a defensive fix that handles cases where evcc's own vehicle polling is slower than SmartLoad's needs. The extra API call is low-cost (one HTTP request per connection event).

2. **What happens when ChargeSequencer receives update_soc() for a vehicle not in requests?**
   - What we know: `update_soc()` begins with `if vehicle in self.requests:` — safe no-op.
   - What's unclear: Nothing — this is safe by design.
   - Recommendation: No action needed.

3. **Should `rl_bootstrap_max_records` be added to options.json / Config, or hardcoded?**
   - What we know: `Config` already has `rl_memory_size=10000` as a configurable field.
   - What's unclear: Whether users will ever need to tune the bootstrap cap. Power users with months of history might want to bootstrap from more records.
   - Recommendation: Add `rl_bootstrap_max_records: int = 1000` to `Config` dataclass (alongside other RL params) and pass it from `main.py`. Defaults to 1000 which is safe on all Pi hardware. Users can increase via options.json.

---

## Sources

### Primary (HIGH confidence)
- Codebase analysis: `vehicle_monitor.py` lines 112-121 — `update_from_evcc()` has no connection-event detection, no trigger_refresh() call
- Codebase analysis: `main.py` lines 246-258 — sequencer block never calls `sequencer.update_soc()`
- Codebase analysis: `rl_agent.py` lines 314-363 — `bootstrap_from_influxdb()` loads all rows silently, uses wrong dict key `"price"` instead of `"price_ct"`
- Codebase analysis: `influxdb_client.py` lines 111-135 — `get_history_hours()` returns dicts with key `"price_ct"` (ct/kWh), not `"price"` (EUR/kWh)
- Codebase analysis: `charge_sequencer.py` lines 112-120 — `update_soc()` marks status done when `need_kwh < 0.5`
- Codebase analysis: `vehicle_monitor.py` lines 138-146 — `trigger_refresh()` guards with `_lock`, adds to `_refresh_requested` set
- Codebase analysis: `vehicle_monitor.py` lines 70-110 — `_poll_loop()` checks `_refresh_requested` every 30 seconds

### Secondary (MEDIUM confidence)
- Raspberry Pi RAM baseline: Pi 4 = 4 GB, Pi 3B+ = 1 GB — 10000 entries × ~500 bytes each ≈ 5 MB is safely within budget on any Pi model
- InfluxDB GROUP BY time(1h): 168 rows maximum for hours=168 — memory is not a current issue; risk is only if hours is increased to months (8760h = 8760 rows ≈ 1.3 MB still manageable)

---

## Metadata

**Confidence breakdown:**
- RELI-01 root cause: HIGH — directly traceable in `update_from_evcc()` source; `trigger_refresh()` mechanism exists and is correct
- RELI-01 fix approach: HIGH — connection-event detection is a standard pattern; `_poll_loop` 30s cycle is the correct integration point
- RELI-02 root cause: HIGH — `sequencer.update_soc()` is definitively never called from `main.py`; code path verified
- RELI-02 fix approach: HIGH — adding the call before `sequencer.plan()` is the correct integration point; `update_soc()` is safe for vehicles not in requests
- RELI-05 memory risk: MEDIUM — current `hours=168` yields ≤168 rows which is trivial; risk is real only if hours grows; cap is a defensive measure
- RELI-05 progress logging: HIGH — absence of logging in bootstrap confirmed; `log()` call in loop is the correct fix
- Price key bug (Pitfall 3): HIGH — confirmed by cross-referencing `influxdb_client.py` return format vs `bootstrap_from_influxdb()` access pattern

**Research date:** 2026-02-22
**Valid until:** 2026-05-22 (stable codebase patterns; no external dependencies changing)
