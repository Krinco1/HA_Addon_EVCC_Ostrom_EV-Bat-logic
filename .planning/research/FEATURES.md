# Feature Research

**Domain:** Home Energy Management System (HEMS) — Home Battery + Multi-EV Predictive Optimization
**Researched:** 2026-02-22
**Confidence:** MEDIUM-HIGH (commercial products verified; academic claims MEDIUM; user frustration data MEDIUM)

---

## Context: What Already Exists in SmartLoad v5

The existing system is not a greenfield build. The following are implemented and must be treated as baseline:

- evcc integration (battery SoC, EV wallbox, PV data, price tariffs)
- Vehicle SoC polling (Kia/Hyundai, Renault/Dacia, manual, evcc-native, custom HTTP)
- Charge sequencer: multi-EV priority scheduling on 1 wallbox
- Telegram bot: driver interaction, notifications
- Web dashboard with decision log (observe / plan / action / RL / sequencer categories)
- InfluxDB: historical data
- RL agent in shadow mode (DQN-based, compared against LP optimizer)
- Holistic LP optimizer (percentile-based price thresholds P20/P30/P40/P60/P80)
- Quiet hours, per-vehicle target SoC, deadline-based urgency escalation

The milestone adds predictive planning, multi-EV orchestration improvements, and transparent decision-making on top of this foundation.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features the target user (technically sophisticated home automation enthusiast, German market, dynamic tariff, 1 wallbox + 3 EVs + PV + battery) considers baseline. Missing these makes the system feel broken or untrustworthy.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Real-time SoC accuracy for all EVs | Stale SoC data causes wrong charging decisions; users notice immediately when car is wrongly managed | MEDIUM | Current v5 has known stale-detection bugs for wallbox-connected vehicles. Fix is pre-requisite for any predictive feature. |
| 24-48h price-aware charge scheduling | All leading products (Intelligent Octopus, Ohme, ev.energy) offer "ready by" with cheapest-slot selection; users consider this the minimum viable HEMS | HIGH | Replaces static euro-price limits with plan-based optimization. Core of the milestone. |
| Battery SoC visible alongside EV SoC in dashboard | Users need a unified view of all energy assets; missing = dashboard feels incomplete | LOW | Already partially there; needs improvement for plan timeline view. |
| "Ready by" departure time per EV | ev.energy, Ohme, Optiwatt all center UX around departure time; without it, scheduling is guesswork | MEDIUM | Currently implemented as a fixed `ev_charge_deadline_hour` config per system. Needs to be per-EV and dynamic (from Telegram or config). |
| Manual override / boost charge | OVO users were furious when Urgent Charge button was removed. Users MUST be able to override automation immediately. | LOW | Telegram "charge now" command partially covers this. Dashboard override needed too. |
| Charge plan that survives EV plug/unplug | Plan must recompute when EV is connected/disconnected, not just on the 15-min cycle | MEDIUM | Charge sequencer currently has up to 15-min delay on vehicle transitions. |
| Explanation of why a decision was made | Users will not trust — and will disable — a system that makes opaque decisions. GridX, SENEC all emphasize user transparency. XAI research confirms this. | MEDIUM | Decision log exists but shows raw actions, not "why". Needs human-readable reasoning text. |
| Emergency alert when EV will not be ready | If optimization concludes car cannot reach target SoC by departure, user must be warned proactively | LOW | Not currently implemented. Telegram is the right channel. |
| Config stays comprehensible | As features are added, configuration complexity must be controlled. Users who cannot configure the system stop using it. | MEDIUM | Active constraint from PROJECT.md. Each new feature must have sane defaults. |

### Differentiators (Competitive Advantage)

Features that go beyond what Intelligent Octopus / Ohme / evcc offer out of the box, aligned with SmartLoad's core value proposition.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Holistic 24-48h plan covering battery + EV jointly | Most chargers optimize EV OR battery independently. Joint optimization avoids the battery discharging at the same time the EV charges from grid. | HIGH | Replaces the current greedy-with-urgency logic. Requires LP or MILP over time horizon. This is the central differentiator. |
| Dynamic battery buffer (situational min-SoC) | Fixed min-SoC wastes money in summer and under-protects in winter. Situational buffer (weather, season, hour, forecast) is technically better. | HIGH | Depends on PV forecast and consumption forecast being available. |
| RL residual corrections on top of planner | RL learns patterns the rule-based planner cannot capture (e.g., specific household consumption spikes on certain days). Hybrid approach is more trainable and more explainable than end-to-end RL. | HIGH | Shadow mode already running. Milestone: promote RL from shadow to advisory or active residual. |
| Multi-EV fairness with driver-context awareness | Jedlix / ev.energy support multi-vehicle but as separate profiles. SmartLoad knows which driver needs which car when (via Telegram), enabling priority that respects real human need rather than just SoC rank. | HIGH | Depends on Telegram departure-time query feature. |
| Telegram-driven departure time input | No commercial HEMS uses a messaging bot for real-time driver input. For a household where the same people drive the same cars, this is friction-free compared to an app. | MEDIUM | Infrastructure exists (Telegram bot). Feature: proactive "when do you need the Kia?" query + plan update on reply. |
| Consumption forecast for planning | Most HEMS use static load assumptions. SmartLoad can learn household consumption patterns from InfluxDB history and use them to improve plan accuracy. | HIGH | Requires time-series pattern recognition. Phase 2+ feature. |
| Plan timeline visualization (24-48h Gantt-style) | Users understand the plan as a visual timeline far better than a log of past actions. Ohme and Intelligent Octopus show future scheduled sessions graphically. | MEDIUM | Current dashboard shows past decisions. Needs forward-looking plan view. |
| RL win-rate and shadow comparison visible to user | Surfacing the RL vs LP comparison builds trust: user can see the AI is being validated before it acts. Unique transparency feature not offered by commercial products. | LOW | Data already collected by comparator. Needs dashboard widget. |
| Seasonal learning (winter vs summer strategy) | Static systems fail in winter (no PV, grid-heavy) vs summer (PV-heavy). SmartLoad can learn seasonal patterns from InfluxDB and adjust automatically. | HIGH | Long-term feature; 12 months of data needed. Flag for future milestone. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem desirable but would make the system worse, more fragile, or harder to maintain.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Cloud LLM for real-time decisions | "Ask Claude why it made that decision" sounds appealing | Latency (seconds vs milliseconds needed), cost, external dependency, privacy. Numeric optimization does not need language models for real-time control. Already ruled out in PROJECT.md. | Use the decision log + plan explanation text instead. LLM could be used offline for analysis or config assistance — not in the control loop. |
| V2G (vehicle-to-grid / vehicle-to-home) | Users with compatible cars want to discharge EV into home during expensive hours | Requires bidirectional charger hardware not in this setup; accelerates battery degradation; evcc does not yet expose V2G control cleanly. Future hardware feature. | Optimize charging timing to fully use battery before peak prices; discharge home battery instead. |
| Per-minute decision cycles | Users want instant response to price spikes | Increases API call rate to evcc and vehicle APIs; risks rate limiting; most price tariffs are hourly so sub-15-min cycles add noise not signal | Keep 15-min cycle but trigger immediate re-plan on significant events (EV plug-in, price spike detection) |
| Appliance scheduling (dishwasher, washing machine) | Full HEMS scope | Out of scope for this system (no HA automation integration planned); adds enormous configuration complexity; Home Assistant itself handles this better natively | Document as "use HA automations for appliances, SmartLoad for battery+EV" |
| Mobile app (iOS/Android) | More accessible than web dashboard | Adds entire separate development track; Telegram covers real-time interaction; web dashboard covers monitoring; mobile app adds no unique value for this single-household use case. Out of scope in PROJECT.md. | Web dashboard (responsive) + Telegram for push notifications |
| Multi-wallbox support | Users with 2 wallboxes want support | Hardware constraint: current setup has 1 wallbox. Adding multi-wallbox would require significant sequencer rearchitecture and is not validated by the actual hardware available. | Leave as config option to note "1 wallbox assumed"; document extension path |
| Fully autonomous mode without any user confirmation | "Set and forget" is appealing | Creates trust failure when system makes a wrong decision. OVO/Charge Anytime case study: removing manual override caused user revolt. Users need to feel in control even if they rarely intervene. | Always maintain override; make automation the default but never the only path |
| Static euro price limits as primary control | Simple and understandable | Cannot adapt to relative price context. P30 on a cheap day is very different from P30 on an expensive day. Static limits cause both over-charging and under-charging. | Replace with plan-based thresholds that adapt to current 24-48h price distribution |

---

## Feature Dependencies

```
[SoC Accuracy Fix]
    └──required by──> [24-48h Predictive Planner]
                          └──required by──> [Dynamic Battery Buffer]
                          └──required by──> [Multi-EV Fairness w/ Driver Context]
                          └──enables──> [Plan Timeline Visualization]

[Telegram Departure Time Query]
    └──required by──> [Multi-EV Fairness w/ Driver Context]
    └──enables──> [Emergency "Car Won't Be Ready" Alert]

[24-48h Predictive Planner]
    └──enables──> [RL Residual Corrections] (RL corrects planner, not rule system)
    └──enables──> [Consumption Forecast Integration]

[Decision Log (existing)]
    └──enhanced by──> [Human-Readable WHY Explanation Text]
    └──enhanced by──> [Plan Timeline Visualization]

[RL Shadow Mode (existing)]
    └──graduates to──> [RL Residual Corrections]
    └──measured by──> [RL Win-Rate Dashboard Widget]

[Charge Sequencer (existing)]
    └──bug fix──> [Immediate Transition on Vehicle Change]
    └──enhanced by──> [Multi-EV Fairness w/ Driver Context]

[InfluxDB Historical Data (existing)]
    └──enables──> [Consumption Forecast]
    └──enables──> [Seasonal Learning] (long-term)
```

### Dependency Notes

- **SoC Accuracy Fix is a blocker:** The predictive planner computes hours of charge needed based on SoC. If SoC is stale or wrong by 20%, the plan will be wrong by hours. This must be fixed before the planner is trusted.
- **Telegram departure time requires Telegram bot (existing):** The infrastructure exists; what's needed is the proactive query flow (system asks driver, not driver tells system).
- **RL residual corrections require a stable planner baseline:** RL learns to correct the planner's systematic errors. If the planner itself is unstable, RL has nothing stable to correct.
- **Plan visualization conflicts with current decision log UX:** The decision log shows past events; the plan timeline shows future. These should be separate dashboard tabs to avoid confusion.
- **Consumption forecast enhances but does not block the planner:** The planner can launch with static consumption assumptions and improve once forecast is available.

---

## MVP Definition

For the next milestone (v6), the minimum viable increment adds a trusted predictive planner with transparent decisions, while fixing the existing reliability issues that undermine trust.

### Launch With (v6.0) — Core Predictive Planning

These are ordered by dependency; each must work before the next is trustworthy.

- [ ] **SoC staleness bugfix** — Without accurate SoC, all planning is wrong. Fix stale detection for wallbox-connected vehicles first.
- [ ] **Charge sequencer: immediate transition** — 15-min delay on vehicle change causes the planner to act on wrong vehicle data. Fix before planner launch.
- [ ] **24-48h predictive planner (battery + EV, joint)** — Replaces static euro limits. Computes optimal charging slots across full price forecast window.
- [ ] **Per-EV departure time** — Read from config (static) or Telegram (dynamic). Used by planner to size urgency windows.
- [ ] **Emergency alert: car won't be ready** — If planner determines target SoC unreachable by departure, send Telegram alert immediately.
- [ ] **Human-readable decision explanation** — Each plan decision accompanied by 1-2 sentence WHY text (e.g., "Charging Kia now because price is in bottom 20% and departure in 6h needs 3 more hours").
- [ ] **Plan timeline view in dashboard** — 24-48h forward-looking Gantt showing planned battery and EV charge slots with price overlay.
- [ ] **Manual override (dashboard + Telegram)** — "Charge now" overrides plan for current vehicle. Essential for trust.

### Add After Validation (v6.x) — Refinements

Features to add once the core planner is running and trusted for 2-4 weeks.

- [ ] **Dynamic battery buffer** — Trigger: planner stability confirmed, PV forecast quality validated.
- [ ] **Telegram departure-time query** — Trigger: per-EV departure config proven insufficient for chaos of real life.
- [ ] **RL residual corrections (advisory)** — Trigger: planner has accumulated 2+ weeks of comparison data and RL win-rate shows consistent improvement.
- [ ] **Consumption forecast from InfluxDB** — Trigger: >30 days of household consumption data available; planner shows systematic errors from static assumptions.
- [ ] **RL win-rate dashboard widget** — Low effort, high transparency value. Can ship with v6.0 if time allows.

### Future Consideration (v2+) — Long-Horizon Features

- [ ] **Seasonal learning** — Requires 12+ months of InfluxDB history. Defer entirely.
- [ ] **V2G/V2H support** — Hardware not available; defer until bidirectional charger is in setup.
- [ ] **Multi-wallbox support** — Not applicable to current hardware. Defer.
- [ ] **Appliance scheduling** — Delegate to Home Assistant native automations; not SmartLoad's domain.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| SoC staleness fix | HIGH (prerequisite for trust) | LOW | P1 |
| Charge sequencer immediate transition | HIGH (immediate UX reliability) | LOW | P1 |
| 24-48h predictive planner | HIGH (core value) | HIGH | P1 |
| Per-EV departure time | HIGH (planner accuracy) | MEDIUM | P1 |
| Human-readable decision explanation | HIGH (trust, transparency) | MEDIUM | P1 |
| Emergency: car won't be ready alert | HIGH (prevents missed departures) | LOW | P1 |
| Manual override (boost charge) | HIGH (safety net for trust) | LOW | P1 |
| Plan timeline visualization | MEDIUM (comprehension) | MEDIUM | P2 |
| Dynamic battery buffer | MEDIUM (optimization quality) | HIGH | P2 |
| Telegram departure-time query | MEDIUM (handles human chaos) | MEDIUM | P2 |
| RL residual corrections (advisory) | MEDIUM (long-term improvement) | HIGH | P2 |
| Consumption forecast | MEDIUM (planner accuracy) | HIGH | P2 |
| RL win-rate dashboard widget | LOW (transparency bonus) | LOW | P2 |
| Seasonal learning | LOW (long-term only) | HIGH | P3 |

**Priority key:**
- P1: Must have for launch (blocks user trust or core value)
- P2: Should have, add when possible (improves quality or UX)
- P3: Nice to have, future consideration

---

## Competitor Feature Analysis

| Feature | Intelligent Octopus Go | Ohme Home Pro | Jedlix | evcc (open source) | SmartLoad v6 Plan |
|---------|------------------------|---------------|--------|---------------------|-------------------|
| Predictive scheduling | Yes (renewable forecast + price) | Yes (tariff integration) | Yes (cost-optimized) | Yes (charge plan w/ late charging) | Yes — 24-48h LP planner |
| Departure time / ready by | App input, daily default | App input | App input | Per-vehicle config | Config + Telegram dynamic |
| Battery integration | Whole-home off-peak rate | Solar boost | Not primary | Yes, with home battery control | Joint battery+EV optimization |
| Multi-EV management | Not primary | Not primary | Multi-vehicle account | Yes, multi-loadpoint | Yes, charge sequencer + planner |
| Decision explanation | None (opaque) | None (opaque) | Charging insights | None | Yes — human-readable WHY |
| Manual override | App boost | App boost | App boost | Dashboard mode switch | Telegram + dashboard |
| RL / AI improvement | None public | None public | Algorithm learning | Exploring LLM via MCP | Hybrid RL residual corrections |
| Open/self-hosted | No | No | No | Yes (local) | Yes (HA add-on) |
| Emergency alert | Push notification | Push notification | Push notification | Not prominently | Telegram alert |

**SmartLoad's unique position:** The only system that combines evcc integration (covering all local hardware without cloud lock-in), multi-EV sequencing with driver-aware prioritization, and a transparent decision log with human-readable explanations — all running locally on Home Assistant.

The gap commercial products fail to close: **explainability**. Intelligent Octopus, Ohme, and ev.energy all optimize opaquely. When the car is not charged by morning, users have no idea why. SmartLoad's decision log and plan visualization solve this directly.

---

## The Human Chaos Factor: How Leading Systems Handle It

Research on EV departure time prediction confirms this is an open, unsolved problem across the industry (ACM 2024, GridX blog, academic HEMS literature).

**Current approaches:**
1. **Fixed "ready by" time** (ev.energy, Ohme default): Simple, fails when plans change
2. **Per-day weekly schedule** (ev.energy Smart Schedule): Better, still breaks for exceptions
3. **Behavioral learning** (Jedlix, UC Riverside SOM research): Learns from usage patterns; 6-18 months data needed; not deployed in consumer products yet
4. **Proactive query via messaging** (not commercially deployed): Ask driver before optimizing; SmartLoad's Telegram approach

**SmartLoad's pragmatic approach for v6:**
- Step 1: Config-based departure time per vehicle (static but per-vehicle, not system-wide)
- Step 2: Telegram query (when planner detects vehicle plugged in with departure within planning window, ask driver: "Wann brauchst du den Kia?")
- Step 3: Emergency escalation when deadline math shows shortfall regardless of why

This handles the chaos factor without behavioral ML that requires months of data and adds a full ML pipeline.

---

## Sources

- [Intelligent Octopus Go — Official Octopus Energy](https://octopus.energy/smart/intelligent-octopus-go/) — HIGH confidence (official)
- [Ohme Home Pro — Home Assistant Integration](https://www.home-assistant.io/integrations/ohme/) — HIGH confidence (official)
- [Jedlix Smart Charging Features](https://www.jedlix.com/categories/product-features) — HIGH confidence (official product page)
- [GridX HEMS Modules](https://www.gridx.ai/hems-modules) — HIGH confidence (official, verified via WebFetch)
- [evcc — Predictive Charging & Battery Optimization Discussions](https://github.com/evcc-io/evcc/discussions/20312) — HIGH confidence (official community)
- [evcc 2025 Highlights Blog](https://docs.evcc.io/en/blog/2025/07/30/highlights-config-ui-feedin-ai) — HIGH confidence (official changelog)
- [OVO Charge Anytime User Frustration — EV Forum](https://forum.ovoenergy.com/electric-vehicles-166/charge-anytime-not-scheduling-charging-sessions-with-hypervolt-pro-3-charger-tesla-18162) — MEDIUM confidence (user reports, not vendor)
- [Explainable RL-based HEMS using Differentiable Decision Trees — arXiv 2403.11947](https://arxiv.org/html/2403.11947v1) — MEDIUM confidence (academic, peer-reviewed)
- [Departure Time Prediction via Digital Phenotyping — ACM IMWUT](https://dl.acm.org/doi/10.1145/3699725) — MEDIUM confidence (academic)
- [GridX HEMS Knowledge Base](https://www.gridx.ai/knowledge/home-energy-management-system-hems) — HIGH confidence (official)
- [HEMS XAI — PV Symposium 2025](https://www.tib-op.org/ojs/index.php/pv-symposium/article/download/2641/2891/52181) — MEDIUM confidence (conference paper)
- [ev.energy Smart Schedule features](https://support.ev.energy/en/support/solutions/articles/80000186755-release-notes) — HIGH confidence (official release notes)
- SmartLoad v5 codebase — HIGH confidence (direct code reading: holistic.py, decision_log.py, charge_sequencer.py)
- SmartLoad PROJECT.md — HIGH confidence (authoritative project context)

---

*Feature research for: Home Energy Management System — Battery + Multi-EV Predictive Planning*
*Researched: 2026-02-22*
