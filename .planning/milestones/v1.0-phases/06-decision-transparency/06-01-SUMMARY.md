---
phase: 06-decision-transparency
plan: 01
subsystem: api
tags: [explanation-generator, german-text, plan-endpoint, tab-navigation, decision-transparency]

# Dependency graph
requires:
  - phase: 04-predictive-planner
    provides: DispatchSlot and PlanHorizon dataclasses with per-slot price, PV, SoC data
  - phase: 01-state-infrastructure
    provides: StateStore with get_plan() method used by /plan endpoint

provides:
  - ExplanationGenerator class with explain() method producing German short/long text
  - GET /plan endpoint returning 96-slot PlanHorizon with per-slot explanations
  - 3-tab dashboard navigation skeleton (Status/Plan/Historie)

affects:
  - 06-02 (Gantt chart renders data from /plan endpoint, uses tab-plan container)
  - 06-03 (Historie tab container provided here, populated by Plan 03)
  - 07-driver-interaction (Plan tab may show manual override markers)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ExplanationGenerator: stateless class, explain(slot, plan) -> {short, long}"
    - "Price rank: 1-based count of slots with strictly lower price (no bisect import needed)"
    - "Cost delta: price-comparison approximation (current vs min future), 'ca.' prefix per user convention"
    - "German decimal formatting: _de_float() helper converts float to comma-separated string"
    - "Tab navigation: CSS display:none/block toggling, inline switchTab() fallback in HTML"

key-files:
  created:
    - evcc-smartload/rootfs/app/explanation_generator.py
  modified:
    - evcc-smartload/rootfs/app/web/server.py
    - evcc-smartload/rootfs/app/web/templates/dashboard.html

key-decisions:
  - "Cost delta uses simple price-comparison approximation (current slot price vs cheapest future slot), not LP dual variables — marked 'ca.' as per user decision in CONTEXT.md"
  - "switchTab() defined as inline fallback in dashboard.html with 'if typeof === undefined' guard — app.js can override with full implementation in Plan 02"
  - "bat_soc_pct and departure_hours also formatted with German decimal comma for consistency"

patterns-established:
  - "ExplanationGenerator is instantiated once in WebServer.__init__() and reused per request"
  - "Plan 02 will add fetchAndRenderPlan() call inside switchTab() for lazy-loading"

requirements-completed: [TRAN-01, TRAN-02]

# Metrics
duration: 5min
completed: 2026-02-23
---

# Phase 6 Plan 01: ExplanationGenerator, /plan Endpoint, 3-Tab Navigation Summary

**German-language ExplanationGenerator class, GET /plan API serializing 96 DispatchSlots with per-slot explanations, and 3-tab dashboard skeleton fulfilling TRAN-01 and TRAN-02 backend foundation**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-23T18:55:58Z
- **Completed:** 2026-02-23T19:00:53Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created `explanation_generator.py` with `ExplanationGenerator` class covering all 4 slot action types (bat_charge, bat_discharge, ev_charge, hold) with German short/long text
- Added GET `/plan` endpoint to `server.py` returning full 96-slot PlanHorizon serialization with per-slot `explanation_short` and `explanation_long` fields
- Added 3-tab navigation (Status/Plan/Historie) to `dashboard.html` with CSS, HTML structure, and inline `switchTab()` fallback

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ExplanationGenerator** - `2efec66` (feat)
2. **Task 2: Add GET /plan endpoint and 3-tab dashboard navigation** - `f1f9546` (feat)

## Files Created/Modified
- `evcc-smartload/rootfs/app/explanation_generator.py` - ExplanationGenerator class with explain(), _price_stats(), _de_float() helpers
- `evcc-smartload/rootfs/app/web/server.py` - Added ExplanationGenerator import, instantiation, _api_plan() method, /plan route
- `evcc-smartload/rootfs/app/web/templates/dashboard.html` - Tab CSS, tab-nav HTML, tab-main wrapper, tab-plan/tab-history containers, switchTab() fallback

## Decisions Made
- **Cost delta approximation:** Used "current slot price vs cheapest future slot" comparison rather than LP dual variables. The result is prefixed with "ca." per user's explicit convention in CONTEXT.md. LP dual variables would be more precise but are harder to interpret for non-experts.
- **switchTab() fallback:** Added inline `if (typeof switchTab === 'undefined')` guard in dashboard.html so the basic tab-switching works immediately. Plan 02 will override this in app.js with the full implementation including `fetchAndRenderPlan()` and `fetchAndRenderHistory()` calls.
- **German decimal formatting:** Applied comma decimal separator to all user-facing numeric values (price in ct, departure hours, SOC percentages) for full German convention consistency.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `numpy` not available in local Windows Python environment — verification adapted to mock numpy before importing `state.py`. This is expected: numpy is always present in the Docker container where the add-on runs. All logic verified via mock-based smoke tests.

## Next Phase Readiness
- `/plan` endpoint is live and returns full 96-slot data with explanations — Plan 02 (Gantt chart) can immediately fetch and render this
- `tab-plan` and `tab-history` containers are in place — Plan 02 renders Gantt into `#planChartWrap`, Plan 03 renders history into `#historyContent`
- `ExplanationGenerator` is wired into `WebServer` and ready for use

---
*Phase: 06-decision-transparency*
*Completed: 2026-02-23*
