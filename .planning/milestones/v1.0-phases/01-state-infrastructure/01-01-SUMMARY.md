---
phase: 01-state-infrastructure
plan: 01
subsystem: state-infrastructure
tags: [threading, sse, state-store, race-conditions, live-updates]
dependency_graph:
  requires: []
  provides: [StateStore, SSE-endpoint, ThreadedHTTPServer]
  affects: [main.py, web/server.py, web/static/app.js, web/templates/dashboard.html]
tech_stack:
  added: []
  patterns: [RLock-guarded-store, queue-fan-out-SSE, ThreadingMixIn]
key_files:
  created:
    - evcc-smartload/rootfs/app/state_store.py
  modified:
    - evcc-smartload/rootfs/app/main.py
    - evcc-smartload/rootfs/app/web/server.py
    - evcc-smartload/rootfs/app/web/templates/dashboard.html
    - evcc-smartload/rootfs/app/web/static/app.js
key_decisions:
  - "RLock (not Lock) guards StateStore to prevent deadlock if nested calls occur"
  - "SSE broadcast happens outside the RLock — no I/O while holding the state lock"
  - "Separate _sse_lock for client list avoids Pitfall 3 (mutation during iteration)"
  - "ThreadedHTTPServer with daemon_threads=True allows concurrent SSE + API requests"
  - "Existing 60s polling preserved as fallback for non-SSE browsers and complex sections"
metrics:
  duration_minutes: 8
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 4
  completed_date: "2026-02-22"
requirements:
  - RELI-03
---

# Phase 1 Plan 1: State Infrastructure — StateStore and SSE

One-liner: RLock-guarded StateStore replaces four unguarded WebServer instance variables; SSE endpoint pushes live state to dashboard via queue.Queue fan-out without polling.

## What Was Built

### Task 1: StateStore (state_store.py)

New file `evcc-smartload/rootfs/app/state_store.py` (188 lines) implementing:

- `StateStore` class with `threading.RLock` guarding `_state`, `_lp_action`, `_rl_action`, `_solar_forecast`, `_last_update`
- `update()`: acquires lock, updates all fields + timestamp, takes snapshot while locked, releases lock, then broadcasts to SSE clients (I/O happens outside the lock)
- `snapshot()`: acquires lock, returns shallow-copy dict (copy.copy() for SystemState/Action, list() for solar_forecast)
- `register_sse_client()`: creates `queue.Queue(maxsize=10)`, appends under separate `_sse_lock`
- `unregister_sse_client()`: removes under `_sse_lock`, silently ignores double-remove
- `_broadcast()`: iterates a copy of the client list (avoids mutation-during-iteration), calls `put_nowait()`, silently drops on `queue.Full`
- `_snapshot_to_json_dict()`: serialises snapshot to JSON-safe dict for SSE payload

### Task 2: Migration and SSE endpoint

**main.py changes:**
- Import `StateStore` from `state_store`
- Create `store = StateStore()` after `load_config()`
- Pass `store` as second positional argument to `WebServer`
- Replace `web.update_state(...)` with `store.update(state=state, lp_action=lp_action, rl_action=rl_action, solar_forecast=solar_forecast)` in decision loop

**web/server.py changes:**
- Added `ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer)` with `daemon_threads = True`
- `WebServer.__init__()` now accepts `store: StateStore` as second positional argument
- Removed `self._last_state`, `self._last_lp_action`, `self._last_rl_action`, `self._last_solar_forecast`, and `update_state()` method entirely
- All API handlers (`_api_status`, `_api_config`, `_api_summary`, `_api_strategy`, `_api_chart_data`, `_api_slots`) now call `snap = self._store.snapshot()` once at the top and reference `snap["state"]`, `snap["lp_action"]` etc. throughout
- Added `/events` SSE endpoint: sets SSE headers, registers client queue, loops on `client_q.get(timeout=30)`, writes keepalive comment on timeout, unregisters on connection close
- `_run()` attaches `store` reference to server as `server._store` for handler access

**dashboard.html changes:**
- Header: added `<span class="sse-dot" id="sseDot">` + `<span id="sseStatus">` connection indicator
- Status cards: added `<span class="update-age" id="priceAge">` etc. per card
- CSS: `.sse-dot` (connection indicator), `.sse-updated` (`@keyframes sse-flash`), `.update-age` label styles

**app.js changes:**
- Module-level `_sseSource` and `_sseLastUpdate` tracking variables
- `flashUpdate(el)`: removes and re-adds `.sse-updated` CSS class to trigger animation
- `updateAgeLabels()`: formats `Date.now() - _sseLastUpdate` as "vor X Min" and sets all age labels
- `applySSEUpdate(msg)`: updates priceVal/batteryVal/pvVal/homeVal from SSE payload, calls flashUpdate() on changed values
- `setSseIndicator(state)`: sets dot colour and label text
- `startSSE()`: creates `EventSource('/events')`, wires `onopen`/`onmessage`/`onerror`
- Startup: calls `startSSE()` if `EventSource` is available; `setInterval(updateAgeLabels, 60000)`; existing `setInterval(refresh, 60000)` preserved

## Verification Results

| Check | Result |
|-------|--------|
| `state_store.py` has `StateStore` class | PASS |
| `update()`, `snapshot()`, `register_sse_client()`, `unregister_sse_client()` methods | PASS |
| `web/server.py` no `_last_state` etc. | PASS (0 matches) |
| `web/server.py` has `snapshot()` in handlers | PASS (10 instances) |
| `web/server.py` has `/events` endpoint | PASS |
| `web/server.py` uses `ThreadingMixIn` | PASS |
| `main.py` creates `StateStore()` | PASS |
| `main.py` calls `store.update()` | PASS |
| `app.js` has `EventSource('/events')` | PASS |
| `app.js` has `flashUpdate()` + `updateAgeLabels()` | PASS |
| `state_store.py` min 50 lines | PASS (188 lines) |

## Deviations from Plan

None — plan executed exactly as written. All anti-patterns from the research document were followed:

- Broadcast released outside RLock (anti-pattern: "Never hold StateStore._lock during I/O")
- Separate `_sse_lock` for client list (Pitfall 3: mutation during iteration)
- All API handlers call `snapshot()` once at top (anti-pattern: "Unguarded multi-attribute reads")
- `RLock` used instead of `Lock` (Pitfall 2: re-entrant safety)

## Self-Check: PASSED

All files exist and all commits verified:

| Item | Status |
|------|--------|
| evcc-smartload/rootfs/app/state_store.py | FOUND |
| evcc-smartload/rootfs/app/main.py | FOUND |
| evcc-smartload/rootfs/app/web/server.py | FOUND |
| evcc-smartload/rootfs/app/web/templates/dashboard.html | FOUND |
| evcc-smartload/rootfs/app/web/static/app.js | FOUND |
| Commit 8065687 (Task 1) | FOUND |
| Commit 12af619 (Task 2) | FOUND |
