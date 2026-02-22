# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-22)

**Core value:** The system makes the economically best energy decision at every moment using all available information — and the user understands why
**Current focus:** Phase 1 — State Infrastructure

## Current Position

Phase: 1 of 8 (State Infrastructure)
Plan: 2 of 2 in current phase
Status: Phase complete
Last activity: 2026-02-22 — Completed plan 01-02: Config validation with fail-fast startup and error page

Progress: [██░░░░░░░░] 13%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: 6 min
- Total execution time: 0.2 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| Phase 1 | 2 | 12 min | 6 min |

**Recent Trend:**
- Last 5 plans: 8 min, 4 min
- Trend: improving

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Research]: scipy/HiGHS via apk (musl-safe), plotly via pip (pure Python), numpy micro-MLP — no PyTorch/TensorFlow (glibc incompatibility on Alpine)
- [Research]: RL agent changes from full action selection to delta corrections (±20 ct clip) — residual learning on planner output, not end-to-end
- [Research]: StateStore (RLock-guarded) replaces ad-hoc module-level globals — web server becomes strictly read-only
- [Research]: DynamicBufferCalc runs in observation mode first 2 weeks before going live — coefficients need empirical tuning
- [Research]: SeasonalLearner deployed at Phase 8 start (not end) — needs months of data accumulation, earlier is better
- [Research]: PV forecast comes from evcc solar tariff API (price signal), not kWh — planner must handle partial forecasts with confidence reduction
- [01-01]: RLock (not Lock) guards StateStore to prevent deadlock if nested calls occur
- [01-01]: SSE broadcast happens outside the RLock to avoid I/O while holding the state lock
- [01-01]: ThreadedHTTPServer with daemon_threads=True enables concurrent SSE + API requests without blocking
- [01-01]: Existing 60s polling preserved in app.js as fallback; SSE is an enhancement layer
- [01-02]: WebServer started before EvccClient/InfluxDB construction so error page is reachable even on critical config errors
- [01-02]: WebServer component attributes populated via late-binding after init rather than second server instance — avoids port conflict
- [01-02]: ConfigValidator uses hasattr() on all field accesses for forward compatibility with future Config shape changes
- [01-02]: Non-critical safe defaults applied before I/O objects are created so downstream components see corrected values

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 2]: SoC staleness and sequencer bugs are P1 blockers — Phase 4 planner output is only as reliable as its input state; these must be fully fixed before Phase 4 can be trusted
- [Phase 5]: DynamicBufferCalc formula coefficients (spread_bonus 0.3, pv_reduction 2.0) are design estimates — plan 2-4 week observation period before enabling live buffer changes
- [Phase 8]: RL constraint audit required before promoting from shadow to advisory — 30-day minimum shadow period; SeasonalLearner needs months for statistically meaningful cells
- [Research gap]: PV forecast from evcc solar tariff is a price signal, not kWh generation — resolution needed in Phase 3 planning (Forecast.Solar API integration vs InfluxDB irradiance history)
- [Research gap]: evcc sometimes returns partial forecasts (6h/12h vs 24h) — HorizonPlanner must handle gracefully; frequency of this in German dynamic tariff context (Tibber/aWATTar) unvalidated

## Session Continuity

Last session: 2026-02-22
Stopped at: Completed 01-02-PLAN.md — Config validation with fail-fast startup and error page
Resume file: .planning/phases/02-soc-sequencer-fixes/ (Phase 2, Plan 1)
