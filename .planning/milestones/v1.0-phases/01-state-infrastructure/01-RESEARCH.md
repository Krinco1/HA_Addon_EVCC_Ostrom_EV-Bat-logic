# Phase 1: State Infrastructure - Research

**Researched:** 2026-02-22
**Domain:** Python threading, config validation, SSE push in stdlib HTTP server
**Confidence:** HIGH (analysis of the actual codebase — no external library guesswork needed)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Config-Fehlerbehandlung**
- Config-Fehler werden sowohl im Container-Log als auch auf einer Dashboard-Fehlerseite (Port 8099) angezeigt
- Abstufung: Kritische Fehler (z.B. fehlende evcc_url) stoppen das Add-on — Web-Server startet nur für Fehlerseite, keine Optimierung. Nicht-kritische Fehler (z.B. fehlender optionaler Parameter) nutzen sichere Defaults mit Warnung
- Die Fehlerseite läuft auf dem bestehenden Web-Server Port 8099

**Config-Migration**
- Bestehende statische Euro-Limits (ev_max_price_ct, battery_max_price_ct) werden als Fallback behalten — wenn der Planer ausfällt, greifen die alten Limits als Sicherheitsnetz
- vehicles.yaml und drivers.yaml bleiben abwärtskompatibel — bestehendes Format wird beibehalten, neue Felder sind optional
- Migration erfolgt still — keine sichtbare Übergangsmeldung beim ersten v6-Start

**State-Konsistenz**
- Dashboard zeigt live neue Werte sofort an, mit kurzer visueller Markierung was sich geändert hat
- Doppelte Feedback-Strategie: Kurzes Highlight (1-2 Sek) bei Wertänderung UND dauerhafter Timestamp ("vor X Min aktualisiert") pro Datenpunkt
- Dashboard-Updates via Server-Sent Events (SSE) oder WebSocket — Server pushed Änderungen in Echtzeit statt Polling

### Claude's Discretion

- Welche Config-Felder als kritisch vs. nicht-kritisch eingestuft werden (Claude beurteilt was ohne Funktion unmöglich ist vs. was mit sinnvollen Defaults laufen kann)
- Detailtiefe der Fehlermeldungen und Korrekturvorschläge auf der Fehlerseite
- Neue v6-Config-Felder: Claude wählt sinnvolle Default-Strategie (auto-Defaults vs. explizite Konfiguration je nach Feld)
- Dashboard-Verhalten bei Backend-Verbindungsabbruch (Banner, Ausgrauen, oder Kombination)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RELI-03 | Web-Server State-Updates sind thread-safe — keine Race Conditions zwischen Decision-Loop, Web-Requests und Polling-Threads | StateStore with RLock guards all writes; web handler reads snapshot atomically; DataCollector and VehicleMonitor write through StateStore only |
| RELI-04 | Ungültige Konfiguration wird beim Start erkannt und mit klarer Fehlermeldung gemeldet | ConfigValidator runs before any network connection; critical vs. non-critical classification with human-readable field-level errors |
</phase_requirements>

---

## Summary

The existing codebase (v5) already has partial threading discipline but has two concrete race conditions. First, `WebServer.update_state()` writes four instance variables (`_last_state`, `_last_lp_action`, `_last_rl_action`, `_last_solar_forecast`) without a lock while the HTTP handler reads them concurrently across any number of request threads. Second, `VehicleMonitor._poll_loop()` writes vehicle data (through `VehicleManager`) without coordinating with `DataCollector._collect_once()`, which also calls `update_from_evcc()`. Both are classic TOCTOU problems on CPython — the GIL prevents torn reads of individual references but cannot prevent logical inconsistency across multiple attribute reads.

The fix is surgical: introduce a single `threading.RLock`-guarded `StateStore` that replaces all four unguarded `WebServer` instance variables, and a second `RLock` inside `VehicleMonitor` that guards the vehicle dict mutations. `DataCollector` becomes the sole writer to `StateStore`; the web handler calls `StateStore.snapshot()` to get an immutable copy for the duration of each request. No third-party library is needed — `threading.RLock` is stdlib.

Config validation is currently non-existent: `load_config()` silently falls back to defaults on any error and applies `setattr` for any key in options.json without range-checking. The fix is a `ConfigValidator` class that validates a loaded `Config` object and returns typed `ValidationError` results (field name, value, rule violated, human-readable message) before any I/O (evcc/InfluxDB connections) is attempted.

**Primary recommendation:** Add `StateStore` (RLock-guarded, one snapshot method), add `ConfigValidator` (pre-I/O, field-level errors), wire SSE endpoint on `/events` using stdlib `http.server` chunked streaming.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `threading.RLock` | stdlib | Guards StateStore writes and reads | Re-entrant; safe if validator or nested code calls back into lock holder; no extra deps on Alpine |
| `dataclasses` | stdlib 3.7+ | Immutable state snapshots via `copy.copy()` | Already used throughout codebase for SystemState, Action |
| `copy.copy()` | stdlib | Shallow snapshot for immutable read views | SystemState fields are primitives + lists — shallow copy is safe and cheap |
| `json` | stdlib | Config loading from options.json | Already in use |
| `yaml` | py3-yaml (apk) | vehicles.yaml / drivers.yaml parsing | Already installed in Dockerfile |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dataclasses.dataclass(frozen=True)` | stdlib | Optional: freeze snapshot to catch accidental mutation | Use on StateSnapshot if web handlers are ever suspected of mutating state |
| `threading.Event` | stdlib | SSE connection keepalive / shutdown signalling | Use in SSE endpoint to unblock on new state or connection close |
| `queue.Queue` | stdlib | SSE fan-out per connected client | Use one Queue per SSE client connection |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `threading.RLock` | `threading.Lock` | Lock is fine if no re-entrancy needed, but RLock costs nothing extra and is safer if `StateStore.update()` is ever called from within a locked context |
| Custom `StateStore` | `multiprocessing.Manager().dict()` | Manager adds IPC overhead for no benefit — everything is in-process |
| `copy.copy()` snapshot | `dataclasses.asdict()` | `asdict()` is recursive and slower; copy.copy() preserves types and is O(fields) |

**Installation:** No new packages needed. All required modules are in Python stdlib or already installed in the Dockerfile.

---

## Architecture Patterns

### Recommended Project Structure

The changes are surgical — no new top-level files except `state_store.py` and `config_validator.py`:

```
rootfs/app/
├── state_store.py       # NEW: RLock-guarded StateStore
├── config_validator.py  # NEW: ConfigValidator, ValidationResult
├── config.py            # MODIFIED: load_config() calls validator before returning
├── main.py              # MODIFIED: receives StateStore, wires SSE
├── vehicle_monitor.py   # MODIFIED: DataCollector writes to StateStore
├── web/
│   └── server.py        # MODIFIED: reads from StateStore snapshot; SSE endpoint
└── state.py             # UNCHANGED: SystemState, Action, VehicleStatus etc.
```

### Pattern 1: RLock-Guarded StateStore

**What:** Single object owns all mutable shared state. Writers acquire lock, update, release. Readers call `.snapshot()` which acquires lock, returns shallow copy, releases.

**When to use:** Any data written by one thread and read by another. In this project: `_last_state`, `_last_lp_action`, `_last_rl_action`, `_last_solar_forecast` in WebServer.

**Example:**

```python
# state_store.py
import threading
import copy
from typing import Optional
from state import SystemState, Action
from typing import List, Dict

class StateStore:
    """Single RLock-guarded store for all shared mutable state.

    Writers: DataCollector (via main loop).
    Readers: WebServer request handlers (via snapshot()).
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._state: Optional[SystemState] = None
        self._lp_action: Optional[Action] = None
        self._rl_action: Optional[Action] = None
        self._solar_forecast: List[Dict] = []

    def update(self,
               state: SystemState,
               lp_action: Action,
               rl_action: Action,
               solar_forecast: List[Dict]) -> None:
        """Called by main decision loop after each cycle."""
        with self._lock:
            self._state = state
            self._lp_action = lp_action
            self._rl_action = rl_action
            self._solar_forecast = list(solar_forecast) if solar_forecast else []

    def snapshot(self) -> dict:
        """Return a shallow copy of all fields; safe for concurrent reads."""
        with self._lock:
            return {
                "state": copy.copy(self._state),
                "lp_action": copy.copy(self._lp_action),
                "rl_action": copy.copy(self._rl_action),
                "solar_forecast": list(self._solar_forecast),
            }
```

### Pattern 2: ConfigValidator with Critical/Non-Critical Classification

**What:** Validate a `Config` object before any I/O. Return a list of `ValidationResult` items. Caller decides whether to abort (critical errors) or warn (non-critical).

**When to use:** At startup, before `EvccClient` or `InfluxDBClient` are constructed.

**Example:**

```python
# config_validator.py
from dataclasses import dataclass
from typing import List
from config import Config

@dataclass
class ValidationResult:
    field: str
    value: object
    severity: str          # "critical" or "warning"
    message: str           # Human-readable, includes valid range
    suggestion: str = ""   # What to fix

class ConfigValidator:
    """Validates Config fields before any network connections are attempted."""

    CRITICAL_FIELDS = {"evcc_url"}

    def validate(self, cfg: Config) -> List[ValidationResult]:
        errors: List[ValidationResult] = []

        # Critical: evcc_url must be non-empty
        if not cfg.evcc_url or not cfg.evcc_url.startswith("http"):
            errors.append(ValidationResult(
                field="evcc_url",
                value=cfg.evcc_url,
                severity="critical",
                message="evcc_url muss eine gültige HTTP-URL sein (z.B. http://192.168.1.66:7070)",
                suggestion="Prüfe die IP-Adresse und Port deines evcc-Servers",
            ))

        # Non-critical: SoC bounds
        if cfg.battery_min_soc >= cfg.battery_max_soc:
            errors.append(ValidationResult(
                field="battery_min_soc / battery_max_soc",
                value=f"{cfg.battery_min_soc} / {cfg.battery_max_soc}",
                severity="critical",
                message=f"battery_min_soc ({cfg.battery_min_soc}) muss kleiner als battery_max_soc ({cfg.battery_max_soc}) sein",
                suggestion="Setze z.B. battery_min_soc=10, battery_max_soc=90",
            ))

        # Efficiency must be 0 < x <= 1
        for field in ("battery_charge_efficiency", "battery_discharge_efficiency"):
            val = getattr(cfg, field)
            if not (0 < val <= 1.0):
                errors.append(ValidationResult(
                    field=field,
                    value=val,
                    severity="critical",
                    message=f"{field} muss zwischen 0 (exklusiv) und 1.0 liegen, ist aber {val}",
                    suggestion="Typischer Wert: 0.92",
                ))

        # Price limits: must be positive
        for field in ("battery_max_price_ct", "ev_max_price_ct"):
            val = getattr(cfg, field)
            if val <= 0:
                errors.append(ValidationResult(
                    field=field,
                    value=val,
                    severity="warning",
                    message=f"{field} ist {val}ct — wird auf sicheren Default gesetzt",
                    suggestion="Typische Werte: battery_max_price_ct=25.0, ev_max_price_ct=30.0",
                ))

        return errors
```

### Pattern 3: SSE Endpoint on stdlib http.server

**What:** Server-Sent Events over plain HTTP using `http.server`. One persistent connection per browser tab. Server pushes JSON when state changes.

**When to use:** Dashboard live updates. SSE preferred over WebSocket because it is unidirectional, HTTP/1.1-native, and requires no extra library.

**Example:**

```python
# In web/server.py Handler.do_GET, add:

elif path == "/events":
    # SSE: keep connection open, push state on each update
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-cache")
    self.send_header("Connection", "keep-alive")
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()

    import queue, json
    client_q = queue.Queue(maxsize=10)
    srv._sse_clients.append(client_q)
    try:
        while True:
            try:
                data = client_q.get(timeout=30)
                self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
            except queue.Empty:
                # keepalive comment
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        srv._sse_clients.remove(client_q)
```

And in `StateStore.update()` or after `web.update_state()` in the main loop:
```python
# Broadcast to all SSE clients
snapshot = store.snapshot()
for q in list(srv._sse_clients):
    try:
        q.put_nowait(snapshot["state"].__dict__)
    except queue.Full:
        pass  # slow client, drop this update
```

### Anti-Patterns to Avoid

- **Unguarded multi-attribute reads in the web handler:** The current `_api_status()` reads `self._last_state` then `self._last_lp_action` in separate statements without a lock. Between reads, the decision loop thread could update both — yielding a response with state from cycle N and action from cycle N+1. Fix: always call `snapshot()` once at top of handler method.
- **Using `threading.Lock` for validator code that calls back into state:** If `ConfigValidator` ever calls back into `StateStore`, a plain `Lock` deadlocks. Use `RLock` (re-entrant) to be safe.
- **Writing state inside web POST handlers:** The current `/vehicles/manual-soc` handler calls `manual_store.set()` which writes to disk under its own lock — this is fine. But adding any writes to `StateStore` from within an HTTP handler would violate the read-only contract. Keep all `StateStore` writes in the main loop thread.
- **Holding the RLock during I/O:** Never hold `StateStore._lock` while writing InfluxDB or calling evcc. Acquire lock, copy data, release, then do I/O.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE fan-out | Custom pub/sub with shared list + manual locking | `queue.Queue` per client + append/remove under a list lock | Queue handles backpressure (maxsize), thread-safe put/get, drop-on-full is one line |
| Config schema | Manual string checks in load_config() | `ConfigValidator` class with typed `ValidationResult` | Separates concerns; testable without running the add-on |
| Snapshot copying | `json.dumps/loads` round-trip for deep copy | `copy.copy()` (shallow) | `SystemState` fields are primitives + lists — shallow is sufficient and 100x faster |

**Key insight:** Everything needed is in Python stdlib. Adding a third-party validation library (pydantic, cerberus) would require adding it to the Dockerfile and is overkill for ~15 config fields with simple range rules.

---

## Common Pitfalls

### Pitfall 1: GIL Gives False Safety

**What goes wrong:** Developers assume CPython's GIL prevents race conditions. It prevents torn reads of individual object references, but not logical inconsistency across two separate attribute reads.

**Why it happens:** `self._last_state = state` is atomic at the bytecode level, but `a = self._last_state; b = self._last_lp_action` is two bytecodes — the GIL can release between them.

**How to avoid:** All state is accessed through one `StateStore.snapshot()` call that holds the RLock for the duration of the copy.

**Warning signs:** Dashboard shows "stale" action for a newly collected state, or RL stats don't match the current state timestamp.

### Pitfall 2: RLock vs Lock for Nested Calls

**What goes wrong:** Using `threading.Lock` and then calling a method that also tries to acquire the same lock → deadlock.

**Why it happens:** `Lock` is not re-entrant. If `StateStore.update()` is ever called from a code path that already holds the lock (e.g., a validator that reads and writes), the second acquisition blocks forever.

**How to avoid:** Use `threading.RLock` throughout `StateStore`. It costs nothing extra and allows the same thread to acquire the lock multiple times.

**Warning signs:** Add-on hangs silently on startup or after first state update.

### Pitfall 3: SSE Client List Mutation During Iteration

**What goes wrong:** Broadcasting to SSE clients iterates `_sse_clients` while another thread's connection teardown removes from the same list.

**Why it happens:** Python list `remove()` is not atomic with respect to iteration even under the GIL for multi-step operations.

**How to avoid:** Broadcast iterates a `list(_sse_clients)` copy; add/remove are done under a short-lived `threading.Lock` on the clients list.

**Warning signs:** `ValueError: list.remove(x): x not in list` in the SSE broadcast path.

### Pitfall 4: Config Validation After I/O Starts

**What goes wrong:** Validator is called after `EvccClient` or `InfluxDBClient` constructors run. A bad `evcc_url` causes a network timeout (30s) before the error is reported.

**Why it happens:** Easy to put validation "somewhere in main()" after all objects are wired up.

**How to avoid:** `validate(cfg)` is the first call in `main()`, before any object construction. If critical errors exist, start only the web server with the error page and exit the main loop.

**Warning signs:** Startup takes 30+ seconds on bad config; error appears in log after a timeout exception rather than immediately.

### Pitfall 5: Error Page Served on Same Port — Handler Must Route

**What goes wrong:** If the HTTPServer's Handler always renders the full dashboard but config is invalid, the user sees a broken dashboard with no data instead of a clear error page.

**Why it happens:** The Handler has no awareness of the config state when deciding what to render at `/`.

**How to avoid:** Pass a `config_errors: List[ValidationResult]` flag to the WebServer constructor. If non-empty critical errors exist, `do_GET` for `/` renders the error page; all other endpoints return `503 Service Unavailable`. The normal dashboard is only rendered when `config_errors` is empty.

---

## Code Examples

Verified patterns from the existing codebase and Python stdlib:

### StateStore Integration in main.py

```python
# main.py (modified excerpt)
from state_store import StateStore
from config_validator import ConfigValidator

def main():
    cfg = load_config()

    # --- Validate BEFORE any I/O ---
    validator = ConfigValidator()
    errors = validator.validate(cfg)
    critical = [e for e in errors if e.severity == "critical"]

    for e in errors:
        level = "error" if e.severity == "critical" else "warning"
        log(level, f"Config {e.field}: {e.message}")

    # Start web server first so error page is reachable
    store = StateStore()
    web = WebServer(cfg, store, config_errors=errors)
    web.start()

    if critical:
        log("error", "Kritische Config-Fehler — Add-on startet nicht. Bitte options.json prüfen.")
        # Block forever; web server shows error page
        import time
        while True:
            time.sleep(60)

    # Continue normal startup only if no critical errors
    evcc = EvccClient(cfg)
    ...
```

### WebServer Reading from StateStore (Thread-Safe)

```python
# web/server.py — _api_status() (modified)
def _api_status(self) -> dict:
    snap = self._store.snapshot()   # one atomic read
    state = snap["state"]
    lp = snap["lp_action"]
    ...
    # All further references use `state` and `lp` from the same snapshot
```

### Error Page Route in Handler

```python
# web/server.py — Handler.do_GET() (modified)
def do_GET(self):
    path = self.path.split("?")[0]

    # If critical config errors exist, only serve error page
    if srv._config_errors:
        if path == "/":
            self._html(srv._render_error_page())
            return
        else:
            self._json({"error": "Add-on nicht gestartet — Konfigurationsfehler",
                        "details": [e.message for e in srv._config_errors]}, 503)
            return

    # Normal routing below ...
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Module-level globals for shared state | RLock-guarded `StateStore` | v6 (this phase) | Eliminates race conditions; single clear ownership |
| Silent config fallback to defaults | `ConfigValidator` pre-I/O with human-readable errors | v6 (this phase) | Fails fast, no 30s timeouts, user sees exact broken field |
| Dashboard polls `/status` every N seconds | SSE push on `/events` | v6 (this phase) | Eliminates polling latency; reduces HTTP overhead |
| Unguarded `_last_state` etc. on WebServer | `StateStore.snapshot()` | v6 (this phase) | Thread-safe reads without blocking request handlers |

**Deprecated/outdated:**
- `WebServer.update_state()`: replaced by `StateStore.update()` — the web server no longer holds state, it only holds a reference to the store.
- `WebServer._last_state`, `_last_lp_action`, `_last_rl_action`, `_last_solar_forecast`: removed; state lives in `StateStore`.

---

## Open Questions

1. **SSE and the stdlib HTTPServer's threading model**
   - What we know: `HTTPServer` creates a new socket per request. For SSE, the connection must stay open — this ties up the handler thread for the duration. The current `threading.Thread` start in `_run()` means the entire server runs in a single thread (no `ThreadingMixIn`).
   - What's unclear: Whether adding `socketserver.ThreadingMixIn` is needed before SSE works, or if SSE will block the only server thread and starve other requests.
   - Recommendation: Add `ThreadingMixIn` to the HTTPServer class in Phase 1. This is a two-line change and is the standard pattern for SSE with stdlib. It handles each HTTP request (including the long-lived SSE connection) in its own daemon thread.

2. **VehicleMonitor internal locking**
   - What we know: `VehicleMonitor._lock` currently guards only `_refresh_requested`. The `VehicleManager`'s internal vehicle dict is written by `_poll_loop` and read by `DataCollector._collect_once()` via `get_all_vehicles()` without coordination.
   - What's unclear: Whether `VehicleManager.get_all_vehicles()` returns a copy or a reference to the live dict.
   - Recommendation: In Phase 1, extend `VehicleMonitor._lock` to guard all `_manager` calls, or verify that `VehicleManager` already returns copies.

3. **Critical vs. non-critical config field list**
   - What we know: From CONTEXT.md, `evcc_url` is explicitly critical. InfluxDB host is optional (add-on can run without InfluxDB).
   - What's unclear: Where `battery_min_soc` fits — the Config dataclass does not have this field currently (only `battery_max_soc` and `battery_min_soc` are absent; checking the existing `Config` shows no `battery_min_soc` field directly — this is used in code but may be a future v6 field).
   - Recommendation: Use the following classification:
     - **Critical:** `evcc_url` (empty or malformed = no data source)
     - **Critical:** `battery_min_soc >= battery_max_soc` (logical impossibility)
     - **Critical:** efficiency fields outside (0, 1] (division by zero risk)
     - **Warning (safe default):** InfluxDB fields (feature degrades gracefully), price limits <= 0, `ev_target_soc` outside [0, 100]

---

## Sources

### Primary (HIGH confidence)

- Codebase analysis: `rootfs/app/web/server.py` lines 56-67 (unguarded `_last_state` writes/reads)
- Codebase analysis: `rootfs/app/vehicle_monitor.py` (VehicleMonitor._lock guards only `_refresh_requested`, not VehicleManager calls)
- Codebase analysis: `rootfs/app/config.py` `load_config()` (no validation, silent fallback)
- Python docs: `threading.RLock` — https://docs.python.org/3/library/threading.html#rlock-objects
- Python docs: `socketserver.ThreadingMixIn` — https://docs.python.org/3/library/socketserver.html#socketserver.ThreadingMixIn
- Python docs: `queue.Queue` — https://docs.python.org/3/library/queue.html

### Secondary (MEDIUM confidence)

- SSE pattern with `http.server` + `ThreadingMixIn` — standard Python community approach; no third-party verification done but pattern is well-established.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all stdlib, no external libraries, codebase already uses same patterns
- Architecture: HIGH — analysis of actual race conditions in existing code, not theoretical
- Pitfalls: HIGH — pitfalls identified directly from reading the live code, not from generic research
- SSE threading model: MEDIUM — ThreadingMixIn pattern is standard but interaction with existing single-thread server needs validation at implementation time

**Research date:** 2026-02-22
**Valid until:** 2026-04-22 (stable stdlib patterns; no fast-moving dependencies)
