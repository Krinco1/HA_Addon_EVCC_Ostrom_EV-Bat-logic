---
phase: 08-residual-rl-and-learning
plan: 03
subsystem: rl-learning
tags: [residual-rl, seasonal-learner, forecast-reliability, reaction-timing, ema, q-learning, lp-planner, dynamic-buffer]

# Dependency graph
requires:
  - phase: 08-01
    provides: ResidualRLAgent with shadow/advisory mode, StratifiedReplayBuffer, Comparator slot-0 extension
  - phase: 08-02
    provides: SeasonalLearner (48-cell), ForecastReliabilityTracker (rolling MAE)
  - phase: 04-predictive-planner
    provides: HorizonPlanner.plan() LP solver
  - phase: 05-dynamic-buffer
    provides: DynamicBufferCalc.step() buffer formula
provides:
  - ReactionTimingTracker with EMA-based self-correction rate and persistence
  - HorizonPlanner.plan() extended with confidence_factors dict (pv confidence scales PV surplus in LP objective)
  - DynamicBufferCalc.step() extended with pv_reliability_factor (effective_confidence = pv * reliability)
  - main.py with all four Phase 8 learners instantiated and wired into the decision loop
  - Shadow/advisory RL branching replacing old DQNAgent select_action() path
  - Forecast reliability updates (PV/consumption/price) each cycle before planner call
  - SeasonalLearner.update() called each cycle with slot-0 plan error
  - ReactionTimingTracker.update() + should_replan_immediately() LERN-03 trigger
  - Comparator.compare_residual() + ResidualRLAgent.learn_from_correction() each cycle
  - Auto-promotion check: run_constraint_audit() + maybe_promote() after 30-day shadow
affects: [08-04, web-dashboard, rl-audit]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Phase 8 helper pattern: _current_slot_index(), _compute_slot0_cost(), _compute_actual_slot0_cost(), _action_to_str() for shared computations"
    - "Shadow/advisory branching: single rl_agent.mode check gates correction application vs log-only"
    - "Confidence factor wiring: reliability tracker -> confidence dict -> planner.plan() + buffer.step()"
    - "Shared slot-0 cost block: computed once before all learner if-blocks to prevent NameError"
    - "Graceful learner init: all four Phase 8 learners wrapped in try/except with None fallback"

key-files:
  created:
    - evcc-smartload/rootfs/app/reaction_timing.py
  modified:
    - evcc-smartload/rootfs/app/main.py
    - evcc-smartload/rootfs/app/optimizer/planner.py
    - evcc-smartload/rootfs/app/dynamic_buffer.py

key-decisions:
  - "ReactionTimingTracker EMA initial value = 0.5, wait_threshold = 0.6: on first start, system re-plans by default (0.5 < 0.6) until enough episodes show self-correction is common"
  - "confidence_factors applied only to PV surplus in LP objective (not price coefficients): per Phase 8 research Open Question 1 recommendation — price confidence affects buffer conservatism, not LP coefficients"
  - "pv_reliability_factor applied as multiplier on existing pv_confidence before _compute_target(): effective_confidence = pv_confidence * pv_reliability_factor"
  - "RL bootstrap removed: ResidualRLAgent loads itself in __init__.load(); old bootstrap was for DQNAgent imitation learning which doesn't apply to delta corrections"
  - "_action_to_str() returns compound bat/ev string (e.g. 'bat_charge/ev_idle'); ReactionTimingTracker stores and compares these as-is"
  - "store.update() now passes 'final' as rl_action: dashboard sees the actual applied action (LP or RL-adjusted) rather than a separate DQN action object"
  - "last_rl_action removed from loop state: ResidualRLAgent.learn_from_correction() uses current state twice (state as both state and next_state); full next_state tracking deferred to Phase 9"

patterns-established:
  - "Shared cost block before learner updates: compute plan_slot0_cost and actual_slot0_cost once, used by SeasonalLearner + Comparator + RL learning"
  - "Override guard: all RL paths guarded by 'not override_active' to prevent boost state from polluting shadow audit"
  - "Late attribute injection for new learners: srv.seasonal_learner = ..., consistent with buffer_calc/plan_snapshotter pattern"

requirements-completed: [LERN-03, LERN-04]

# Metrics
duration: 6min
completed: 2026-02-23
---

# Phase 8 Plan 03: ReactionTimingTracker + All Phase 8 Learner Wiring Summary

**ReactionTimingTracker with EMA deviation classification, HorizonPlanner and DynamicBufferCalc extended with confidence factors, all four Phase 8 learners wired into main.py decision loop with shadow/advisory RL branching**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-23T21:38:40Z
- **Completed:** 2026-02-23T21:44:40Z
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- Created `reaction_timing.py` with `ReactionTimingTracker`: EMA-based self-correction rate (alpha=0.05, initial=0.5, threshold=0.6), `DeviationEpisode` dataclass, atomic JSON persistence, threading.Lock safety
- Extended `HorizonPlanner.plan()` with optional `confidence_factors` dict; PV confidence scales PV surplus reduction in LP objective, making the planner more conservative when PV forecasts are unreliable
- Extended `DynamicBufferCalc.step()` with optional `pv_reliability_factor`; effective_confidence = pv_confidence * pv_reliability_factor keeps buffer higher when PV is unreliable
- Replaced entire old `DQNAgent` path in `main.py` with four-learner Phase 8 wiring: shadow/advisory branching, forecast reliability updates, confidence factor propagation, SeasonalLearner + ReactionTimingTracker updates, auto-promotion check

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ReactionTimingTracker and extend planner/buffer with confidence factors** - `851f85c` (feat)
2. **Task 2: Wire all Phase 8 learners into main.py decision loop** - `fe85803` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `evcc-smartload/rootfs/app/reaction_timing.py` - ReactionTimingTracker with EMA self-correction rate, DeviationEpisode dataclass, JSON persistence
- `evcc-smartload/rootfs/app/main.py` - All Phase 8 learner wiring: ResidualRLAgent shadow/advisory, ForecastReliabilityTracker, SeasonalLearner, ReactionTimingTracker, helpers
- `evcc-smartload/rootfs/app/optimizer/planner.py` - confidence_factors parameter in plan(); pv_confidence_factor passed to _solve_lp() and applied to PV surplus in LP objective
- `evcc-smartload/rootfs/app/dynamic_buffer.py` - pv_reliability_factor parameter in step(); effective_confidence = pv_confidence * pv_reliability_factor before formula

## Decisions Made

- EMA initial value 0.5 with threshold 0.6: system defaults to triggering re-plans until it learns deviations self-correct; conservative start avoids stale plans early in deployment
- confidence_factors applied only to PV surplus in LP objective (not price coefficients): research Open Question 1 recommends price confidence flows through DynamicBufferCalc conservatism, not LP coefficient scaling — lower risk and easier to explain
- pv_reliability_factor multiplied on existing pv_confidence: composable with the existing PVForecaster.confidence signal, no special-casing needed
- RL bootstrap removed: ResidualRLAgent is self-loading via __init__; the bootstrap was DQNAgent-specific for imitation learning
- _action_to_str() returns compound "bat_X/ev_Y" string: richer signal for ReactionTimingTracker than battery-only comparison
- last_rl_action removed from loop state: ResidualRLAgent.learn_from_correction() uses (state, action_idx, reward, next_state=state) where next_state=state is a simplification; proper prev/next tracking deferred
- store.update() passes `final` instead of `rl_action`: dashboard sees the actual applied action (LP or RL-corrected) rather than a separate DQN decision object

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None — all integrations worked cleanly. The `_current_slot_index()` helper was needed in both ForecastReliabilityTracker update calls and was written as a module-level function matching the plan spec.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All four Phase 8 learning subsystems are now live in the decision loop
- LERN-01 (ResidualRLAgent delta corrections) + LERN-02 (SeasonalLearner) + LERN-03 (ReactionTimingTracker) + LERN-04 (ForecastReliabilityTracker confidence) are all complete
- Phase 8 Plan 04 (Dashboard "Lernen" tab) is the final remaining plan: GET /rl-learning endpoint, "Lernen" tab with German labels, shadow countdown, constraint audit display
- Blocker noted in STATE.md: RL constraint audit requires 30-day shadow period before advisory promotion; SeasonalLearner needs months for statistically meaningful cells

---
## Self-Check: PASSED

- `evcc-smartload/rootfs/app/reaction_timing.py` — FOUND
- `.planning/phases/08-residual-rl-and-learning/08-03-SUMMARY.md` — FOUND
- Commit `851f85c` (Task 1) — FOUND
- Commit `fe85803` (Task 2) — FOUND

---
*Phase: 08-residual-rl-and-learning*
*Completed: 2026-02-23*
