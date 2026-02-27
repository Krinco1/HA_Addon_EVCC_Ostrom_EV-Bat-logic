---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: Smart EV Charging & evcc Control
status: unknown
last_updated: "2026-02-27T17:17:54.478Z"
progress:
  total_phases: 2
  completed_phases: 2
  total_plans: 4
  completed_plans: 4
---

---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: Smart EV Charging & evcc Control
status: unknown
last_updated: "2026-02-27T16:30:40.384Z"
progress:
  total_phases: 1
  completed_phases: 1
  total_plans: 2
  completed_plans: 2
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-27)

**Core value:** The system makes the economically best energy decision at every moment using all available information — and the user understands why
**Current focus:** v1.1 Smart EV Charging & evcc Control

## Current Position

Phase: 9 — Vehicle SoC Provider Fix
Plan: 02 complete — phase done
Status: Complete — 2/2 plans complete
Last activity: 2026-02-27 — 09-02 complete: KiaProvider/RenaultProvider fixes + VehicleMonitor evcc suppression

Progress: [█░░░░░░░░░] 10% — v1.1 (0/4 phases complete, Phase 9 in progress)

## Performance Metrics

**Velocity (v1.0):**
- Total plans completed: 27
- Total execution time: ~0.72 hours
- Timeline: 31 days (2026-01-24 → 2026-02-24)
- Commits: 240

## Accumulated Context

### Decisions

All v1.0 decisions logged in PROJECT.md Key Decisions table with outcomes.
Full decision history preserved in `milestones/v1.0-ROADMAP.md` phase summaries.

New v1.1 decisions:
- SmartLoad leads evcc charge modes; manual evcc overrides apply until session ends (EV disconnects or target SoC reached)
- v1.1 Functional / v2.0 UI split — deliver working mode control and arbitrage before any dashboard redesign
- Phase 11 (mode control) and override detection ship as one atomic deploy — never split
- Phase 12 (arbitrage) waits 1-2 weeks of Phase 11 production stability before activation
- [09-01] STALE_THRESHOLD_MINUTES set to 720 (12h) — 60min was too aggressive given provider poll intervals
- [09-01] last_successful_poll set only in update_from_api (API success); update_from_evcc does not set it — intentional distinction
- [09-01] LP planner uses last-known SoC when stale with warning log, never blocks charging decisions
- [09-01] Telegram silent failure fixed: getMe check before poll loop start, invalid tokens caught at startup with error-level log
- [09-02] KiaProvider: persistent VehicleManager (no 2h re-init), progressive backoff 2h->24h cap, RateLimitingError caught specifically
- [09-02] RenaultProvider: persistent aiohttp session + RenaultClient, 401 retry once, asyncio.run() replaced with persistent loop
- [09-02] VehicleMonitor evcc-live suppression: API poll skipped when vehicle connected_to_wallbox (evcc provides live SoC)
- [09-02] Per-vehicle poll_interval_minutes overrides global default; disabled flag excludes vehicle from polling entirely

### Pending Todos

- Brief codebase verification before Phase 11 implementation: confirm `PlanHorizon`/`DispatchSlot` field names and `loadpoints[0].mode` behavior when EV is disconnected against live evcc instance
- Brief codebase verification before Phase 12 implementation: confirm `PlanHorizon` exposes battery SoC trajectory suitable for 6-hour viability check

### Blockers/Concerns

- RL agent requires 30-day shadow mode observation before advisory mode promotion (started 2026-02-24)
- DynamicBufferCalc requires 14-day observation period before live buffer changes (started 2026-02-24)
- Seasonal dampening (50% + 0.05 cap) should be revisited after 3+ months of data
- Vehicle SoC API providers (Kia, Renault) not delivering data reliably — root cause identified, fixed in Phase 9

## Session Continuity

Last session: 2026-02-27
Stopped at: Phase 10 context gathered — all implementation decisions captured
Resume file: .planning/phases/10-poll-now-button-soc-dashboard/10-CONTEXT.md
Next: `/gsd:plan-phase 10`
