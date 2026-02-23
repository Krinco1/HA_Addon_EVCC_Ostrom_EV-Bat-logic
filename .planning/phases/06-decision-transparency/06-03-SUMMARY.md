---
phase: 06-decision-transparency
plan: 03
subsystem: history-comparison
tags: [plan-snapshotter, influxdb, history-endpoint, svg-chart, cost-deviation, decision-transparency]

# Dependency graph
requires:
  - phase: 06-decision-transparency
    plan: 01
    provides: ExplanationGenerator, GET /plan endpoint, tab navigation skeleton
  - phase: 06-decision-transparency
    plan: 02
    provides: switchTab() implementation, fetchAndRenderHistory() stub, #historyContent container
  - phase: 04-predictive-planner
    provides: PlanHorizon with .slots[0] (bat_charge_kw, bat_discharge_kw, ev_charge_kw, price_eur_kwh) and .solver_fun

provides:
  - PlanSnapshotter class with write_snapshot() and query_comparison()
  - GET /history endpoint returning planned-vs-actual rows with cost_delta_eur for 24h/7d
  - fetchAndRenderHistory() replacing Plan 02 stub — full chart + table implementation
  - renderHistoryChart() SVG overlay chart (planned dashed green, actual solid blue, fill areas)
  - renderHistoryTable() detail table with per-row cost deviation in EUR, color-coded green/red
  - toggleHistoryRange() for 24h/7d switch with active button state
  - Empty state handling when InfluxDB unavailable or no data

affects:
  - REQUIREMENTS: TRAN-04 completed
  - decision loop: write_snapshot() called each LP cycle (fire-and-forget, never crashes)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PlanSnapshotter follows same try/except guard pattern as DynamicBufferCalc.step() — never crashes decision loop"
    - "query_comparison() uses direct requests.get() matching InfluxDBClient pattern for consistent HTTP handling"
    - "History SVG chart uses SVG string-concatenation pattern matching renderChart()/renderForecastChart()/renderPlanGantt()"
    - "Cost delta approximation: (actual_price_ct - planned_price_ct) / 100 * planned_bat_charge_kw * 0.25 (15-min slot energy cost diff)"
    - "fill areas: red polygon (plan - actual, plan on top) for costlier than planned; green polygon (actual - plan) for cheaper than planned"

key-files:
  created:
    - evcc-smartload/rootfs/app/plan_snapshotter.py
  modified:
    - evcc-smartload/rootfs/app/main.py
    - evcc-smartload/rootfs/app/web/server.py
    - evcc-smartload/rootfs/app/web/static/app.js
    - evcc-smartload/rootfs/app/web/templates/dashboard.html

key-decisions:
  - "PlanSnapshotter uses direct requests calls (not InfluxDBClient.query()) because InfluxDBClient.query_*() methods all have specific response shapes — a direct get() with custom column parsing is cleaner for a new measurement"
  - "actual_bat_power_kw returned in rows (W-to-kW converted server-side in query_comparison) — avoids JS division and keeps unit consistency with planned_bat_charge_kw"
  - "SVG fill areas use two separate polygon paths (one red, one green) rather than per-segment comparison — simpler code at the cost of occasional visual overlap for mixed deviation"
  - "96-row display limit with 'Zeige letzte N von M' notice — matches existing buffer-log-table pattern"
  - "toggleHistoryRange() uses data-hours attribute on buttons for active state detection — avoids hardcoded index lookup"

requirements-completed: [TRAN-04]

# Metrics
duration: 4min
completed: 2026-02-23
---

# Phase 6 Plan 03: Plan Snapshot Storage, /history Endpoint, and Historie Tab Summary

**InfluxDB plan snapshot storage (PlanSnapshotter), GET /history planned-vs-actual endpoint, and complete Historie tab with SVG overlay chart and cost-deviation detail table closing the TRAN-04 feedback loop**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-23T19:10:05Z
- **Completed:** 2026-02-23T19:13:33Z
- **Tasks:** 2
- **Files modified:** 4 (+ 1 created)

## Accomplishments

- Created `plan_snapshotter.py` with `PlanSnapshotter` class:
  - `write_snapshot(plan, actual_state)`: writes slot-0 planned fields + actual battery/EV/price data to `smartload_plan_snapshot` InfluxDB measurement; wrapped entirely in try/except, never raises
  - `query_comparison(hours)`: queries the measurement for 24h/7d, converts actual_bat_power_w to kW, computes `cost_delta_eur` per row as approximate 15-min slot cost difference
- Updated `main.py`: import and instantiate PlanSnapshotter, call `write_snapshot()` each LP decision cycle after `store.update_plan()`, wire to `web.plan_snapshotter`
- Updated `server.py`: add `urlparse`/`parse_qs` imports, `plan_snapshotter = None` attribute, `GET /history` route with `?hours=24|168` query parameter support
- Updated `app.js`: replaced `fetchAndRenderHistory()` stub with full implementation; added `renderHistoryChart()` (SVG overlay), `renderHistoryTable()` (cost-deviation detail), `toggleHistoryRange()` (24h/7d), `_pad2()` helper, `_historyHours` state variable
- Updated `dashboard.html`: replaced empty `#tab-history` skeleton with range-toggle buttons (24h/7 Tage), `#historyChartWrap`, `#historyTableWrap`, `#historySummary`, `#historyNoData` empty state

## Task Commits

Each task was committed atomically:

1. **Task 1: PlanSnapshotter, wire into decision loop, GET /history endpoint** - `2e1d9e2` (feat)
2. **Task 2: Historie tab UI with overlay chart and cost-deviation table** - `4e163b5` (feat)

## Files Created/Modified

- `evcc-smartload/rootfs/app/plan_snapshotter.py` - PlanSnapshotter with write_snapshot() and query_comparison()
- `evcc-smartload/rootfs/app/main.py` - PlanSnapshotter import, instantiation, write_snapshot() call in decision loop, web.plan_snapshotter late assignment
- `evcc-smartload/rootfs/app/web/server.py` - urlparse/parse_qs import, plan_snapshotter=None attribute, GET /history route
- `evcc-smartload/rootfs/app/web/static/app.js` - Full fetchAndRenderHistory(), renderHistoryChart(), renderHistoryTable(), toggleHistoryRange(), _pad2()
- `evcc-smartload/rootfs/app/web/templates/dashboard.html` - Updated #tab-history panel with full structure

## Decisions Made

- **Direct requests.get() in query_comparison()**: InfluxDBClient's existing query methods (query_home_power_15min, etc.) all have fixed response shapes. For the new `smartload_plan_snapshot` measurement with a dynamic column set, a direct requests.get() call with column-indexed parsing is cleaner and avoids coupling to the specific helper methods.
- **W-to-kW conversion server-side**: `query_comparison()` converts `actual_bat_power_w` to kW and returns `actual_bat_power_kw` in the row dict. This keeps the JS rendering code simple (consistent kW units across planned and actual).
- **SVG fill areas**: Two separate polygon paths (red fills where planned > actual, green where actual > planned) using full-width polygons traversed forward and backward. This is the same approach as the existing buffer chart patterns.
- **96-row display limit**: Matches the existing `buffer-log-table` pattern in the Phase 5 buffer card.

## Deviations from Plan

### Auto-fixed Issues

None.

**Plan 01's #tab-history skeleton** only had `<div id="historyContent">` and `<div id="historyNoData">`. The plan specified a richer structure with cards, toggle buttons, and separate chart/table wraps. These were added as specified in Plan 03's task description — this is additive HTML structure, not a deviation from intent.

## Issues Encountered

None — `requests` module not available in local Windows Python environment (expected). Import verified with mocked dependencies. All logic runs in Docker container where requests is always present.

## Self-Check
---

## Self-Check: PASSED

- `evcc-smartload/rootfs/app/plan_snapshotter.py`: FOUND
- `2e1d9e2` (Task 1 commit): FOUND
- `4e163b5` (Task 2 commit): FOUND
- `fetchAndRenderHistory` in app.js: 4 occurrences (declaration + 2 calls + 1 switchTab reference)
- `renderHistoryChart` in app.js: 2 occurrences
- `renderHistoryTable` in app.js: 2 occurrences
- `historyChartWrap` in dashboard.html: 1 occurrence
- `/history` in server.py: 2 occurrences
- `plan_snapshotter` in main.py: 5 occurrences

---
*Phase: 06-decision-transparency*
*Completed: 2026-02-23*
