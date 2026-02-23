# Roadmap: SmartLoad v6

## Overview

SmartLoad v6 transforms a reliable reactive optimizer into a proactive 24-48h predictive energy management system. The journey moves in dependency order: fix the data foundation first (reliable vehicle state, thread-safe infrastructure), then build the predictive planner on top of clean data, then add driver interaction and transparency so users trust the system, and finally promote the RL agent from shadow mode to active residual corrector once the planner is proven. Every phase delivers a verifiable, independently runnable capability — no phase produces work-in-progress that only makes sense at the end.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: State Infrastructure** - Thread-safe StateStore and startup config validation eliminate race conditions and misconfiguration crashes
- [x] **Phase 2: Vehicle Reliability** - Accurate live vehicle SoC, immediate charge sequencer transitions, and bounded RL bootstrap memory
- [x] **Phase 3: Data Foundation** - Consumption history forecasting from HA/InfluxDB and PV generation estimates from evcc solar tariff integrated into planning inputs (completed 2026-02-22)
- [x] **Phase 4: Predictive Planner** - Rolling-horizon 24-48h LP optimizer replaces static euro price limits with joint battery and EV dispatch planning (completed 2026-02-22)
- [x] **Phase 4.1: Deploy Configuration** - Version bump to 6.0.0, config.yaml schema completion, repository.yaml channel field (INSERTED — gap closure) (completed 2026-02-22)
- [x] **Phase 4.2: CI/CD Pipeline** - GitHub Actions multi-arch container build and push to GHCR (INSERTED — gap closure) (completed 2026-02-22)
- [x] **Phase 4.3: Release Documentation** - CHANGELOG.md and README.md updated for Phases 1-4 features (INSERTED — gap closure) (completed 2026-02-23)
- [x] **Phase 5: Dynamic Buffer** - Situational minimum battery SoC adapts based on PV forecast confidence, price spread, and time of day (completed 2026-02-23)
- [x] **Phase 6: Decision Transparency** - Dashboard shows 24-48h plan timeline, per-slot decision explanations, and planned-vs-actual historical comparison (completed 2026-02-23)
- [x] **Phase 7: Driver Interaction** - Manual override from dashboard and Telegram, proactive departure-time queries, and driver-context-aware multi-EV prioritization (completed 2026-02-23)
- [x] **Phase 8: Residual RL and Learning** - RL agent refactored to delta corrections on planner output, seasonal learner deployed, forecast calibration with confidence factors, RL vs planner comparison in dashboard (completed 2026-02-23)

## Phase Details

### Phase 1: State Infrastructure
**Goal**: The system runs without thread-safety failures and rejects invalid configuration at startup before any damage is done
**Depends on**: Nothing (first phase)
**Requirements**: RELI-03, RELI-04
**Success Criteria** (what must be TRUE):
  1. Under concurrent load (web request + decision loop + vehicle polling all running simultaneously), the dashboard never shows corrupted or partially-updated state
  2. If a user provides an invalid configuration value (e.g., min_soc > max_soc, missing required key, out-of-range percentage), the add-on refuses to start and logs a human-readable error explaining exactly which field is wrong and what the valid range is
  3. All state writes from DataCollector and vehicle monitors go through a single RLock-guarded StateStore; the web server only reads, never writes
  4. Config validation runs before any network connection is attempted, so the add-on fails fast rather than partially initializing
**Plans**: 2 plans

Plans:
- [x] 01-01-PLAN.md — Thread-safe StateStore with RLock, SSE push, and web server migration to read-only
- [x] 01-02-PLAN.md — Config validation with critical/non-critical classification and startup error page

### Phase 2: Vehicle Reliability
**Goal**: Vehicle SoC is always current and correct, charge transitions happen within one decision cycle, and the RL bootstrap does not exhaust memory on Raspberry Pi
**Depends on**: Phase 1
**Requirements**: RELI-01, RELI-02, RELI-05
**Success Criteria** (what must be TRUE):
  1. When a vehicle is connected to the wallbox and actively charging, the dashboard shows the correct current SoC (not a stale value from the last API poll before connection)
  2. When a vehicle finishes charging and a second vehicle is waiting, the charge sequencer switches to the second vehicle within one decision cycle (under 5 minutes), not up to 15 minutes later
  3. On a Raspberry Pi with limited RAM, the add-on starts in under 3 minutes and uses less than 256 MB peak memory during RL bootstrap, regardless of how many months of InfluxDB history exist
  4. The RL bootstrap logs progress (e.g., "Loading history: 847/1000 records") so the user knows startup is not frozen
**Plans**: 2 plans

Plans:
- [x] 02-01-PLAN.md — Connection-event SoC refresh and sequencer SoC sync in decision loop
- [x] 02-02-PLAN.md — RL bootstrap with record cap, progress logging, and price field fix

### Phase 3: Data Foundation
**Goal**: The planner has accurate house consumption forecasts and PV generation estimates to plan against, sourced from real historical data
**Depends on**: Phase 1
**Requirements**: PLAN-04, PLAN-05
**Success Criteria** (what must be TRUE):
  1. When the planner requests a consumption forecast for the next 24h, it receives per-slot (15-min) estimated house load values derived from HA database or InfluxDB history — not fixed defaults
  2. PV generation estimates for the next 24h are available to the planner by reading the evcc solar tariff API; when the API returns partial data (less than 24h), the planner notes reduced forecast confidence
  3. ConsumptionForecaster exposes rolling hour-of-day averages that update incrementally as new data arrives — no full refit required each cycle
  4. If InfluxDB history is under 2 weeks old, the system falls back to sensible defaults and logs that forecast accuracy will improve as history accumulates
**Plans**: 3 plans

Plans:
- [x] 03-01-PLAN.md — ConsumptionForecaster with tiered InfluxDB aggregation, HA entity discovery, and persistent versioned model
- [x] 03-02-PLAN.md — PVForecaster with evcc solar tariff integration, correction coefficient, and partial forecast handling
- [x] 03-03-PLAN.md — Wire forecasters into main loop, extend StateStore, dashboard 24h SVG forecast chart with SSE

### Phase 4: Predictive Planner
**Goal**: A rolling-horizon LP optimizer produces a 24-48h joint battery and EV dispatch plan every decision cycle, replacing all static euro price limits
**Depends on**: Phase 2, Phase 3
**Requirements**: PLAN-01, PLAN-02
**Success Criteria** (what must be TRUE):
  1. Every 15-minute decision cycle, the system produces a fresh PlanHorizon covering the next 24-48h with per-slot (15-min) dispatch decisions for battery charging, battery discharging, and EV charging
  2. The static configuration parameters `ev_max_price_ct` and `battery_max_price_ct` are no longer used to gate charging decisions; instead, all grid-charging decisions come from the LP plan
  3. When real-world conditions diverge mid-cycle (price spike, unexpected cloud cover), the next cycle's plan reflects the updated inputs — old plans are never cached for re-use
  4. If the LP solver fails or times out, the system falls back to the existing holistic optimizer and logs a warning — the add-on never crashes due to a planner failure
  5. A per-EV departure time (from config or driver input) is factored into the plan so urgency windows are sized correctly: a vehicle departing in 2h gets priority over one departing in 12h
**Plans**: 3 plans

Plans:
- [x] 04-01-PLAN.md — Core LP engine: scipy/HiGHS LP formulation, PlanHorizon/DispatchSlot dataclasses, HorizonPlanner with 96-slot joint battery+EV optimization
- [x] 04-02-PLAN.md — Main loop integration: wire HorizonPlanner into decision loop, replace static price limit gating with LP-derived actions, StateStore plan storage, departure time resolution
- [x] 04-03-PLAN.md — Integration tests (TDD): verify price-responsive behavior, solver failure fallback, no-EV case, departure urgency, SoC bounds compliance

### Phase 4.1: Deploy Configuration (INSERTED — Gap Closure)
**Goal**: Version, config schema, and repository metadata are correct and complete for HA add-on deployment
**Depends on**: Phase 4
**Gap Closure**: Closes DEPLOY-02, DEPLOY-03, DEPLOY-05 from v1.0 audit
**Success Criteria** (what must be TRUE):
  1. `version.py` and `config.yaml` both declare version `6.0.0`
  2. All LP planner config fields (battery_charge_power_kw, battery_min/max_soc, feed_in_tariff_ct, ev_default_energy_kwh, sequencer_enabled, sequencer_default_charge_power_kw, rl_bootstrap_max_records) are exposed in config.yaml options and schema sections
  3. `repository.yaml` includes `channel: stable`
**Plans**: 1 plan

Plans:
- [x] 04.1-01-PLAN.md — Version bump to 6.0.0, config.yaml schema completion (8 LP planner fields), repository.yaml channel, translations (completed 2026-02-22)

### Phase 4.2: CI/CD Pipeline (INSERTED — Gap Closure)
**Goal**: GitHub Actions validates Dockerfile builds on every push/PR; HA Supervisor builds locally from Dockerfile (standard add-on distribution)
**Depends on**: Phase 4.1
**Gap Closure**: Partial DEPLOY-01 — CI test validation in place; distribution via local Dockerfile build (no GHCR pre-built images)
**Strategy Change (2026-02-23)**: GHCR pre-built image approach abandoned — HA Supervisor was pulling pre-built images instead of building locally. Reverted to standard HA add-on model where Supervisor builds from Dockerfile on device.
**Success Criteria** (what must be TRUE):
  1. A GitHub Actions workflow validates Dockerfile builds on push/PR using `--test` flag
  2. No `image:` key in config.yaml — Supervisor builds locally from Dockerfile
  3. CI catches Dockerfile build errors before they reach users
**Plans**: 1 plan

Plans:
- [x] 04.2-01-PLAN.md — CI test workflow with home-assistant/builder@2025.09.0 (GHCR approach abandoned, test-only retained) (completed 2026-02-23)

### Phase 4.3: Release Documentation (INSERTED — Gap Closure)
**Goal**: CHANGELOG.md and README.md accurately describe all Phases 1-4 features, APIs, and architecture
**Depends on**: Phase 4.1
**Gap Closure**: Closes DEPLOY-04 from v1.0 audit
**Success Criteria** (what must be TRUE):
  1. CHANGELOG.md has entries for v5.1 through v6.0 covering all Phase 1-4 features
  2. README.md architecture section describes StateStore, forecasters, HorizonPlanner, and LP dispatch
  3. README.md API table lists `/forecast`, `/events`, and all other endpoints
**Plans**: 1 plan

Plans:
- [x] 04.3-01-PLAN.md — CHANGELOG.md v5.1-v6.0 entries, README.md architecture and API updates (completed 2026-02-23)

### Phase 5: Dynamic Buffer
**Goal**: The battery minimum SoC adapts situationally — higher when PV forecast confidence is low or prices are flat, lower when cheap solar is reliably incoming
**Depends on**: Phase 4
**Requirements**: PLAN-03
**Success Criteria** (what must be TRUE):
  1. The battery minimum SoC threshold changes across the day based on PV forecast confidence: when forecast confidence is HIGH and cheap solar is expected within 4h, the buffer can be lowered (floor: 10%); when confidence is LOW or no solar is expected, the buffer stays at the configured safe minimum
  2. Every buffer adjustment is logged to the dashboard with the specific inputs that drove it (confidence level, price spread, time of day, expected PV), so the user can audit and understand every change
  3. The buffer never drops below a hard 10% floor regardless of forecast or price signals
  4. During the first 2 weeks after deployment, the DynamicBufferCalc runs in observation mode (logging what it would do) rather than actively changing the buffer, allowing calibration before live use
**Plans**: 2 plans

Plans:
- [ ] 05-01-PLAN.md — DynamicBufferCalc engine with formula, observation mode, persistence; main loop integration; StateStore SSE extension
- [ ] 05-02-PLAN.md — Dashboard UI: confidence widget, observation banner, buffer history chart, event log table, POST API endpoints for mode control

### Phase 6: Decision Transparency
**Goal**: Users can see the full 24-48h plan in the dashboard, understand why each slot was chosen, and compare what was planned against what actually happened
**Depends on**: Phase 4
**Requirements**: TRAN-01, TRAN-02, TRAN-04
**Success Criteria** (what must be TRUE):
  1. The dashboard has a plan timeline tab showing the next 24-48h as a Gantt-style chart with price overlay and colored bars for planned battery charge, battery discharge, and EV charge windows
  2. Clicking (or hovering on) any plan slot shows a human-readable explanation: "Charging Kia now because price is in the bottom 20% of forecast and departure is in 6h — waiting would cost an estimated 1.40 EUR more"
  3. A second dashboard tab shows a historical comparison: for each past decision cycle, what the plan said would happen vs what the optimizer actually did vs what evcc reported as the outcome
  4. Explanations are generated from the LP dual variables and slot context — they reference actual numbers (price rank, hours to departure, cost delta), not generic phrases
**Plans**: 3 plans

Plans:
- [x] 06-01-PLAN.md — ExplanationGenerator class, GET /plan endpoint, 3-tab dashboard navigation (completed 2026-02-23)
- [x] 06-02-PLAN.md — SVG Gantt chart with price overlay, hover tooltips, click-detail explanations (completed 2026-02-23)
- [x] 06-03-PLAN.md — PlanSnapshotter for InfluxDB, GET /history endpoint, Historie tab with overlay chart and cost-deviation table (completed 2026-02-23)

### Phase 7: Driver Interaction
**Goal**: Drivers can always override the plan immediately, the system proactively asks about departure times via Telegram, and multi-EV priority reflects actual driver needs rather than just SoC ranking
**Depends on**: Phase 4
**Requirements**: DRIV-01, DRIV-02, DRIV-03
**Success Criteria** (what must be TRUE):
  1. A "Boost Charge" button on the dashboard and a Telegram command both trigger an immediate manual override that starts charging the target vehicle regardless of the current plan; the override shows in the plan timeline as a manual intervention marker
  2. When a vehicle is plugged in, the system sends a Telegram message to the driver within one decision cycle asking "Wann brauchst du den [vehicle name]?" with a 30-minute reply window; if no reply arrives, the system falls back to the configured default departure time
  3. When two vehicles are waiting to charge, the sequencer prioritizes based on urgency (time to departure vs SoC deficit) rather than SoC alone — a vehicle departing in 2h with 50% SoC takes priority over one departing in 12h with 40% SoC
  4. All overrides expire after 90 minutes maximum; after expiry the planner resumes control and the driver is notified via Telegram
**Plans**: 3 plans

Plans:
- [ ] 07-01-PLAN.md — OverrideManager class, POST /override/boost+cancel endpoints, dashboard Boost button on vehicle cards, Telegram /boost+/stop commands, 90-min expiry, quiet-hours guard, Gantt override marker
- [ ] 07-02-PLAN.md — DepartureTimeStore with JSON persistence, plug-in event detection, Telegram departure inquiry with inline buttons + free-text parsing, 30-min timeout, _get_departure_times() integration
- [ ] 07-03-PLAN.md — Urgency scoring (SoC deficit / hours to departure) in ChargeSequencer._rank_vehicles(), dashboard vehicle card urgency display with German labels

### Phase 8: Residual RL and Learning
**Goal**: The RL agent learns signed delta corrections to the planner's decisions, a seasonal learner accumulates pattern data, forecast accuracy improves through confidence calibration, and the dashboard shows RL performance vs the planner
**Depends on**: Phase 4
**Requirements**: LERN-01, LERN-02, LERN-03, LERN-04, TRAN-03
**Success Criteria** (what must be TRUE):
  1. The RL agent outputs delta corrections (e.g., +15 ct/kWh or -10 ct/kWh) on the planner's battery and EV price thresholds, clipped to +/-20 ct — it never selects full actions independently, and its corrections cannot push battery below min_soc or cause a vehicle to miss its departure target
  2. The SeasonalLearner is live from Phase 8 start, maintaining a 48-cell lookup table (4 seasons x 6 time periods x 2 weekend flags) of average plan errors; each cell exposes its sample count so downstream consumers can weight low-confidence cells appropriately
  3. The system tracks forecast reliability (PV, consumption, price) over time and applies learned confidence factors when these forecasts feed into the planner — a forecast source that is consistently 30% off gets a lower confidence weight than one that is consistently accurate
  4. The dashboard shows a live RL vs planner comparison widget: rolling win-rate (percentage of cycles where RL corrections reduced cost vs plan-only), average cost delta per day, and cumulative savings estimate
  5. The RL agent runs in shadow mode (logging corrections but not applying them) for the first 30 days, and transitions to advisory mode only after a structured constraint audit confirms no shadow corrections would have violated safety constraints
**Plans**: 5 plans

Plans:
- [x] 08-01-PLAN.md — ResidualRLAgent with delta corrections (+/-20ct clip), stratified replay buffer, extended Comparator with slot-0 cost accounting
- [x] 08-02-PLAN.md — SeasonalLearner (48-cell lookup table) and ForecastReliabilityTracker (per-source rolling MAE with confidence factors)
- [x] 08-03-PLAN.md — ReactionTimingTracker, main loop wiring for all learners, shadow mode branching, confidence factors into planner and buffer
- [x] 08-04-PLAN.md — Dashboard "Lernen" tab with German labels, GET /rl-learning and /rl-audit endpoints, constraint audit display
- [ ] 08-05-PLAN.md — Gap closure: fix audit checklist array-vs-dict mismatch in app.js

### Phase 8.1: Seasonal Feedback + Phase 5 Verification (INSERTED — Gap Closure)
**Goal**: SeasonalLearner corrections flow into HorizonPlanner LP objective, and Phase 5 Dynamic Buffer has formal verification
**Depends on**: Phase 8
**Requirements**: LERN-02, PLAN-03
**Gap Closure**: Closes LERN-02 (seasonal feedback loop unwired) and PLAN-03 (missing verification) from v1.0 audit
**Success Criteria** (what must be TRUE):
  1. `SeasonalLearner.get_correction_factor()` is called in main.py and its output is passed to `HorizonPlanner.plan()` as a seasonal cost correction
  2. The LP solver incorporates the seasonal correction when computing dispatch decisions — slots in seasons with historically high plan errors get adjusted cost coefficients
  3. Phase 5 Dynamic Buffer has a VERIFICATION.md confirming all must_haves against the actual codebase
**Plans**: TBD

Plans:
- [ ] 08.1-01: Wire SeasonalLearner.get_correction_factor() into main.py → HorizonPlanner.plan() → _solve_lp() as seasonal cost offset; verify Phase 5 DynamicBufferCalc

## Progress

**Execution Order:**
Phases execute in dependency order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 8.1
Note: Phase 3 can begin in parallel with Phase 2 (both depend only on Phase 1).
Note: Phases 5, 6, and 7 can begin in parallel (all depend on Phase 4).

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. State Infrastructure | 2/2 | Complete    | 2026-02-22 |
| 2. Vehicle Reliability | 2/2 | Complete    | 2026-02-22 |
| 3. Data Foundation | 3/3 | Complete   | 2026-02-22 |
| 4. Predictive Planner | 3/3 | Complete    | 2026-02-22 |
| 4.1 Deploy Configuration | 1/1 | Complete    | 2026-02-22 |
| 4.2 CI/CD Pipeline | 1/1 | Complete (CI test-only, GHCR abandoned) | 2026-02-23 |
| 4.3 Release Documentation | 1/1 | Complete | 2026-02-23 |
| 5. Dynamic Buffer | 2/2 | Complete   | 2026-02-23 |
| 6. Decision Transparency | 2/3 | Complete    | 2026-02-23 |
| 7. Driver Interaction | 3/3 | Complete    | 2026-02-23 |
| 8. Residual RL and Learning | 5/5 | Complete   | 2026-02-23 |
| 8.1 Seasonal Feedback + Phase 5 Verification | 0/1 | Not started | - |
