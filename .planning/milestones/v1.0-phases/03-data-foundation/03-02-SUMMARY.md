---
phase: 03-data-foundation
plan: 02
subsystem: forecasting
tags: [pv-forecast, evcc-api, correction-coefficient, ema, threading, json-persistence, alpine]

# Dependency graph
requires:
  - phase: 03-data-foundation plan 01
    provides: forecaster package skeleton (__init__.py, ConsumptionForecaster)
  - phase: 01-state-infrastructure
    provides: evcc_client.get_tariff_solar(), logging_util, threading patterns
provides:
  - PVForecaster class with 96-slot (15-min) PV generation forecast from evcc solar tariff API
  - Coverage-based confidence float (0.0-1.0) for partial forecast handling
  - Rolling correction coefficient with EMA, daytime-only updates, bounds [0.3, 3.0]
  - German dashboard labels: correction_label and quality_label
  - Versioned atomic JSON persistence at /data/smartprice_pv_model.json
  - Updated forecaster/__init__.py exporting both ConsumptionForecaster and PVForecaster
affects: [03-03-data-foundation, 04-predictive-planner, 05-dynamic-buffer, dashboard-forecast-chart]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Watt-to-kW unit detection via median heuristic (reuse from state.py:calc_solar_surplus_kwh)
    - Daytime-only coefficient update gate (forecast > 50W threshold)
    - EMA correction coefficient with [0.3, 3.0] clamp for PV variability
    - threading.Lock for concurrent read/write protection of forecast slots
    - Atomic JSON write pattern (write .tmp then os.rename)
    - Variable slot duration parsing via (end - start).total_seconds() / 3600

key-files:
  created:
    - evcc-smartload/rootfs/app/forecaster/pv.py
  modified:
    - evcc-smartload/rootfs/app/forecaster/__init__.py

key-decisions:
  - "Correction EMA alpha=0.1 per 15-min cycle: smoother reaction, avoids overcorrecting on transient clouds"
  - "Correction bounds [0.3, 3.0]: PV can legitimately be 3x forecast (unexpectedly sunny) unlike consumption [0.5, 1.5]"
  - "Variable slot duration computed per slot via (end - start).total_seconds(): handles mixed 15-min and 1h evcc slot sources"
  - "future_hours sums actual slot durations (not slot count) for accurate partial forecast detection"
  - "Only _correction persisted (not _slots): forecast data is ephemeral, re-fetched hourly"

patterns-established:
  - "Pattern: Daytime gate - never update coefficient when forecast <= DAYTIME_THRESHOLD_W (50W)"
  - "Pattern: Confidence = min(1.0, coverage_hours / 24.0) for proportional partial forecast handling"
  - "Pattern: 96-slot output interpolates variable-duration evcc slots by finding the covering [start, end) range"

requirements-completed: [PLAN-05]

# Metrics
duration: 2min
completed: 2026-02-22
---

# Phase 3 Plan 02: PVForecaster Summary

**PVForecaster with 96-slot evcc solar tariff integration, daytime-only EMA correction coefficient, partial forecast confidence, and versioned JSON persistence**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-22T18:16:12Z
- **Completed:** 2026-02-22T18:18:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Created `forecaster/pv.py` (425 lines) with full PVForecaster class implementing all plan requirements
- Correct Watt-to-kW unit detection by reusing the median heuristic from `state.py:calc_solar_surplus_kwh()`
- Daytime-only correction coefficient updates (Research Pitfall 7: avoids nighttime drift to zero)
- Coverage-based confidence: partial forecasts reduce confidence proportionally (12h = 0.5)
- Total API failure case: 96 zeros returned, confidence = 0.0 (conservative and safe)
- Updated `forecaster/__init__.py` to export both `ConsumptionForecaster` and `PVForecaster`

## Task Commits

Each task was committed atomically:

1. **Task 1: PVForecaster with evcc solar tariff integration and correction coefficient** - `3108c12` (feat)

*Note: pv.py was committed as part of the Plan 01 commit since the forecaster directory was staged together. The implementation is complete and committed.*

**Plan metadata:** (created after this summary)

## Files Created/Modified

- `evcc-smartload/rootfs/app/forecaster/pv.py` - PVForecaster class: hourly evcc API refresh, 96-slot 15-min interpolation, EMA correction coefficient with daytime guard, coverage confidence, German dashboard labels, versioned atomic JSON persistence
- `evcc-smartload/rootfs/app/forecaster/__init__.py` - Added PVForecaster export alongside ConsumptionForecaster

## Decisions Made

- EMA alpha=0.1 per 15-min update cycle: provides smooth correction that avoids overcorrecting on transient cloud cover while still tracking persistent conditions
- Correction bounds [0.3, 3.0]: wider than consumption correction [0.5, 1.5] because PV output can legitimately be 3x forecast on unexpectedly sunny days
- Variable slot duration per slot: `(end - start).total_seconds() / 3600` computed per slot to handle both 15-min (Forecast.Solar) and 1-hour (Open-Meteo) evcc sources without assuming fixed intervals
- `future_hours` sums actual slot durations (not slot count) so partial forecast detection is accurate when slot sizes differ
- Only `_correction` persisted to disk (not `_slots`): forecast data is ephemeral and re-fetched hourly, persisting it would add complexity without benefit

## Deviations from Plan

None - plan executed exactly as written. All Research Pitfalls avoided as specified.

## Issues Encountered

The `forecaster/` directory and `__init__.py` were partially created from Plan 01 work staged but not committed. The Plan 01 commit included `pv.py` as it was in the working tree when staged. The resulting implementation fully satisfies Plan 02's requirements (all 10 verification checks pass, 425 lines vs 120 minimum).

## User Setup Required

None - no external service configuration required. PVForecaster uses the existing `evcc_client.get_tariff_solar()` method which requires no additional configuration beyond the existing evcc connection.

## Next Phase Readiness

- `PVForecaster` is ready to be wired into the main loop by Plan 03
- Plan 03 will: import PVForecaster, call `refresh()` on hourly timer, call `update_correction()` every 15-min cycle, pass `get_forecast_24h()` to planner
- `forecaster/__init__.py` now exports both `ConsumptionForecaster` and `PVForecaster` — Plan 03 can import both from the package
- German dashboard labels (`correction_label`, `quality_label`) are ready for the SVG forecast chart (Plan 03)

---
*Phase: 03-data-foundation*
*Completed: 2026-02-22*
