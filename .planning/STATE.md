# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-22)

**Core value:** The system makes the economically best energy decision at every moment using all available information — and the user understands why
**Current focus:** Phase 7 (Driver Interaction) — all 3 plans complete, ready for Phase 8

## Current Position

Phase: 7 of 8 (Driver Interaction)
Plan: 3 of 3 in current phase — 07-03 complete (Urgency-Based Vehicle Ranking)
Status: Urgency scoring (SoC deficit / hours to departure); dashboard urgency cards with Dringlichkeit label and priority badges; departure_store injected into sequencer (17d4211)
Last activity: 2026-02-23 — Phase 7 Plan 03 executed (17d4211)

Progress: [██████████] 98%

## Performance Metrics

**Velocity:**
- Total plans completed: 11
- Average duration: 3.9 min
- Total execution time: 0.72 hours

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
| Phase 05 P01 | 1 | 12 min | 12 min |
| Phase 05 P02 | 1 | 4 min | 4 min |
| Phase 06 P01 | 1 | 5 min | 5 min |
| Phase 06 P02 | 1 | 8 min | 8 min |
| Phase 06 P03 | 1 | 4 min | 4 min |
| Phase 07 P01 | 1 | 4 min | 4 min |
| Phase 07 P02 | 1 | 4 min | 4 min |
| Phase 07 P03 | 1 | 3 min | 3 min |

**Recent Trend:**
- Last 5 plans: 4 min, 5 min, 8 min, 4 min, 4 min
- Trend: stable

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
- [Phase 05-01]: Conservative formula: practical minimum 20% even at highest confidence, hard floor 10%
- [Phase 05-01]: bat-to-EV takes precedence: buffer_calc.step() skipped when controller._bat_to_ev_active is True
- [Phase 05-01]: 5% rounding hysteresis applied to target buffer to prevent oscillation between cycles
- [Phase 05-02]: buffer_calc injected via late attribute assignment (web.buffer_calc = buffer_calc) — consistent with all other components; WebServer started early before buffer_calc is created
- [Phase 05-02]: SVG chart uses two polylines (obs=dashed/50% opacity, live=solid) for visual mode distinction
- [Phase 05-02]: confirm() dialog before activateBufferLive() to prevent accidental live activation
- [Phase 06-01]: Cost delta uses price-comparison approximation (current slot vs cheapest future slot), prefixed "ca." per user convention — not LP dual variables
- [Phase 06-01]: switchTab() defined as inline fallback in dashboard.html with 'if typeof === undefined' guard — app.js overrides in Plan 02 with full implementation
- [Phase 06]: Transparent hit-area rects for hold/idle slots ensure all 96 slots respond to hover/click in Gantt chart
- [Phase 06]: renderPlanGantt() uses SVG string-concatenation pattern matching renderChart()/renderForecastChart() — lazy-loaded by switchTab('plan')
- [Phase 06-03]: PlanSnapshotter uses direct requests.get() (not InfluxDBClient query helpers) for smartload_plan_snapshot — cleaner column parsing for new measurement
- [Phase 06-03]: query_comparison() converts actual_bat_power_w to kW server-side (returns actual_bat_power_kw) — consistent kW units with planned fields in JS
- [Phase 06-03]: cost_delta_eur approximation: (actual_price_ct - planned_price_ct) / 100 * planned_bat_charge_kw * 0.25 — 15-min slot energy cost difference
- [Phase 07-01]: last-activated-wins for Boost override — no explicit cancel required when switching vehicles
- [Phase 07-01]: cancel() does NOT call evcc — main loop restores LP-controlled mode on next cycle (avoids double-write)
- [Phase 07-01]: override_manager injected as late attribute (same pattern as buffer_calc, sequencer, plan_snapshotter)
- [Phase 07-02]: morgen frueh (frueh variant) accepted by regex — handles German ASCII umlaut substitution
- [Phase 07-02]: departure_store injected as late attribute into notifier and web server; _get_departure_times() extended with departure_store + state params
- [Phase 07-02]: plug-in detection defers last_ev_connected update until ev_name known — avoids false-negative when evcc slow to resolve vehicle name
- [Phase 07-03]: get_requests_summary() return type changed to list (each entry has 'vehicle' key) — fixes pre-existing JS array/dict mismatch
- [Phase 07-03]: Past departure times treated as 12h default window (no urgency inflation for expired entries)
- [Phase 07-03]: Connected vehicle tie-break +5.0; quiet hours absolute priority +1000.0 preserved
- [Phase 07-03]: urgency color thresholds: red >= 10, amber >= 3, blue < 3

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 5]: DynamicBufferCalc formula coefficients (spread_bonus 0.3, pv_reduction 2.0) are design estimates — plan 2-4 week observation period before enabling live buffer changes
- [Phase 8]: RL constraint audit required before promoting from shadow to advisory — 30-day minimum shadow period; SeasonalLearner needs months for statistically meaningful cells

## Session Continuity

Last session: 2026-02-23
Stopped at: Completed 07-03-PLAN.md — Urgency-Based Vehicle Ranking implemented
Resume file: .planning/phases/07-driver-interaction/07-03-SUMMARY.md
Next: Execute Phase 8 (RL Advisory)
