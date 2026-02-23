# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-22)

**Core value:** The system makes the economically best energy decision at every moment using all available information — and the user understands why
**Current focus:** Phase 4.3 (Release Documentation) or Phase 5 (Dynamic Buffer) — next unstarted phases

## Current Position

Phase: 4.3 of 8 (Release Documentation) — Complete
Plan: 1 of 1 in current phase
Status: Phase 4.3 complete (CHANGELOG v5.1.0/v5.2.0/v6.0.0 + README v6.0 with LP architecture, API table, config fields). Next: Phase 5 (Dynamic Buffer).
Last activity: 2026-02-23 — Release documentation updated (cbe9ef3, 076fab3)

Progress: [███████░░░] 62%

## Performance Metrics

**Velocity:**
- Total plans completed: 9
- Average duration: 3.0 min
- Total execution time: 0.45 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| Phase 1 | 2 | 12 min | 6 min |
| Phase 2 | 2 | 7 min | 3.5 min |
| Phase 3 | 3 (of 3) | 7 min | 2.3 min |
| Phase 4 | 3 (of 3) | 12 min | 4 min |
| Phase 04.1 | 1 | 5 min | 5 min |
| Phase 04.2 | 1 | 2 min | 2 min |
| Phase 04.3 | 1 | 3 min | 3 min |

**Recent Trend:**
- Last 5 plans: 5 min, 2 min, 5 min, 2 min, 3 min
- Trend: stable ~2-5 min per plan

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 04.2 Strategy Change]: GHCR pre-built image approach abandoned (2026-02-23) — HA Supervisor pulled pre-built images instead of building locally; reverted to standard model where Supervisor builds from Dockerfile on device. CI kept as test-only (`--test` flag).
- [Phase 04.2-01]: Pin home-assistant/builder to 2025.09.0 to preserve armv7 + --all flag support
- [Phase 04.1-01]: Version bumped to 6.0.0 reflecting LP Horizon Planner and PV forecasting capabilities
- [Phase 04.1-01]: config.yaml ends up with 35 fields total (original 27 + 8 new LP planner fields)
- [Phase 04.3-01]: CHANGELOG entries written in German matching existing style; v5.1/v5.2 used as intermediate milestone markers for Phase 1-4 work
- [Phase 04.3-01]: README architecture diagram uses ASCII art consistent with v5.0 style, extended to show StateStore -> SSE -> Dashboard flow

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 5]: DynamicBufferCalc formula coefficients (spread_bonus 0.3, pv_reduction 2.0) are design estimates — plan 2-4 week observation period before enabling live buffer changes
- [Phase 8]: RL constraint audit required before promoting from shadow to advisory — 30-day minimum shadow period; SeasonalLearner needs months for statistically meaningful cells

## Session Continuity

Last session: 2026-02-23
Stopped at: Completed 04.3-01-PLAN.md — CHANGELOG and README updated to v6.0.0 with full Phase 1-4 documentation.
Next: Phase 5 (Dynamic Buffer) — independent of release docs
