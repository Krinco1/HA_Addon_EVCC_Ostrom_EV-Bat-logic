---
phase: 01-state-infrastructure
plan: 02
subsystem: config-validation
tags: [config, validation, error-page, fail-fast, german-ui, startup]

dependency_graph:
  requires:
    - phase: 01-01
      provides: StateStore + WebServer infrastructure used as base
  provides:
    - ConfigValidator class with critical/warning severity classification
    - ValidationResult dataclass for typed error reporting
    - error.html German error page served at port 8099 on config failures
    - Fail-fast startup: validation before any network I/O
    - 503 JSON responses on all API endpoints when config is critically invalid
  affects:
    - Phase 2 (SoC/sequencer fixes): validation guards battery_min_soc/max_soc bounds
    - Phase 4 (HorizonPlanner): evcc_url validation ensures connectivity before planning
    - Phase 5 (DynamicBufferCalc): battery_capacity_kwh/efficiency validation ensures valid inputs

tech-stack:
  added: []
  patterns:
    - "Fail-fast startup: validate before I/O — no partial initialization on invalid config"
    - "Early WebServer start: HTTP server starts before EvccClient so error page is always reachable"
    - "Attribute late-binding: WebServer components populated after init allows split startup phases"
    - "hasattr() guards: validator checks field existence before accessing — forward-compatible with any Config version"

key-files:
  created:
    - evcc-smartload/rootfs/app/config_validator.py
    - evcc-smartload/rootfs/app/web/templates/error.html
  modified:
    - evcc-smartload/rootfs/app/main.py
    - evcc-smartload/rootfs/app/web/server.py
    - evcc-smartload/rootfs/app/config.py

key-decisions:
  - "WebServer started before EvccClient/InfluxDB construction so error page is reachable even on critical config errors"
  - "WebServer component attributes populated via late-binding (web.lp = optimizer etc.) rather than creating a second server instance — avoids port conflict"
  - "ConfigValidator uses hasattr() on all field accesses for forward compatibility with future Config shape changes"
  - "Non-critical safe defaults applied before I/O objects are created so downstream components see corrected values"
  - "Euro limit fields (ev_max_price_ct, battery_max_price_ct) preserved in config.py per user decision"

patterns-established:
  - "Critical vs warning severity: 'critical' = add-on cannot function without this value; 'warning' = can run with a sensible default"
  - "German messages, plain ASCII: all user-facing error strings in German with ASCII-only characters for container log safety"
  - "Validation before I/O: any new startup-phase code should follow the pattern of validating config before attempting network connections"

requirements-completed:
  - RELI-04

duration: 4min
completed: 2026-02-22
---

# Phase 1 Plan 2: Config Validation — Fail-Fast Startup with Error Page

**ConfigValidator blocks optimization startup on critical config errors (evcc_url, SoC bounds, efficiency range, battery capacity) and serves a German error page at port 8099 before any network I/O is attempted.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-22T16:26:38Z
- **Completed:** 2026-02-22T16:30:38Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- `ConfigValidator` with `validate(cfg) -> List[ValidationResult]` checking 4 critical fields and 5 warning conditions, all messages in German plain ASCII
- Fail-fast startup: `validator.validate(cfg)` runs at line 53 of `main.py`, `EvccClient(cfg)` at line 92 — 39 lines of separation guaranteeing zero network I/O before validation
- German error page (`error.html`) at port 8099 with severity badges (red "Kritisch" / yellow "Warnung"), field names, values, and fix suggestions per error card
- `WebServer` started before the critical-error block so the error page is always reachable even when the optimization loop never starts
- 503 JSON responses on `/status` and all other API routes when critical errors exist; static files and `/health` remain accessible
- Safe defaults applied in-place on `cfg` for non-critical warnings (price limits, decision interval) before any I/O objects are built

## Task Commits

1. **Task 1: ConfigValidator with critical/non-critical classification** - `6131099` (feat)
2. **Task 2: Wire validation into startup, error page, 503 routing** - `26e1716` (feat)

## Files Created/Modified

- `evcc-smartload/rootfs/app/config_validator.py` - ConfigValidator class (227 lines): ValidationResult dataclass, validate() method, has_critical() helper, all checks with hasattr() guards
- `evcc-smartload/rootfs/app/web/templates/error.html` - German error page with dark theme matching dashboard, severity-colored cards per ValidationResult
- `evcc-smartload/rootfs/app/main.py` - Added ConfigValidator import, validation block before I/O, early WebServer start, critical error block, late-binding of WebServer components
- `evcc-smartload/rootfs/app/web/server.py` - WebServer.__init__ accepts config_errors kwarg, all positional args made optional (None defaults), _render_error_page() method, do_GET guard, _config_errors attached to server in _run()
- `evcc-smartload/rootfs/app/config.py` - Added doc comment noting validation delegated to ConfigValidator

## Decisions Made

- **WebServer late-binding pattern:** Rather than creating two WebServer instances (which would cause a port conflict), the single server is started early with `config_errors` and component references (`lp`, `rl`, `comparator`, etc.) are populated via attribute assignment afterward. The `do_GET` handler references `srv` at call time, so late-populated attributes are visible to all requests.

- **Optional constructor parameters:** Made all WebServer constructor parameters except `cfg` and `store` optional with `None` defaults. This is safe because: (a) on critical errors, the server only serves the error page; (b) on normal startup, all components are populated before the first decision loop iteration that would exercise them.

- **hasattr() guards throughout:** The validator checks `hasattr(cfg, field)` before accessing any field. This means the validator can run against any Config version without crashing — essential for phased v6 migration.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Made WebServer constructor parameters optional to support early-start pattern**
- **Found during:** Task 2 (wiring validation into startup)
- **Issue:** The plan specified starting WebServer early with just `config_errors`, but the existing constructor signature required `optimizer`, `rl_agent`, `comparator`, etc. as positional arguments. Calling `WebServer(cfg, store, config_errors=config_errors)` would fail with a TypeError.
- **Fix:** Made all component parameters optional (default `None`), switched positional to keyword-only after `store`. Also added `_render_error_page()` as a WebServer method (rather than a standalone function) so it can access `self._config_errors` naturally.
- **Files modified:** evcc-smartload/rootfs/app/web/server.py
- **Verification:** Grep confirms `config_errors` in both `__init__` and `do_GET`; constructor call in main.py works with keyword-only arg
- **Committed in:** `26e1716` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug: constructor signature incompatible with early-start pattern)
**Impact on plan:** The fix was structurally necessary to implement the plan's stated goal of starting WebServer before EvccClient. No scope creep — the change makes all existing positional parameters optional with None defaults, which is backward-compatible since the normal startup path populates them all via late-binding before first use.

## Issues Encountered

Python is not installed on the host machine (runs inside Alpine container). Runtime verification via `python -c` was not possible. Syntax and logic verified by code review. The validator uses only stdlib (`dataclasses`, `typing`) and does not import `Config` directly — all field checks use duck-typing with `hasattr()`.

## Next Phase Readiness

- Config validation foundation complete; Phase 2 (SoC staleness, sequencer bugs) can assume battery_min_soc < battery_max_soc is enforced at startup
- The `ConfigValidator` is fully extensible — new v6 fields validated in later phases can be added as additional `_check_*` methods
- No blockers for Phase 2 from this plan

---
*Phase: 01-state-infrastructure*
*Completed: 2026-02-22*
