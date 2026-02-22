# Project Research Summary

**Project:** SmartLoad v6
**Domain:** Home Energy Management System (HEMS) — Predictive Planning + Hybrid Residual RL
**Researched:** 2026-02-22
**Confidence:** MEDIUM-HIGH

## Executive Summary

SmartLoad v6 is a self-hosted Home Assistant add-on that moves from reactive threshold-based energy management to proactive 24-48h predictive optimization. The system already has a solid foundation: evcc integration, multi-EV charge sequencing, a DQN-based RL agent running in shadow mode, an LP optimizer with percentile-based price thresholds, Telegram-based driver interaction, and an InfluxDB time-series backend. The milestone adds a rolling-horizon predictive planner (joint battery + EV optimization over the full price forecast window), promotes RL from shadow mode to residual corrector (learning signed delta corrections on top of plan actions rather than full actions from scratch), and wraps everything in transparent decision visualization. The recommended stack stays entirely within the Alpine Linux/musl/aarch64 environment: scipy via apk for LP solving (HiGHS backend), statsmodels via apk for consumption forecasting, plotly via pip for interactive visualization, and a custom numpy micro-MLP for the residual RL agent — all avoiding the PyTorch/TensorFlow glibc incompatibility.

The key architectural insight is that a deterministic LP planner and a learned residual corrector are stronger together than either alone. The planner handles the global 24-48h optimization that rules-based logic cannot, while RL handles systematic biases the planner cannot model (household consumption anomalies, seasonal calibration drift). The hybrid approach also solves a trust problem: users can read the plan, understand why each slot was chosen, and disable RL corrections independently. The single most important design constraint is that all features must be built on top of a reliable data foundation — stale vehicle SoC and 15-minute sequencer transition delays will corrupt any predictive model that depends on accurate state. These bugs must be fixed before any new planning feature is trusted.

Three risks dominate. First, the planner must be a true rolling-horizon model (re-solving every cycle from the current real state) — a static day-ahead schedule degrades quickly as real-world conditions diverge from predictions. Second, the RL residual output must be hard-clipped to prevent it from overriding the planner's safety constraints even when it would be economically rewarded to do so. Third, the dynamic battery buffer can cause serious under-service if PV forecasts are wrong and the buffer was already lowered to exploit expected solar — it must be gated on forecast confidence from day one, not tuned as a later refinement.

---

## Key Findings

### Recommended Stack

The Alpine Linux constraint eliminates PyTorch, TensorFlow, and OR-Tools — all require glibc. The correct strategy is: install scipy and statsmodels via `apk add py3-scipy py3-statsmodels` (compiled against musl in Alpine's community repo), install plotly via `pip install plotly==6.5.2` (pure Python, zero compatibility issues), and implement the residual RL micro-MLP in numpy (already available). This is not a workaround — it is the right fit for the problem scale. A 96-interval LP (24h at 15-min slots) solves in under 100ms with HiGHS; a SARIMA forecast runs in milliseconds once fitted; a 2-hidden-layer numpy MLP forward-passes in microseconds. The system never needs a heavy ML framework.

**Core technologies:**
- `scipy.optimize.linprog` (HiGHS method) via `apk add py3-scipy`: LP solver for 24-48h dispatch optimization — HiGHS is production-grade, solves 96-slot LP in <100ms on Raspberry Pi, included in Alpine community repo (no musl compilation)
- `statsmodels` SARIMA via `apk add py3-statsmodels`: statistical consumption forecasting — outperforms Prophet on short-horizon structured data, needs only 2-4 weeks of InfluxDB history, Alpine-native
- `plotly==6.5.2` via pip: interactive plan timeline visualization — pure Python, `fig.to_json()` embeds in existing HTML templates via CDN plotly.js, no Dash overhead
- numpy micro-MLP (custom, no new dependency): residual RL agent — the existing codebase already implements DQN in numpy; extending to a 2-hidden-layer MLP for delta corrections is a natural continuation
- `highspy==1.13.1` (conditional fallback): direct HiGHS Python bindings — only needed if `apk add py3-scipy` provides a version older than 1.7.0; musllinux_1_2_aarch64 wheel confirmed on PyPI (Feb 2026)

**Explicit exclusions (do not revisit without base image change):** PyTorch, TensorFlow, Stable-Baselines3, ONNX Runtime, Prophet, Dash, Google OR-Tools, Pyomo, SHAP/LIME.

### Expected Features

The research distinguishes between what is already in v5 (baseline that must work reliably) and what v6 adds. Two categories of existing functionality are broken and act as blockers: SoC staleness detection for wallbox-connected vehicles, and the 15-minute transition delay in the charge sequencer. These are P1 bug fixes, not optional polish — the predictive planner's output is only as accurate as its input state.

**Must have for v6 launch (P1 — table stakes + core value):**
- SoC staleness bugfix — prerequisite for every downstream planning feature
- Charge sequencer immediate transition on vehicle change — eliminates the primary trust-breaking UX failure
- 24-48h predictive planner (joint battery + EV) — replaces static euro price limits; core milestone value
- Per-EV departure time (config + optional Telegram dynamic) — required for planner to size urgency windows
- Human-readable decision explanation ("why" text per plan slot) — users will disable opaque automation
- Emergency alert when EV cannot reach target SoC by departure — proactive, not reactive failure handling
- Manual override / boost charge (dashboard + Telegram) — users must always be able to override; OVO case study confirms removing this causes user revolt
- Plan timeline visualization (24-48h Gantt-style in dashboard) — forward-looking view is categorically different from the existing retrospective decision log

**Should have after validation (P2 — add once planner is trusted for 2-4 weeks):**
- Dynamic battery buffer (situational min-SoC based on PV forecast confidence)
- Telegram departure-time proactive query ("Wann brauchst du den Kia?")
- RL residual corrections promoted from shadow to advisory mode (after 2+ weeks of win-rate data)
- Consumption forecast from InfluxDB history (after 30+ days of clean data)
- RL win-rate dashboard widget (low effort, high transparency signal)

**Defer to v2+ (P3):**
- Seasonal learning (needs 12+ months of data)
- V2G/V2H (hardware not available)
- Multi-wallbox support (not applicable to current setup)
- Appliance scheduling (delegate to Home Assistant native automations)

**Anti-features to avoid:** Cloud LLM in the control loop (latency + cost + privacy), per-minute decision cycles (API rate limits), mobile app (Telegram + web dashboard covers the need).

SmartLoad's unique competitive position: the only self-hosted system combining evcc hardware integration, multi-EV sequencing with driver-aware prioritization, and transparent human-readable decision explanations. Commercial products (Intelligent Octopus, Ohme, ev.energy, Jedlix) all optimize opaquely.

### Architecture Approach

The v6 architecture introduces a Predictive Planning layer between data collection and the existing optimizer, and a formal StateStore (RLock-guarded shared state hub) to replace the current ad-hoc module-level globals that cause known web server race conditions. The RL agent's output changes from a full action selection (7×5 action space) to a signed delta correction (e.g., ±20 ct/kWh adjustment on the planner's battery and EV price limits), which dramatically reduces training time and preserves the planner's safety properties. Every component reads from the StateStore; only the DataCollector and vehicle monitor write to it. The web server is strictly read-only. New code lives in a `planner/` package; the existing `optimizer/` package is retained as fallback.

**Major components:**
1. **StateStore** (`state_store.py`) — single RLock-guarded hub holding current snapshot, plan horizon, and vehicle data; eliminates all existing race conditions; all threads read from it, writes are lock-guarded and fire callbacks post-release
2. **HorizonPlanner** (`planner/horizon_planner.py`) — solves 24-48h LP every 15-min cycle using current real state (rolling-horizon MPC); outputs `PlanHorizon` (list of `DispatchSlot`) stored in StateStore
3. **ConsumptionForecaster** (`planner/consumption_forecaster.py`) — maintains rolling hour-of-day averages from InfluxDB history; feeds home load estimates into HorizonPlanner
4. **DynamicBufferCalc** (`planner/dynamic_buffer.py`) — computes situational `min_battery_soc` from PV forecast confidence, price spread, and time-of-day; transparent formula (not a black box), logged to dashboard
5. **ResidualRLAgent** (refactored `rl_agent.py`) — outputs delta corrections on plan actions, clipped to ±20 ct; reward = plan_cost - actual_cost; trained online after each cycle
6. **SeasonalLearner** (`seasonal_learner.py`) — 3D lookup table (season × time-period × weekend) of average plan errors; provides context features to RL agent; deployed early to accumulate data
7. **ChargeSequencer** (refactored `charge_sequencer.py`) — event-driven transitions via StateStore callback + 15-min polling fallback; idempotent `evaluate_and_apply()`; adds starvation threshold and override expiry
8. **WebServer** (extended `web/server.py`) — strictly read-only from StateStore; serves cached plan JSON and plotly chart JSON; separate tabs for retrospective log and forward-looking plan timeline

### Critical Pitfalls

1. **Open-loop static plan execution** — Avoid by implementing true receding-horizon control: re-solve the LP every 15-min cycle from the real current state (battery SoC, vehicle SoC, latest price forecast). Never cache a plan across cycles for execution. Validate by injecting deliberate mid-cycle price changes in tests and confirming plan updates on the next cycle.

2. **RL learning unsafe constraint violations** — Avoid by encoding hard constraint violations as large fixed penalty rewards (not just opportunity cost), AND by hard-clipping RL delta output so it cannot push battery below `battery_min_soc` or miss EV departure SoC targets regardless of economic reward. Run a shadow-mode constraint audit over 30+ days of history before enabling live corrections.

3. **Dynamic battery buffer miscalibrated against inaccurate PV forecasts** — Avoid by gating buffer reduction on forecast confidence from day one (never lower below 10% hard floor; only lower when confidence is HIGH). Log every buffer-lowering event with the confidence signal so calibration can be improved empirically.

4. **Catastrophic forgetting in RL during seasonal transitions** — Avoid by building a stratified replay buffer from day one that explicitly retains samples from all four seasons. Never train exclusively on the last N days. Add concept drift detection (DDM or KSWIN) to increase learning rate temporarily during transition periods.

5. **RL bootstrap OOM on Raspberry Pi** — Fix before adding new planner features: cap bootstrap to 72h max, sample reservoir-style (LIMIT 1000 with timestamp sampling), stream in batches of 500, log progress. Target: startup under 3 minutes, peak memory under 256 MB.

6. **Multi-EV starvation from override without expiry** — Avoid by implementing override expiry (90-minute maximum), starvation threshold (notify waiting driver after 60 minutes), and wallbox vacancy detection (trigger transition check when full vehicle stays plugged >15 min).

---

## Implications for Roadmap

Research across all four files consistently points to a 4-phase structure that mirrors the component dependency graph. The architecture's `Build Order` section and the pitfalls' `Pitfall-to-Phase Mapping` are in strong agreement.

### Phase 1: Foundation — Data Reliability and State Infrastructure

**Rationale:** Every downstream feature depends on accurate vehicle SoC and thread-safe shared state. Building the predictive planner on stale data or a race-prone global state wastes the entire investment. These fixes are low-complexity, high-unblock-value, and the right start.
**Delivers:** Reliable SoC readings, <1-min sequencer transition response, thread-safe StateStore with RLock, fixed RL bootstrap memory behavior, config validation on startup.
**Addresses:** SoC staleness bugfix (P1), charge sequencer immediate transition (P1), RL bootstrap OOM fix (CONCERNS.md known issue), web server race condition elimination.
**Avoids:** Pitfall 4 (RL bootstrap OOM), Pitfall 6 (sequencer starvation — partial fix), thread-safety race condition in web server.
**Research flag:** Standard patterns — Python threading, RLock, event-driven callback. No deeper research needed; implementation is well-documented.

### Phase 2: Predictive Planner — 24-48h Horizon Optimization

**Rationale:** This is the core milestone deliverable. It can only be trusted once Phase 1 provides clean state. The planner introduces the new scipy LP solver, consumption forecaster (statsmodels via SARIMA or rolling averages), and dynamic buffer calculation. These are a single coherent subsystem.
**Delivers:** HorizonPlanner producing PlanHorizon with 24-48h DispatchSlots; per-EV departure time integration; ConsumptionForecaster (simple rolling average first, SARIMA refinement later); DynamicBufferCalc with forecast-confidence gating; plan timeline visualization in dashboard using plotly; human-readable decision explanation per slot; emergency Telegram alert when EV departure target is infeasible.
**Uses:** `scipy.optimize.linprog` (HiGHS), `statsmodels` (apk), `plotly==6.5.2` (pip).
**Implements:** HorizonPlanner, DynamicBufferCalc, ConsumptionForecaster, StateStore.update_plan(), WebServer plan timeline tab.
**Avoids:** Pitfall 1 (open-loop static plan — must be rolling-horizon from day one), Pitfall 5 (dynamic buffer miscalibration — forecast confidence gate is mandatory).
**Research flag:** LP formulation for joint battery+EV scheduling is well-documented (PyPSA, energy-py-linear patterns available). MPC rolling-horizon pattern is standard. The DynamicBufferCalc formula requires empirical tuning — plan a calibration period of 2-4 weeks post-launch before considering the buffer "reliable."

### Phase 3: Hybrid Residual RL — Learning Corrections

**Rationale:** RL residual corrections require a stable, proven planner as the baseline. The "residual" has nothing to correct if the planner is unstable. Phase 3 starts only after Phase 2 has been running and trusted for 2+ weeks. SeasonalLearner is deployed at Phase 3 start (not end) so it can accumulate data while other Phase 3 work is in progress.
**Delivers:** RL agent refactored from full action selection to delta corrections (±20 ct/kWh); SeasonalLearner deployed and accumulating; Comparator extended to track plan_cost vs actual_cost; RL win-rate dashboard widget; stratified replay buffer built from day one.
**Uses:** Custom numpy micro-MLP (no new dependency), existing InfluxDB historical data.
**Implements:** Refactored ResidualRLAgent, SeasonalLearner, Comparator extension.
**Avoids:** Pitfall 2 (RL unsafe constraint violations — delta clipping is mandatory), Pitfall 3 (catastrophic forgetting — stratified replay buffer from day one).
**Research flag:** The transition from shadow mode to advisory RL corrections is well-documented in the residual RL literature (EmergentMind survey, MDPI Energies 2025). The specific reward function calibration and delta clip threshold need empirical validation — plan a 2-week shadow comparison before promoting RL corrections to active mode.

### Phase 4: Transparency, Driver Interaction, and Polish

**Rationale:** These features deliver the highest user-visible trust return per implementation cost. They are largely independent of each other and can be sequenced flexibly within the phase. Telegram departure-time proactive query is the one feature that feeds back into the planner (updating HorizonPlanner departure slots), so it should come first within the phase.
**Delivers:** Telegram proactive departure query ("Wann brauchst du den Kia?") with 30-minute timeout fallback; config simplification (remove static euro price limits, expose planner parameters with sane defaults); dashboard progressive disclosure (next 6h default, zoom to 24h/48h); RL win-rate and shadow comparison widget (if not already shipped in Phase 3); config validation with startup rejection of invalid bounds.
**Avoids:** Pitfall UX (information overload — progressive disclosure required), notification spam (only notify on significant plan changes, not every re-optimization).
**Research flag:** Config simplification requires reviewing the full existing config surface area — a brief codebase audit before planning this phase is recommended. No external research needed.

### Phase Ordering Rationale

- Phase 1 before everything: StateStore and SoC reliability are prerequisites for all planning features. No amount of algorithmic sophistication compensates for corrupted input data.
- Phase 2 before Phase 3: RL residual corrections are mathematically defined as corrections on planner output. Without a stable planner, the delta space is meaningless.
- SeasonalLearner deployed at Phase 3 start (not end): It needs months of data to be statistically useful. Earlier deployment = earlier payoff.
- Phase 4 can overlap with late Phase 3: Transparency features do not depend on RL being active. The Telegram departure query, once built, feeds Phase 2's HorizonPlanner even before Phase 3 completes.
- The holistic LP optimizer (`optimizer/holistic.py`) is retained as fallback throughout. If the planner fails to solve (timeout, bad forecast), the system falls back to the existing optimizer rather than failing entirely.

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 2 (DynamicBufferCalc calibration):** The starting formula is a design inference, not a literature result. The confidence-gating threshold and the weight of each input term need empirical calibration against the specific setup (PV system size, battery capacity, typical German household load). Plan an explicit calibration sub-phase.
- **Phase 2 (ConsumptionForecaster maturation):** Rolling averages are sufficient for launch; SARIMA refinement requires verifying that 2-4 weeks of InfluxDB 15-min data is sufficient for stable SARIMA fitting. If data history is shorter, seasonal decomposition will be unreliable.
- **Phase 3 (RL constraint audit):** Before promoting RL corrections from shadow to active, a structured audit of the shadow agent's 30+ day recommendation history is required to verify no constraint-violating actions have positive Q-values.

**Phases with standard patterns (skip research-phase):**
- **Phase 1 (StateStore):** Python RLock, threading.Event, callback registration — all standard Python threading documentation. No research phase needed.
- **Phase 1 (SoC bugfix):** This is a logic fix in existing code paths (VehicleMonitor, evcc_provider). Requires code reading, not research.
- **Phase 2 (LP formulation):** scipy.optimize.linprog with HiGHS, 96-slot battery+EV scheduling — well-documented pattern in energy-py-linear and PyPSA. No research phase needed.
- **Phase 4 (Telegram interactions):** The Telegram bot infrastructure already exists. Proactive query is an extension of existing driver_manager.py patterns.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Core packages verified on PyPI and Alpine package repository (Feb 2026). PyTorch Alpine incompatibility is a hard constraint, not a preference. All recommended packages have confirmed musl/aarch64 compatibility. |
| Features | MEDIUM-HIGH | Table stakes verified against official product pages (Ohme, Octopus, evcc, Jedlix). Anti-feature rationale (OVO case study, XAI research) is MEDIUM — sourced from user forums and conference papers rather than vendor publications. |
| Architecture | MEDIUM | Component patterns (StateStore, rolling-horizon MPC, residual RL delta) are well-supported by literature and Python stdlib documentation. Specific integration choices (callback timing, deadlock prevention strategy) are design decisions informed by patterns, not directly cited results. |
| Pitfalls | MEDIUM | Critical pitfalls (open-loop plan, RL constraint violations, catastrophic forgetting, OOM bootstrap) are well-documented in academic and practitioner sources. Specific thresholds (±20 ct delta clip, 60-min starvation threshold, 30-min Telegram timeout) are reasonable estimates requiring empirical validation. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **PV forecast source:** evcc's solar tariff signal is a price signal, not a kWh generation forecast. For DynamicBufferCalc and HorizonPlanner to use PV generation estimates, either a dedicated PV forecast API must be integrated (e.g., Forecast.Solar), or PV generation must be estimated from historical irradiance patterns stored in InfluxDB. This gap should be resolved in Phase 2 planning before implementing DynamicBufferCalc.
- **evcc tariff forecast coverage:** evcc sometimes returns partial forecasts (6h or 12h rather than 24-48h). The HorizonPlanner must handle truncated forecasts gracefully and reduce confidence accordingly. The exact frequency and conditions of partial forecasts in the German dynamic tariff context (Tibber, aWATTar) should be validated against the live system during Phase 2 development.
- **DynamicBufferCalc formula calibration:** The starting formula in ARCHITECTURE.md is an informed design inference. The coefficients (spread_bonus factor of 0.3, pv_reduction factor of 2.0) need empirical tuning against the specific setup over 2-4 weeks. Plan a calibration phase with extensive logging before enabling dynamic buffer in production.
- **RL delta clip threshold:** The ±20 ct/kWh cap on residual corrections is a reasonable starting point from the literature but has not been validated for this specific system. The constraint audit in Phase 3 should inform whether the cap needs tightening or relaxing.
- **Seasonal learner data sufficiency:** SeasonalLearner uses 48 cells (4 seasons × 6 periods × 2 weekend flags). Each cell needs meaningful sample counts to produce reliable features for the RL agent. At 96 cycles/day, a full seasonal distribution requires months of operation. During Phase 3, the learner should expose cell confidence (sample count) so the RL agent can weight its context features accordingly.

---

## Sources

### Primary (HIGH confidence)
- [highspy 1.13.1 on PyPI](https://pypi.org/project/highspy/) — confirmed musllinux_1_2_aarch64 wheel (Feb 11, 2026)
- [plotly 6.5.2 on PyPI](https://pypi.org/project/plotly/) — confirmed pure Python py3-none-any wheel (Jan 14, 2026)
- [py3-scipy on Alpine Linux packages](https://pkgs.alpinelinux.org/package/edge/community/x86/py3-scipy) — confirmed Alpine community repo
- [py3-statsmodels on Alpine Linux packages](https://pkgs.alpinelinux.org/package/edge/community/armhf/py3-statsmodels) — confirmed Alpine community repo
- [Python threading documentation](https://docs.python.org/3/library/threading.html) — RLock, threading.Event patterns
- [Intelligent Octopus Go — Octopus Energy](https://octopus.energy/smart/intelligent-octopus-go/) — feature comparison
- [Ohme Home Pro — HA Integration](https://www.home-assistant.io/integrations/ohme/) — feature comparison
- [Jedlix Smart Charging Features](https://www.jedlix.com/categories/product-features) — feature comparison
- [GridX HEMS Modules](https://www.gridx.ai/hems-modules) — feature comparison
- [evcc Predictive Charging Discussions](https://github.com/evcc-io/evcc/discussions/20312) — evcc context
- SmartLoad v5 codebase (direct reading) — holistic.py, decision_log.py, charge_sequencer.py, CONCERNS.md

### Secondary (MEDIUM confidence)
- [scipy.optimize.linprog HiGHS docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html) — LP formulation, dual variables
- [ADGEfficiency/energy-py-linear](https://github.com/ADGEfficiency/energy-py-linear) — LP battery scheduling pattern
- [MPC-RL hybrid for EV smart charging (ScienceDirect 2025)](https://www.sciencedirect.com/science/article/pii/S2352467725003455) — rolling-horizon pattern
- [H-RPEM health-aware hybrid RL-MPC (MDPI Batteries 2025)](https://www.mdpi.com/2313-0105/12/1/5) — dynamic buffer pattern
- [Residual RL survey 2024-2025 (EmergentMind)](https://www.emergentmind.com/topics/residual-reinforcement-learning-rl) — residual RL delta pattern
- [Expert-guided DRL SAC (MDPI Energies 2025)](https://www.mdpi.com/1996-1073/18/22/6054) — hybrid planner+RL validation
- [Safe RL in Power and Energy Systems (Engineering Applications of AI 2025)](https://dl.acm.org/doi/10.1016/j.engappai.2025.110091) — RL constraint penalties
- [Continual Learning for EMS (ScienceDirect 2025)](https://www.sciencedirect.com/science/article/pii/S0306261925001886) — catastrophic forgetting mitigation
- [OVO Charge Anytime User Frustration — EV Forum](https://forum.ovoenergy.com/electric-vehicles-166/charge-anytime-not-scheduling-charging-sessions-with-hypervolt-pro-3-charger-tesla-18162) — manual override UX importance
- [Practical Challenges of MPC — Lawrence Berkeley National Lab, 2024](https://eta-publications.lbl.gov/sites/default/files/2024-09/practical_challenges_of_model_predictive_control.pdf) — open-loop plan pitfall
- [MPC Rolling Horizon: Open-Loop Infeasibility — arXiv, 2025](https://arxiv.org/pdf/2502.02133) — rolling-horizon validation
- [Multi-EV Scheduling via Stochastic Queueing — Nature Scientific Reports, 2025](https://www.nature.com/articles/s41598-025-04725-7) — sequencer starvation prevention

### Tertiary (LOW confidence)
- [SeasonalLearner formula design] — informed by seasonal demand forecasting literature (ANFIS+LSTM, Scientific Reports 2025) but the specific 48-cell indexing and decay formula are original design decisions requiring empirical validation
- [DynamicBufferCalc formula] — coefficients (0.3, 2.0) are starting estimates; empirical tuning required against the specific hardware setup

---

*Research completed: 2026-02-22*
*Ready for roadmap: yes*
