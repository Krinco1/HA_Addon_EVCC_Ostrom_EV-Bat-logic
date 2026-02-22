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
- [ ] **Phase 3: Data Foundation** - Consumption history forecasting from HA/InfluxDB and PV generation estimates from evcc solar tariff integrated into planning inputs
- [ ] **Phase 4: Predictive Planner** - Rolling-horizon 24-48h LP optimizer replaces static euro price limits with joint battery and EV dispatch planning
- [ ] **Phase 5: Dynamic Buffer** - Situational minimum battery SoC adapts based on PV forecast confidence, price spread, and time of day
- [ ] **Phase 6: Decision Transparency** - Dashboard shows 24-48h plan timeline, per-slot decision explanations, and planned-vs-actual historical comparison
- [ ] **Phase 7: Driver Interaction** - Manual override from dashboard and Telegram, proactive departure-time queries, and driver-context-aware multi-EV prioritization
- [ ] **Phase 8: Residual RL and Learning** - RL agent refactored to delta corrections on planner output, seasonal learner deployed, forecast calibration with confidence factors, RL vs planner comparison in dashboard

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
**Plans**: TBD

Plans:
- [ ] 03-01: Implement ConsumptionForecaster: pull HA/InfluxDB 15-min consumption history, build rolling hour-of-day average model, expose per-slot forecast with confidence flag
- [ ] 03-02: Integrate evcc solar tariff API into PV forecast pipeline; handle partial forecasts with confidence reduction; wire both forecasts into StateStore

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
**Plans**: TBD

Plans:
- [ ] 04-01: Implement HorizonPlanner: scipy linprog LP formulation for joint battery + EV 96-slot scheduling; rolling-horizon MPC loop; fallback to holistic optimizer on failure
- [ ] 04-02: Integrate departure times into LP formulation; replace static euro price limit config paths with planner output; update StateStore.update_plan()
- [ ] 04-03: End-to-end integration test: inject price spike mid-sequence, confirm next cycle plan updates; confirm fallback activates on deliberate solver failure

### Phase 5: Dynamic Buffer
**Goal**: The battery minimum SoC adapts situationally — higher when PV forecast confidence is low or prices are flat, lower when cheap solar is reliably incoming
**Depends on**: Phase 4
**Requirements**: PLAN-03
**Success Criteria** (what must be TRUE):
  1. The battery minimum SoC threshold changes across the day based on PV forecast confidence: when forecast confidence is HIGH and cheap solar is expected within 4h, the buffer can be lowered (floor: 10%); when confidence is LOW or no solar is expected, the buffer stays at the configured safe minimum
  2. Every buffer adjustment is logged to the dashboard with the specific inputs that drove it (confidence level, price spread, time of day, expected PV), so the user can audit and understand every change
  3. The buffer never drops below a hard 10% floor regardless of forecast or price signals
  4. During the first 2 weeks after deployment, the DynamicBufferCalc runs in observation mode (logging what it would do) rather than actively changing the buffer, allowing calibration before live use
**Plans**: TBD

Plans:
- [ ] 05-01: Implement DynamicBufferCalc: formula with spread_bonus, pv_reduction, confidence gate, hard 10% floor; observation mode for first 2 weeks; log every event with full inputs

### Phase 6: Decision Transparency
**Goal**: Users can see the full 24-48h plan in the dashboard, understand why each slot was chosen, and compare what was planned against what actually happened
**Depends on**: Phase 4
**Requirements**: TRAN-01, TRAN-02, TRAN-04
**Success Criteria** (what must be TRUE):
  1. The dashboard has a plan timeline tab showing the next 24-48h as a Gantt-style chart with price overlay and colored bars for planned battery charge, battery discharge, and EV charge windows
  2. Clicking (or hovering on) any plan slot shows a human-readable explanation: "Charging Kia now because price is in the bottom 20% of forecast and departure is in 6h — waiting would cost an estimated 1.40 EUR more"
  3. A second dashboard tab shows a historical comparison: for each past decision cycle, what the plan said would happen vs what the optimizer actually did vs what evcc reported as the outcome
  4. Explanations are generated from the LP dual variables and slot context — they reference actual numbers (price rank, hours to departure, cost delta), not generic phrases
**Plans**: TBD

Plans:
- [ ] 06-01: Implement plan timeline visualization: plotly Gantt chart with price overlay embedded in dashboard via fig.to_json(); progressive disclosure (next 6h default, zoom to 24h/48h)
- [ ] 06-02: Implement per-slot decision explanation generator: extract LP dual variables and slot context, format human-readable "why" text per DispatchSlot, store in PlanHorizon
- [ ] 06-03: Implement planned-vs-actual comparison tab: store plan snapshots in InfluxDB per cycle, compare against actual evcc outcomes, render comparison table in dashboard

### Phase 7: Driver Interaction
**Goal**: Drivers can always override the plan immediately, the system proactively asks about departure times via Telegram, and multi-EV priority reflects actual driver needs rather than just SoC ranking
**Depends on**: Phase 4
**Requirements**: DRIV-01, DRIV-02, DRIV-03
**Success Criteria** (what must be TRUE):
  1. A "Boost Charge" button on the dashboard and a Telegram command both trigger an immediate manual override that starts charging the target vehicle regardless of the current plan; the override shows in the plan timeline as a manual intervention marker
  2. When a vehicle is plugged in, the system sends a Telegram message to the driver within one decision cycle asking "Wann brauchst du den [vehicle name]?" with a 30-minute reply window; if no reply arrives, the system falls back to the configured default departure time
  3. When two vehicles are waiting to charge, the sequencer prioritizes based on urgency (time to departure vs SoC deficit) rather than SoC alone — a vehicle departing in 2h with 50% SoC takes priority over one departing in 12h with 40% SoC
  4. All overrides expire after 90 minutes maximum; after expiry the planner resumes control and the driver is notified via Telegram
**Plans**: TBD

Plans:
- [ ] 07-01: Implement manual override: dashboard boost button + Telegram command; override marker in plan timeline; 90-minute expiry with Telegram notification
- [ ] 07-02: Implement proactive departure-time Telegram query: trigger on vehicle plug-in event, 30-min reply window, fallback to config default, feed departure time into HorizonPlanner
- [ ] 07-03: Refactor multi-EV prioritization: urgency scoring (SoC deficit / hours to departure); replace SoC-only ranking in ChargeSequencer

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
**Plans**: TBD

Plans:
- [ ] 08-01: Refactor ResidualRLAgent: change from full action selection to delta corrections (+/-20 ct clip); implement stratified replay buffer (retain samples from all four seasons); reward = plan_cost - actual_cost
- [ ] 08-02: Implement SeasonalLearner: 48-cell lookup table with decay, sample counts, and plan-error accumulation; deploy immediately at Phase 8 start for data accumulation
- [ ] 08-03: Implement forecast reliability tracker: per-source (PV, consumption, price) rolling accuracy measurement; apply confidence factors in HorizonPlanner and DynamicBufferCalc
- [ ] 08-04: Implement adaptive reaction timing: track which deviations from plan self-corrected vs required intervention; learn threshold for "wait" vs "re-plan now"
- [ ] 08-05: Implement RL dashboard widget: win-rate, cost delta, cumulative savings; 30-day shadow mode gate; structured constraint audit checklist before advisory promotion

## Progress

**Execution Order:**
Phases execute in dependency order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8
Note: Phase 3 can begin in parallel with Phase 2 (both depend only on Phase 1).
Note: Phases 5, 6, and 7 can begin in parallel (all depend on Phase 4).

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. State Infrastructure | 2/2 | Complete    | 2026-02-22 |
| 2. Vehicle Reliability | 2/2 | Complete    | 2026-02-22 |
| 3. Data Foundation | 0/2 | Not started | - |
| 4. Predictive Planner | 0/3 | Not started | - |
| 5. Dynamic Buffer | 0/1 | Not started | - |
| 6. Decision Transparency | 0/3 | Not started | - |
| 7. Driver Interaction | 0/3 | Not started | - |
| 8. Residual RL and Learning | 0/5 | Not started | - |
