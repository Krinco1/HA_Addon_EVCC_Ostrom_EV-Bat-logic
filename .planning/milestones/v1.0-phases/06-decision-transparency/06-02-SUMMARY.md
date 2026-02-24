---
phase: 06-decision-transparency
plan: 02
subsystem: ui
tags: [svg-chart, gantt, tooltip, tab-navigation, plan-visualization, decision-transparency]

# Dependency graph
requires:
  - phase: 06-decision-transparency
    plan: 01
    provides: GET /plan endpoint returning 96-slot PlanHorizon with per-slot explanations, tab-plan container in dashboard.html

provides:
  - switchTab() function overriding dashboard.html inline fallback, enabling Plan/History lazy-loading
  - fetchAndRenderPlan() fetching /plan and delegating to renderPlanGantt()
  - renderPlanGantt() SVG Gantt chart with 4 bar types, price overlay, time labels, hover tooltips, click-detail
  - fetchAndRenderHistory() stub for Plan 03

affects:
  - 06-03 (History tab content — fetchAndRenderHistory stub ready, historyContent container wired)
  - 07-driver-interaction (Plan tab may show manual override markers in future)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Gantt chart: SVG string-concatenation pattern matching existing renderChart()/renderForecastChart()"
    - "PV drawn first (z-order), then action bars, then price polyline on top"
    - "Stacking bars: stackY starts at bottom of plot area (marginT+plotH), decrements for each kW layer"
    - "Transparent hit-areas for hold/idle slots (fill:transparent class=plan-slot) ensure full-width tooltip coverage"
    - "Tooltip: absolute-positioned div injected after SVG, positioned via mousemove offsetting from wrap.getBoundingClientRect()"
    - "Click-detail: populates #planDetail with grid of slot values + explanation_long paragraph"
    - "All var declarations (no let/const) for ES5 compatibility matching codebase style"

key-files:
  created: []
  modified:
    - evcc-smartload/rootfs/app/web/static/app.js

key-decisions:
  - "Transparent hit-area rects for hold/idle slots ensure all 96 slots respond to hover/click, not just active bars"
  - "Stack ordering: bat_charge first (lowest), then bat_discharge, then ev_charge — discharge rarely co-occurs with charge but stacking is correct for edge cases"
  - "Tooltip overflow protection: if tooltip would clip right edge of wrap, shift left by 302px"
  - "marginR=50 (not 20) to accommodate right-side price ct/kWh axis labels"

patterns-established:
  - "Plan Gantt follows same SVG string-build pattern as renderChart() and renderForecastChart() — consistent with codebase"
  - "fetchAndRenderPlan() is called lazily by switchTab('plan') — no data fetched until tab is active"

requirements-completed: [TRAN-02, TRAN-01]

# Metrics
duration: 8min
completed: 2026-02-23
---

# Phase 6 Plan 02: SVG Gantt Chart with Price Overlay, Tooltips, and Click-Detail Summary

**Interactive SVG Gantt chart rendering 96 dispatch slots with color-coded action bars (green/orange/blue), PV background (gold), red price polyline, hover tooltips showing German short explanation, and click-to-expand detail panel with long explanation**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-23T19:03:59Z
- **Completed:** 2026-02-23T19:11:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Implemented `switchTab()` in app.js overriding the dashboard.html inline fallback, with lazy-loading of Plan/History data on tab switch
- Implemented `fetchAndRenderPlan()` fetching GET /plan, handling no-data empty state, storing `window._planSlots` for click access
- Implemented `renderPlanGantt(slots, computedAt)` building a full SVG Gantt chart following the existing `renderChart()`/`renderForecastChart()` string-concatenation pattern with: PV background bars (gold, 20% opacity), action bars stacked bottom-up (bat charge green, bat discharge orange, EV charge blue), red price polyline overlay, Y-axis labels for both kW and ct scales, X-axis time labels every 2 hours, computed-at timestamp label, color legend
- Implemented hover tooltip (explanation_short) with overflow-protected positioning and click-to-expand detail panel (explanation_long, slot values grid)

## Task Commits

Each task was committed atomically:

1. **Task 1: switchTab() and fetchAndRenderPlan()** - `4a8fec4` (feat)
2. **Task 2: renderPlanGantt() SVG chart with tooltip and click-detail** - `73d0e39` (feat)

## Files Created/Modified

- `evcc-smartload/rootfs/app/web/static/app.js` - Added switchTab(), fetchAndRenderHistory() stub, renderPlanGantt(), fetchAndRenderPlan()

## Decisions Made

- **Transparent hit-areas for idle slots:** Plan slots with no active action (hold/idle) get a transparent full-height rect with `class="plan-slot"` so tooltip and click-detail work across all 96 positions, not just where bars are drawn.
- **marginR=50 for right price axis:** Changed from the plan's suggested 20px to 50px to accommodate the right-side price (ct/kWh) axis labels without clipping.
- **Stack ordering:** bat_charge at bottom, bat_discharge above it, ev_charge topmost. Discharge and charge rarely co-occur but stacking is logically correct and consistent with "charge = foundation, EV = top demand".
- **Tooltip left-overflow guard:** If tooltip would extend past the right edge of wrap, it shifts left by 302px (tooltip max-width 280px + 22px margin) for overflow protection.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Plan tab fully functional: fetch /plan -> SVG Gantt renders with all 4 bar types + price overlay, hover tooltips, click-detail panel
- `switchTab()` is the definitive implementation — Plan 03 just needs to implement `fetchAndRenderHistory()` (stub is in place)
- `#historyContent` container is already in dashboard.html from Plan 01, ready for Plan 03 to populate

---
*Phase: 06-decision-transparency*
*Completed: 2026-02-23*
