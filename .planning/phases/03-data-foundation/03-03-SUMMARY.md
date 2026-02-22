---
phase: 03-data-foundation
plan: 03
subsystem: forecasting
tags: [forecast-chart, svg-chart, sse, state-store, api-endpoint, dashboard, ha-entity-discovery, pv-forecast, consumption-forecast]

# Dependency graph
requires:
  - phase: 03-data-foundation plan 01
    provides: ConsumptionForecaster with InfluxDB bootstrap and HA energy discovery
  - phase: 03-data-foundation plan 02
    provides: PVForecaster with evcc solar tariff integration and correction coefficient
  - phase: 01-state-infrastructure
    provides: StateStore (RLock pattern), SSE broadcast infrastructure, WebServer threading
provides:
  - End-to-end forecast pipeline: InfluxDB/evcc API -> forecasters -> StateStore -> /forecast API -> dashboard chart
  - GET /forecast endpoint returning consumption_96, pv_96, price_zones_96, and all forecaster metadata
  - Pure SVG 24h forecast chart with consumption (blue #00d4ff) and PV (yellow #ffdd00) lines
  - SSE live chart updates: forecast data in every SSE broadcast payload
  - Forecaster maturity indicator: "Verbrauchsprognose: X/14 Tage Daten" in German
  - PV correction label and quality label displayed below chart
  - HA entity warning banner (amber) shown when unconfigured entities detected
affects: [04-predictive-planner, 05-dynamic-buffer, dashboard-ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Pure SVG chart rendering (no external libs) with viewBox 960x250 and margin layout
    - Forecast SSE payload: 'forecast' key added to _snapshot_to_json_dict() output
    - Price zone classification from price_percentiles P30/P60 thresholds
    - Daemon thread HA discovery with shared dict result_store for non-blocking startup
    - applySSEUpdate() extended to handle msg.forecast for live chart updates

key-files:
  created: []
  modified:
    - evcc-smartload/rootfs/app/main.py
    - evcc-smartload/rootfs/app/state_store.py
    - evcc-smartload/rootfs/app/web/server.py
    - evcc-smartload/rootfs/app/web/static/app.js
    - evcc-smartload/rootfs/app/web/templates/dashboard.html

key-decisions:
  - "Price zone classification uses current state.price_percentiles P30/P60 as proxy for all 96 slots — a proper per-slot version requires passing tariff data as 15-min granularity (deferred to Phase 4 when planner generates slot-level decisions)"
  - "PV unit detection in renderForecastChart: pvMax > 20 means Watts (no conversion), else kW (multiply by 1000) — reuses same heuristic as state.py"
  - "Forecast section added to SSE JSON payload outside RLock (same broadcast-after-release pattern as existing state fields)"
  - "consumptionForecaster.apply_correction() called only when current_forecast[0] > 100W — avoids correction on cold-start defaults"

patterns-established:
  - "Pattern: fetchJSON('/forecast').then() at page load for initial chart render; SSE provides subsequent updates"
  - "Pattern: Forecast section in SSE payload enables live chart updates without additional polling endpoint"
  - "Pattern: SVG forecast chart uses xPos(i) / yPos(w) helper functions for clean coordinate math"

requirements-completed: [PLAN-04, PLAN-05]

# Metrics
duration: 3min
completed: 2026-02-22
---

# Phase 03 Plan 03: Forecast Integration and Dashboard Visualization Summary

**End-to-end forecast pipeline wired from InfluxDB/evcc through StateStore to pure SVG 24h dual-line dashboard chart with SSE live updates, German maturity indicators, and HA entity warning banner.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-22T18:22:41Z
- **Completed:** 2026-02-22T18:25:00Z
- **Tasks:** 3 of 3 (Task 3 human-verify checkpoint — approved by user)
- **Files modified:** 5

## Accomplishments

- Wired ConsumptionForecaster and PVForecaster into main decision loop: update every 15-min cycle, PV refresh hourly, correction coefficient updated every cycle
- Extended StateStore with 8 new forecast fields (all under existing RLock) and SSE broadcast payload includes complete forecast section
- Added GET /forecast endpoint to server.py with _compute_price_zones() helper
- Built pure SVG 24h forecast chart (no external libraries): consumption line (blue #00d4ff), PV line (yellow #ffdd00) with fill area, price zone backgrounds, battery phase placeholder, time labels, grid lines
- HA entity warning banner and forecaster maturity indicator in German

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire forecasters into main loop and extend StateStore** - `93eae1c` (feat)
2. **Task 2: Dashboard forecast chart, API endpoint, and SSE integration** - `1feaeb5` (feat)

3. **Task 3: Verify dashboard forecast visualization** - human-verify checkpoint, approved by user

**Plan metadata:** `a8ac21d` (docs: complete forecast integration plan summary and state update)

## Files Created/Modified

- `evcc-smartload/rootfs/app/main.py` - Added forecaster imports, daemon thread HA discovery, forecaster calls in decision loop, extended store.update() call
- `evcc-smartload/rootfs/app/state_store.py` - 8 new forecast fields in __init__, extended update() signature, extended _snapshot_unlocked(), added 'forecast' section to SSE JSON
- `evcc-smartload/rootfs/app/web/server.py` - GET /forecast endpoint, _compute_price_zones() helper method
- `evcc-smartload/rootfs/app/web/static/app.js` - renderForecastChart(), updateForecastMeta(), updateHaWarnings(), extended applySSEUpdate(), initial fetch('/forecast') on page load
- `evcc-smartload/rootfs/app/web/templates/dashboard.html` - CSS for forecast card/banner, HA warning banner div, forecast chart section with maturity/correction/quality spans

## Decisions Made

1. **Price zone classification uses current price as proxy for all 96 slots:** A proper per-slot classification would need tariff data at 15-min granularity, which the main loop doesn't currently pass to StateStore. Phase 4 (predictive planner) will generate slot-level decisions and can provide a proper battery_phases_96 array. The current approach classifies the current price against P30/P60 percentiles and applies it uniformly, giving a useful visual indicator without blocking the chart display.

2. **PV unit auto-detection in renderForecastChart:** `pvMax > 20` means values are in Watts (Forecast.Solar returns Watts), otherwise kW. Reuses the same median heuristic pattern established in state.py.

3. **consumptionForecaster.apply_correction() guard:** Only applied when `current_forecast[0] > 100W` to avoid adjusting the correction factor based on the cold-start default of 1200W (which would be trivially "correct" without being meaningful feedback).

4. **Forecast in SSE broadcast:** The `_snapshot_to_json_dict()` function already takes a snapshot dict argument, so adding the forecast section there is clean and consistent with the existing pattern. No additional locking required.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - forecast chart is automatic. No additional configuration required beyond the existing evcc and InfluxDB connections.

## Next Phase Readiness

- Phase 4 (predictive planner) can now read `forecaster_ready`, `consumption_96`, and `pv_96` from StateStore to make informed decisions
- Battery phase areas are stubbed in the chart (`battery_phases_96` key) — Phase 4 can populate this to show charge/discharge schedule on the chart
- Price zone visualization is simplified (current price proxy) — Phase 4 can improve this by passing per-slot tariff data to the /forecast endpoint
- HA warning banner is wired up — HA entity discovery runs at startup and surfaces warnings in the dashboard

## Self-Check: PASSED

Files exist:
- evcc-smartload/rootfs/app/main.py: FOUND
- evcc-smartload/rootfs/app/state_store.py: FOUND
- evcc-smartload/rootfs/app/web/server.py: FOUND
- evcc-smartload/rootfs/app/web/static/app.js: FOUND
- evcc-smartload/rootfs/app/web/templates/dashboard.html: FOUND
- .planning/phases/03-data-foundation/03-03-SUMMARY.md: FOUND

Commits exist:
- 93eae1c: feat(03-03): wire forecasters into main loop and extend StateStore — FOUND
- 1feaeb5: feat(03-03): dashboard forecast chart, /forecast API endpoint, SSE integration — FOUND

Human verification: Task 3 checkpoint approved by user on 2026-02-22.

---
*Phase: 03-data-foundation*
*Completed: 2026-02-22*
