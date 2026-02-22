---
phase: 02-vehicle-reliability
plan: 01
subsystem: vehicle-monitoring
tags: [vehicle-monitor, charge-sequencer, soc-refresh, connection-event, threading]

# Dependency graph
requires:
  - phase: 01-state-infrastructure
    provides: StateStore, DataCollector, VehicleMonitor threading model established
provides:
  - Connection-event detection in VehicleMonitor with _prev_connected dict and trigger_refresh on connect
  - Sequencer SoC sync every decision cycle before plan() via sequencer.update_soc()
affects: [03-energy-optimization, 04-holistic-planner, 05-dynamic-buffer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Connection-event detection: diff prev/current state across synchronous update calls to detect transitions, queue async I/O via existing thread-safe mechanism"
    - "Decision-loop SoC sync: call update_soc() for all sequencer-tracked vehicles before plan() each cycle to keep internal state current"

key-files:
  created: []
  modified:
    - evcc-smartload/rootfs/app/vehicle_monitor.py
    - evcc-smartload/rootfs/app/main.py

key-decisions:
  - "_prev_connected is not guarded by a lock because it is only accessed from update_from_evcc() (single-threaded by design — called from DataCollector._collect_once()); no additional synchronization needed"
  - "trigger_refresh() adds to _refresh_requested set (guarded by _lock); actual I/O poll happens in _poll_loop() within 30s — no I/O in the synchronous data collection path"
  - "update_soc() called for all vehicles in sequencer.requests regardless of connection status; update_soc() is a no-op for vehicles not in requests (guarded by 'if vehicle in self.requests')"
  - "Sequencer SoC sync loop placed inside existing 'if sequencer is not None:' block before plan() so it only runs when sequencer is enabled"

patterns-established:
  - "Connection-event detection pattern: track prev state in dict initialized in __init__, diff in update call, queue async action via thread-safe set"
  - "Decision-loop sync pattern: sync internal state of long-lived objects (sequencer) from authoritative data source (vehicle_monitor) at top of each cycle before making decisions"

requirements-completed: [RELI-01, RELI-02]

# Metrics
duration: 2min
completed: 2026-02-22
---

# Phase 2 Plan 01: Vehicle Reliability - SoC Staleness and Sequencer Handoff Summary

**Connection-event-triggered SoC refresh for wallbox-connected vehicles and per-cycle sequencer SoC sync for immediate completion detection**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-22T17:02:40Z
- **Completed:** 2026-02-22T17:04:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- VehicleMonitor now detects False->True transitions in `connected_to_wallbox` and calls `trigger_refresh()` for pollable vehicles (Kia/Renault API providers) within 30 seconds of connection, eliminating up to 60-minute SoC staleness on the dashboard
- ChargeSequencer receives updated SoC every decision cycle via `sequencer.update_soc()` called before `sequencer.plan()`, enabling completion detection within one cycle and handoff to the next waiting vehicle within 15 minutes instead of potentially hours
- Both changes are surgical modifications to existing methods with no new files, no new dependencies, and no new threads

## Task Commits

Each task was committed atomically:

1. **Task 1: Add connection-event detection to VehicleMonitor.update_from_evcc()** - `ddc290d` (feat)
2. **Task 2: Add sequencer SoC sync to main decision loop** - `477121e` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `evcc-smartload/rootfs/app/vehicle_monitor.py` - Added `_prev_connected: Dict[str, bool] = {}` to `__init__`, added connection-event detection block at end of `update_from_evcc()` that calls `trigger_refresh()` for pollable vehicles on connect
- `evcc-smartload/rootfs/app/main.py` - Added `sequencer.update_soc()` loop inside `if sequencer is not None:` block, before the existing `sequencer.plan()` call

## Decisions Made

- `_prev_connected` dict is not lock-guarded because `update_from_evcc()` is called exclusively from `DataCollector._collect_once()` which runs on a single background thread; the dict is never accessed from `_poll_loop()` or any other thread
- `trigger_refresh()` is the correct integration point (not direct `poll_vehicle()`) because polling is I/O and must happen in `_poll_loop()`, not the synchronous data collection path; worst-case refresh delay is one 30-second poll cycle
- The `update_soc` loop uses `all_vehicles.items()` (already available in scope at line 241) and skips vehicles not in `sequencer.requests` (safe no-op by design in `update_soc()`)
- The plan's instruction to check `pollable` set before calling `trigger_refresh()` is correctly implemented as `if name in pollable` — evcc-only vehicles (without API providers) are excluded since evcc already reports their current SoC from the loadpoint data

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- RELI-01 and RELI-02 are resolved; Phase 4 planner input data is now reliable for connected vehicles
- RELI-05 (RL bootstrap progress logging + record cap) is the remaining Phase 2 requirement, addressed in plan 02
- No blockers for downstream phases

---
*Phase: 02-vehicle-reliability*
*Completed: 2026-02-22*
