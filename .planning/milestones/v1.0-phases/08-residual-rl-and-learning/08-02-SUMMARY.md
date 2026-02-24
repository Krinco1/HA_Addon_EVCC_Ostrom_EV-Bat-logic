---
phase: 08-residual-rl-and-learning
plan: "02"
subsystem: learning
tags: [seasonal-learning, forecast-reliability, rolling-mae, json-persistence, threading]

# Dependency graph
requires:
  - phase: 05-dynamic-buffer
    provides: DynamicBufferCalc atomic JSON persistence pattern (tmp + os.replace, lock/IO separation)
provides:
  - SeasonalLearner with 48-cell lookup table, DJF/MAM/JJA/SON season mapping, atomic JSON persistence
  - ForecastReliabilityTracker with per-source rolling MAE, confidence factors [0..1], atomic JSON persistence
affects:
  - 08-03 (residual RL agent will import both learners for correction and confidence weighting)
  - main.py wiring (Phase 8 plan 03 or later injects both into the main loop)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SeasonalLearner: 48-cell (season×time_period×weekend) lookup table with running average"
    - "ForecastReliabilityTracker: per-source deque rolling MAE normalized against reference scales"
    - "Persist-every-N pattern: serialize under lock, write outside lock, every 10 updates"

key-files:
  created:
    - evcc-smartload/rootfs/app/seasonal_learner.py
    - evcc-smartload/rootfs/app/forecast_reliability.py
  modified: []

key-decisions:
  - "MONTH_TO_SEASON explicit dict avoids naive (month-1)//3 bug that maps December to season 3 (autumn)"
  - "get_correction_factor() returns None below min_samples=10 — low-confidence cells do not distort optimizer"
  - "ForecastReliabilityTracker returns confidence=1.0 below 5 samples — assume reliable until proven otherwise"
  - "PV reference scale is 5.0 kW (not 5000 W) — callers must convert state.pv_power from W to kW"
  - "No decay in SeasonalLearner (simple running average) — per research recommendation; decay deferred to Phase 9"

patterns-established:
  - "Explicit month-season mapping via dict — never use arithmetic mapping for non-contiguous month groups"
  - "Unit contract in docstring — PV kW requirement documented in update() to prevent caller mistakes"

requirements-completed: [LERN-02, LERN-04]

# Metrics
duration: 2min
completed: 2026-02-23
---

# Phase 8 Plan 02: Seasonal Learner and Forecast Reliability Tracker Summary

**48-cell seasonal plan error accumulator and per-source rolling MAE tracker — both with atomic JSON persistence and thread-safe access — ready to begin data accumulation**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-23T21:29:59Z
- **Completed:** 2026-02-23T21:32:25Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- SeasonalLearner accumulates plan_error_eur in 48 cells indexed by (season, time_period, is_weekend); get_correction_factor() suppresses low-confidence cells (< 10 samples)
- ForecastReliabilityTracker maintains 50-cycle rolling MAE deque per source (pv/consumption/price) and exposes confidence [0.0, 1.0]
- Both modules survive container restarts via atomic JSON persistence (tmp + os.replace, lock-then-release-IO pattern from DynamicBufferCalc)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create SeasonalLearner module** - `b86cff0` (feat)
2. **Task 2: Create ForecastReliabilityTracker module** - `808ab3d` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `evcc-smartload/rootfs/app/seasonal_learner.py` - SeasonalLearner with 48-cell DJF/MAM/JJA/SON lookup, update(), get_correction_factor(), atomic JSON to /data/smartprice_seasonal_model.json
- `evcc-smartload/rootfs/app/forecast_reliability.py` - ForecastReliabilityTracker with rolling MAE (pv kW / consumption W / price EUR/kWh), confidence factors, atomic JSON to /data/smartprice_forecast_reliability.json

## Decisions Made
- MONTH_TO_SEASON explicit dict avoids the naive arithmetic bug that maps December to season 3 (autumn)
- get_correction_factor() returns None below min_samples=10 threshold — prevents spurious corrections from cells with few observations
- ForecastReliabilityTracker confidence defaults to 1.0 below 5 samples — "assume reliable until proven otherwise"
- PV reference scale is 5.0 kW; callers must convert state.pv_power (W) to kW before passing — documented in update() docstring
- No exponential decay in SeasonalLearner — simple running average per research recommendation; decay can be added in Phase 9 after observing convergence behavior

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Both modules begin accumulating data automatically when wired into the main loop (Phase 8 plan 03+).

## Next Phase Readiness
- SeasonalLearner and ForecastReliabilityTracker are ready to import as standalone modules
- Phase 8 plan 03 (RL agent wiring) can import both and call update() each cycle
- Data accumulation starts immediately on deployment; correction factors become available after ~10 plan cycles per cell

## Self-Check: PASSED

- FOUND: evcc-smartload/rootfs/app/seasonal_learner.py
- FOUND: evcc-smartload/rootfs/app/forecast_reliability.py
- FOUND: .planning/phases/08-residual-rl-and-learning/08-02-SUMMARY.md
- FOUND: commit b86cff0 (feat(08-02): SeasonalLearner)
- FOUND: commit 808ab3d (feat(08-02): ForecastReliabilityTracker)

---
*Phase: 08-residual-rl-and-learning*
*Completed: 2026-02-23*
