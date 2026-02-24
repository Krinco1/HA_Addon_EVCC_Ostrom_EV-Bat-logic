---
phase: 05-dynamic-buffer
plan: 02
subsystem: dashboard-ui
tags: [dynamic-buffer, dashboard, sse, svg-chart, observation-mode, web-api]

# Dependency graph
requires:
  - phase: 05-01
    provides: DynamicBufferCalc engine, buffer_result in SSE payload as data.buffer
provides:
  - Dashboard buffer section: observation banner with countdown and controls
  - Collapsible PV-confidence widget (summary + expandable detail)
  - SVG buffer history line chart with 10%/20% reference lines
  - Expandable event log table with observation entries visually muted
  - POST /buffer/activate-live endpoint
  - POST /buffer/extend-obs endpoint with days validation (1-90)
affects: [PLAN-03 complete, Phase 5 done]

# Tech tracking
tech-stack:
  added: []  # no new dependencies
  patterns:
    - "Pure SVG chart rendered inline (same style as existing renderForecastChart)"
    - "SSE handler extended: applySSEUpdate() calls updateBufferSection(msg.buffer)"
    - "WebServer constructor extended with buffer_calc=None; late-assigned in main.py"
    - "Observation vs live entries distinguished via e.mode === 'observation' || e.applied === false"

key-files:
  created: []
  modified:
    - evcc-smartload/rootfs/app/web/templates/dashboard.html
    - evcc-smartload/rootfs/app/web/static/app.js
    - evcc-smartload/rootfs/app/web/server.py
    - evcc-smartload/rootfs/app/main.py

key-decisions:
  - "Late attribute assignment for buffer_calc in main.py (web.buffer_calc = buffer_calc) consistent with all other components in the codebase"
  - "SVG chart uses two separate polylines (obs dashed + live solid) for visual mode distinction"
  - "Event log limited to last 50 entries reversed (most recent first) for performance"
  - "confirm() dialog before activateBufferLive() to prevent accidental live activation"

# Metrics
duration: 4min
completed: 2026-02-23
---

# Phase 5 Plan 02: Dynamic Buffer Dashboard UI Summary

**Complete dynamic buffer dashboard section: observation banner with countdown and controls, collapsible PV-confidence widget, SVG buffer history line chart, expandable event log table with observation mode distinction, and POST API endpoints for mode control**

## Performance

- **Duration:** ~4 min
- **Completed:** 2026-02-23T10:23:49Z
- **Tasks:** 2 of 3 complete (Task 3 is human-verify checkpoint)
- **Files modified:** 4

## Accomplishments

- Added buffer section to `dashboard.html`: observation mode banner (`#bufferObsBanner`) with countdown text and Jetzt-aktivieren/Verlängern buttons, "Dynamischer Puffer" chart-card with collapsible confidence widget, SVG chart container, and event log table with thead/tbody
- Added CSS for all buffer UI elements: `.obs-banner` (amber, consistent with existing HA warning banner style), `.conf-widget`, `.conf-summary`/`.conf-detail`, `.buffer-log-table`, `.buffer-log-obs` (muted/italic for observation entries), `.btn-sm`
- Added to `app.js`: `updateBufferSection()` (main SSE handler), `renderBufferChart()` (pure SVG line chart with 10%/20% reference lines, obs=dashed/live=solid), `renderBufferLog()` (most-recent-first table, last 50 entries), `toggleConfDetail()` (collapsible widget), `activateBufferLive()` (fetch POST with confirm dialog), `extendBufferObs()` (fetch POST with 14-day body)
- Extended `applySSEUpdate()` in app.js to call `updateBufferSection(msg.buffer)` on each SSE event
- Added `buffer_calc=None` parameter to `WebServer.__init__()` with `self.buffer_calc` attribute
- Added `POST /buffer/activate-live`: calls `buffer_calc.activate_live()`, returns `{ok, mode}`
- Added `POST /buffer/extend-obs`: validates `days` (1-90), calls `buffer_calc.extend_observation(extra_days=days)`, returns `{ok, mode, extended_days}`
- Both endpoints return 503 when `buffer_calc is None`
- Wired `web.buffer_calc = buffer_calc` in main.py after all components initialized

## Task Commits

1. **Task 1: Dashboard HTML/CSS buffer section and JS chart/table/SSE integration** - `ebe95bb` (feat)
2. **Task 2: POST API endpoints for manual observation mode control** - `4eb0c31` (feat)

## Files Created/Modified

- `evcc-smartload/rootfs/app/web/templates/dashboard.html` - Buffer section: observation banner, chart-card with confidence widget, SVG chart, event log table; new CSS block for all buffer UI elements
- `evcc-smartload/rootfs/app/web/static/app.js` - updateBufferSection(), renderBufferChart(), renderBufferLog(), toggleConfDetail(), activateBufferLive(), extendBufferObs(); SSE handler extended
- `evcc-smartload/rootfs/app/web/server.py` - buffer_calc parameter in WebServer.__init__(), POST /buffer/activate-live, POST /buffer/extend-obs
- `evcc-smartload/rootfs/app/main.py` - web.buffer_calc = buffer_calc assignment

## Decisions Made

- Late attribute assignment pattern: `web.buffer_calc = buffer_calc` in main.py after all components initialized — consistent with sequencer, notifier, driver_mgr, and all other components; WebServer is started early before components are initialized, so constructor injection is not feasible here
- SVG chart draws two separate polyline paths for observation (dashed, 50% opacity) and live (solid, full opacity) entries, providing immediate visual mode distinction
- Event log `slice(-50).reverse()` — last 50 most-recent entries shown to keep table performant with 700-entry log
- confirm() dialog before `activateBufferLive()` — user must explicitly confirm before exiting observation mode

## Deviations from Plan

### Auto-fixed Issues

None.

### Minor Deviations

**1. [Minor] buffer_calc injected via attribute assignment, not constructor keyword argument**
- **Found during:** Task 2
- **Issue:** Plan's verify script checked for `buffer_calc=buffer_calc` as a constructor keyword argument in main.py. However, WebServer is constructed early in main.py (before buffer_calc is created) to serve the config-error page. Late attribute assignment (`web.buffer_calc = buffer_calc`) is the consistent pattern used for all other components (sequencer, notifier, driver_mgr, etc.).
- **Fix:** Used `web.buffer_calc = buffer_calc` after all components are initialized (line 206)
- **Impact:** Functionally identical — buffer_calc is available to all request handlers via `srv.buffer_calc`

## Self-Check: PENDING

Awaiting Task 3 human verification checkpoint.
