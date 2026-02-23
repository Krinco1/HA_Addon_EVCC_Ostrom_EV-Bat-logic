---
phase: 05-dynamic-buffer
plan: 01
subsystem: battery-management
tags: [dynamic-buffer, pv-confidence, observation-mode, sse, state-store, persistence]

# Dependency graph
requires:
  - phase: 03-pv-forecasting
    provides: PVForecaster.confidence (0.0-1.0), pv_96 forecast slots, pv_forecaster.correction_label
  - phase: 04-lp-horizon-planner
    provides: SystemState.price_spread (P80-P20), StateStore SSE infrastructure
provides:
  - DynamicBufferCalc engine with conservative formula (20% practical min, 10% hard floor)
  - Observation mode with 14-day auto-transition and manual override API
  - Atomic JSON persistence at /data/smartload_buffer_model.json
  - buffer_result in SSE payload as data.buffer for dashboard consumption
affects: [06-dashboard-buffer, 07-web-api-endpoints, Phase 8 RL constraint audit]

# Tech tracking
tech-stack:
  added: []  # stdlib only: json, os, threading, collections.deque, datetime
  patterns:
    - "DynamicBufferCalc owns one domain with _load()/_save() persistence and single public step() method"
    - "File I/O released outside lock (serialize under lock, write after lock release)"
    - "Atomic rename: .tmp -> final prevents JSON corruption on restart"
    - "Graceful fallback: buffer_calc = None if import fails, main loop continues"
    - "Hysteresis: round target to nearest 5% to prevent oscillation"

key-files:
  created:
    - evcc-smartload/rootfs/app/dynamic_buffer.py
  modified:
    - evcc-smartload/rootfs/app/main.py
    - evcc-smartload/rootfs/app/state_store.py

key-decisions:
  - "Conservative formula: practical minimum 20% even at highest confidence, hard floor 10%"
  - "Confidence threshold 0.65 above which buffer reduction begins (linear scale above threshold)"
  - "5% rounding hysteresis applied to target to dampen oscillation between cycles"
  - "bat-to-EV takes precedence: buffer_calc.step() skipped when controller._bat_to_ev_active is True"
  - "File I/O happens outside the lock to avoid blocking SSE reads in web thread"
  - "Log entries restored from JSON as plain dicts (not full BufferEvent objects) to simplify restore path"

patterns-established:
  - "DynamicBufferCalc pattern: standalone module, _load()/_save(), step() called each cycle — mirrors PVForecaster"
  - "Observation-mode pattern: _deployment_ts persisted on first call, elapsed vs OBSERVATION_PERIOD_SECONDS determines mode"
  - "SSE extension pattern: add field to __init__, update() signature, _snapshot_unlocked(), _snapshot_to_json_dict()"

requirements-completed: [PLAN-03]

# Metrics
duration: 12min
completed: 2026-02-23
---

# Phase 5 Plan 01: Dynamic Buffer Engine Summary

**DynamicBufferCalc engine with conservative PV-confidence formula, 14-day observation mode with JSON persistence, and SSE broadcast of buffer state via data.buffer**

## Performance

- **Duration:** 12 min
- **Started:** 2026-02-23T10:05:00Z
- **Completed:** 2026-02-23T10:17:12Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `dynamic_buffer.py` (418 lines): DynamicBufferCalc engine with conservative formula (20% practical min, 10% hard floor), observation mode with 14-day auto-transition, atomic JSON persistence surviving restarts, hysteresis (5% rounding), German-language reason strings, and manual override API (`activate_live()`, `extend_observation()`)
- Wired DynamicBufferCalc into `main.py`: initialized after HorizonPlanner with graceful fallback, called every 15-min cycle after bat-to-EV block (skipped when `controller._bat_to_ev_active`), wrapped in try/except so buffer failure never crashes the main loop
- Extended `state_store.py`: `buffer_result` field in `__init__`, added to `update()` signature, stored in `_snapshot_unlocked()`, and exposed as `"buffer"` key in SSE JSON payload

## Task Commits

1. **Task 1: Create DynamicBufferCalc module** - `c40cc68` (feat)
2. **Task 2: Wire into main loop and extend StateStore** - `f45a3ae` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `evcc-smartload/rootfs/app/dynamic_buffer.py` - DynamicBufferCalc engine: formula, BufferEvent log, observation mode, persistence, manual override API
- `evcc-smartload/rootfs/app/main.py` - Phase 5 initialization block + buffer_calc.step() in decision loop + buffer_result wired to store.update()
- `evcc-smartload/rootfs/app/state_store.py` - buffer_result field, update() parameter, snapshot field, SSE "buffer" key

## Decisions Made

- Conservative formula chosen per user decision: buffer can only be lowered to 20% practical minimum, never below 10% hard floor
- Confidence threshold 0.65 (Claude's discretion): above 50%, conservative — starts reducing buffer only when PV forecast is quite reliable
- Hysteresis via 5% rounding (Pitfall 4 from research): prevents buffer oscillation when confidence hovers near threshold
- bat-to-EV coordination: DynamicBufferCalc skips its `set_buffer_soc()` call when `controller._bat_to_ev_active` is True, preventing value fighting between the two code paths
- I/O outside lock: `_save()` serializes under lock, writes file after releasing — prevents blocking SSE reads in web thread (Pitfall 2 from research)
- Log restore: `_load()` reconstructs log entries as plain dicts (not BufferEvent objects) — simpler restore path, sufficient for chart/table rendering

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Verification script using `from state_store import StateStore` failed locally due to missing `numpy` (needed by `state.py` — numpy is installed in the Docker add-on but not in the dev Python env). Resolved by verifying via AST parsing of the source files instead, which confirmed all required patterns.

## User Setup Required

None - no external service configuration required. DynamicBufferCalc initializes automatically on add-on startup and enters observation mode for the first 14 days.

## Next Phase Readiness

- `data.buffer` is now available in the SSE payload — dashboard can render buffer status, observation mode banner, and event log chart
- Web API endpoints for `activate_live()` and `extend_observation()` are the natural next step (Phase 5, Plan 2 or separate web plan)
- Buffer formula coefficients are design estimates — the 14-day observation period exists precisely to calibrate them before live mode applies changes

---
*Phase: 05-dynamic-buffer*
*Completed: 2026-02-23*
