# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-22)

**Core value:** The system makes the economically best energy decision at every moment using all available information — and the user understands why
**Current focus:** Phase 8.1 (Seasonal Feedback Verification) — ALL PLANS COMPLETE (08.1-01)

## Current Position

Phase: 8.1 of 8.1 (Seasonal Feedback Verification)
Plan: 1 of 1 in current phase — 08.1-01 complete (Seasonal LP wiring + Phase 5 VERIFICATION.md)
Status: ALL PHASE 8.1 PLANS COMPLETE — LERN-02 closed (seasonal corrections flow into LP); PLAN-03 closed (Phase 5 VERIFICATION.md with 15 truths, 6 artifacts, 7 links all PASS); v1.0 audit fully satisfied
Last activity: 2026-02-24 — Phase 8.1 Plan 01 executed (8e95188)

Progress: [██████████] 100%

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

| Phase 08 P01 | 1 | 5 min | 5 min |
| Phase 08 P02 | 1 | 2 min | 2 min |

**Recent Trend:**
- Last 5 plans: 4 min, 3 min, 4 min, 4 min, 2 min
- Trend: stable
| Phase 08-residual-rl-and-learning P08-03 | 6 | 2 tasks | 4 files |
| Phase 08 P04 | 3 | 2 tasks | 3 files |
| Phase 08-residual-rl-and-learning P05 | 1 | 1 tasks | 1 files |
| Phase 08.1 P01 | 5 | 2 tasks | 3 files |

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
- [Phase 08-01]: ResidualRLAgent outputs signed ct/kWh delta corrections on LP thresholds (never full actions) — agent cannot conflict with LP safety guarantees
- [Phase 08-01]: model_version=2 field is primary migration guard; old DQNAgent Q-tables (version 1 or missing) reset cleanly
- [Phase 08-01]: compare_residual() uses slot-0 energy cost only — NOT plan.solver_fun (which is full 24h LP objective); docstring warning added
- [Phase 08-01]: Comparator persistence version=2; old v1 format loads with graceful fallback (residual entries reset, legacy compare() data preserved)
- [Phase 08-02]: MONTH_TO_SEASON explicit dict avoids naive (month-1)//3 bug that maps December to season 3 (autumn)
- [Phase 08-02]: ForecastReliabilityTracker PV reference scale is 5.0 kW; callers must convert state.pv_power (W) to kW
- [Phase 08-02]: SeasonalLearner: no decay (simple running average) — decay deferred to Phase 9 per research recommendation
- [Phase 08-03]: ReactionTimingTracker EMA initial value = 0.5, wait_threshold = 0.6 — system defaults to re-planning until it learns deviations self-correct; conservative start
- [Phase 08-03]: confidence_factors applied only to PV surplus in LP objective (not price coefficients) — per research Open Question 1; price confidence flows through DynamicBufferCalc
- [Phase 08-03]: pv_reliability_factor multiplied on existing pv_confidence before _compute_target(); effective_confidence = pv_confidence * pv_reliability_factor
- [Phase 08-03]: RL bootstrap removed from main.py; ResidualRLAgent self-loads via __init__.load() and the old imitation bootstrap was DQNAgent-specific
- [Phase 08-03]: _action_to_str() returns compound "bat_X/ev_Y" string for ReactionTimingTracker; richer signal than battery-only
- [Phase 08-04]: ausstehend displayed for None metrics when insufficient data — not 0 or NaN (Pitfall 7)
- [Phase 08-04]: Lernen tab lazy-loaded on switchTab activation, SSE refreshes only when tab visible
- [Phase 08-05]: check.name preferred over auditLabels[ci] as display label — server provides German label directly; auditLabels kept as fallback
- [Phase 08-05]: data.audit.all_passed used directly instead of computing allPassed in JS — server already aggregates
- [Phase 08-05]: check.detail exposed as title attribute for hover tooltip — zero layout cost, useful for diagnosis
- [Phase 08.1]: 50% dampening + 0.05 EUR/kWh cap applied to SeasonalLearner corrections before LP injection (conservative per user decision)
- [Phase 08.1]: Seasonal correction applied to normal-cost else branches only; penalty slots (price*10.0) and discharge slots unchanged

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 5]: DynamicBufferCalc formula coefficients (spread_bonus 0.3, pv_reduction 2.0) are design estimates — plan 2-4 week observation period before enabling live buffer changes
- [Phase 8]: RL constraint audit required before promoting from shadow to advisory — 30-day minimum shadow period; SeasonalLearner needs months for statistically meaningful cells

## Session Continuity

Last session: 2026-02-24
Stopped at: Completed 08.1-01-PLAN.md — LERN-02 (seasonal correction wired into LP objective) and PLAN-03 (Phase 5 VERIFICATION.md) both closed
Resume file: .planning/phases/08.1-seasonal-feedback-verification/08.1-01-SUMMARY.md
Next: All plans complete — project v1.0 audit fully satisfied (21/21 requirements); ready for deployment and 30-day shadow period observation
