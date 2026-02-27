---
phase: 10-poll-now-button-soc-dashboard
plan: 01
subsystem: api
tags: [http, throttle, vehicles, rate-limit]

requires:
  - phase: 09-vehicle-soc-provider-fix
    provides: VehicleMonitor with trigger_refresh, get_all_vehicles, VehicleManager with get_vehicle_config and disabled flag
provides:
  - Server-side 5-minute per-vehicle poll throttle on POST /vehicles/refresh
  - Disabled vehicle filtering on GET /vehicles API
  - HTTP 429 response with retry_in_seconds for throttled requests
affects: [10-02-PLAN, dashboard, vehicles]

tech-stack:
  added: []
  patterns: [per-endpoint throttle dict on WebServer, disabled-vehicle filtering via manager config]

key-files:
  created: []
  modified:
    - evcc-smartload/rootfs/app/web/server.py

key-decisions:
  - "Throttle dict on WebServer, not VehicleMonitor — internal trigger_refresh stays unthrottled"
  - "300-second (5 min) hardcoded window — simple, matches UI refresh UX"
  - "CPython GIL sufficient for dict thread safety — no Lock needed"

patterns-established:
  - "HTTP throttle pattern: per-key dict with time.time() comparison"
  - "Disabled vehicle filtering at API boundary, not in data layer"

requirements-completed: [SOC-03, SOC-04]

duration: 3min
completed: 2026-02-27
---

# Plan 10-01: Server-side Poll Throttle + Disabled Vehicle Filtering Summary

**POST /vehicles/refresh rate-limited to 5-min per vehicle with HTTP 429 + countdown, GET /vehicles filters disabled vehicles**

## Performance

- **Duration:** 3 min
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- POST /vehicles/refresh returns HTTP 429 with retry_in_seconds when called within 5 minutes of last trigger
- Missing vehicle name returns HTTP 400 error
- GET /vehicles excludes vehicles with disabled:true in their config
- total_charge_needed_kwh excludes disabled vehicles
- Internal trigger_refresh calls remain unthrottled (throttle is HTTP-layer only)

## Task Commits

1. **Task 1+2: Poll throttle + disabled filtering** - `83ce8d7` (feat)

## Files Created/Modified
- `evcc-smartload/rootfs/app/web/server.py` - Added _poll_throttle dict, throttle logic in POST handler, disabled filtering in _api_vehicles()

## Decisions Made
- Throttle dict placed on WebServer (not VehicleMonitor) to keep internal trigger_refresh unthrottled
- 300-second hardcoded window — no config needed for this use case
- No threading.Lock — CPython GIL protects single-key dict operations

## Deviations from Plan
None - plan executed exactly as written

## Issues Encountered
None

## Next Phase Readiness
- POST /vehicles/refresh throttle ready for Plan 10-02's Poll Now button
- GET /vehicles disabled filtering ready for Plan 10-02's vehicle card rendering

---
*Phase: 10-poll-now-button-soc-dashboard*
*Completed: 2026-02-27*
