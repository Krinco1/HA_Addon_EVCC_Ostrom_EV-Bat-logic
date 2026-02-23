# Phase 8: Residual RL and Learning - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

The RL agent is refactored from full action selection to signed delta corrections (+/-20ct clip) on the planner's battery and EV price thresholds. A SeasonalLearner accumulates pattern data in a 48-cell lookup table. Forecast reliability tracking applies learned confidence factors to PV, consumption, and price forecasts. Adaptive reaction timing learns when to re-plan vs wait. The dashboard shows RL performance vs the planner with German labels.

</domain>

<decisions>
## Implementation Decisions

### RL Promotion Path
- Automatic promotion: system runs constraint audit after 30-day shadow period, promotes to advisory automatically if all checks pass
- No Telegram notifications for RL status — Telegram is reserved exclusively for charging plan integration and errors
- Dashboard is the sole UI channel for RL status, audit results, and promotion info

### Dashboard RL Widget
- Dashboard language: German throughout (consistent with existing dashboard) — 'Lernmodus', 'Beobachtung', 'Gewinnrate', 'Tagesersparnis'
- No mixed DE/EN for RL terms

### Claude's Discretion
- **RL Promotion:** Audit failure handling (continue shadow + retry, clip-range reduction, or other). Two-stage vs three-stage model (Shadow+Advisory vs Shadow+Advisory+Active). Audit UI representation (badge vs checklist vs other)
- **Dashboard Widget:** Placement within existing tab structure (new tab vs embedded vs integrated). Primary metrics selection (EUR savings, win-rate, or both). Shadow-phase visibility (show learning progress during shadow or hide until advisory)
- **Forecast Confidence:** Whether/how to display confidence to user. Impact on planner behavior (conservative planning vs weighting only). Storage approach (rolling window vs seasonal cells). Whether to couple with DynamicBufferCalc
- **Learning Speed:** SeasonalLearner conservatism (minimum sample threshold per cell). Decay strategy (exponential vs none). Adaptive reaction timing approach (learned vs fixed thresholds). Replay buffer strategy (stratified vs FIFO)

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. User trusts Claude's judgment on all technical and UX decisions for this phase, with two hard constraints:
1. Telegram is ONLY for charging plan integration and errors — no RL status messages
2. All dashboard text in German

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 08-residual-rl-and-learning*
*Context gathered: 2026-02-23*
