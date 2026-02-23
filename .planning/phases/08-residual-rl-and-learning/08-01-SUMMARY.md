---
phase: 08-residual-rl-and-learning
plan: 01
subsystem: ml
tags: [reinforcement-learning, q-table, stratified-replay, residual-rl, comparator, seasonal-buffer]

# Dependency graph
requires:
  - phase: 05-dynamic-buffer
    provides: DynamicBufferCalc pattern for JSON persistence and atomic writes
  - phase: 06-lp-planner
    provides: HorizonPlanner LP plan with slot-0 pricing data (DispatchSlot, PlanHorizon)
provides:
  - ResidualRLAgent with 49-action delta correction space (7 bat x 7 EV deltas, +/-20ct)
  - StratifiedReplayBuffer with 4 seasonal sub-buffers (winter/spring/summer/autumn)
  - Shadow/advisory mode with run_constraint_audit() and maybe_promote()
  - Extended Comparator with compare_residual(), get_recent_comparisons(), cumulative_savings_eur(), avg_daily_savings()
affects: [08-02, 08-03, 08-04, main.py, web/server.py]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - ResidualRLAgent: delta corrections (+/-20ct) on LP price thresholds instead of full action selection
    - StratifiedReplayBuffer: one deque per season, sample equally from non-empty seasons
    - model_version=2 migration guard: detects old DQNAgent Q-tables and resets cleanly
    - Slot-0 cost accounting: plan_slot0_cost_eur = slot0.price_eur_kwh * (slot0.bat_charge_kw + slot0.ev_charge_kw) * 0.25
    - Shadow log persistence: separate JSON file to avoid bloating main model file

key-files:
  created: []
  modified:
    - evcc-smartload/rootfs/app/rl_agent.py
    - evcc-smartload/rootfs/app/comparator.py

key-decisions:
  - "ResidualRLAgent outputs signed ct/kWh delta corrections on LP thresholds instead of full actions — agent never conflicts with LP safety guarantees"
  - "StratifiedReplayBuffer uses explicit MONTH_TO_SEASON mapping (Dec=winter) to avoid naive quarter-based indexing (Pitfall 3 from research)"
  - "model_version=2 field used as primary migration guard — detects old DQNAgent models and resets Q-table cleanly (N_ACTIONS 35->49)"
  - "compare_residual() uses slot-0 cost only, NOT plan.solver_fun (full 24h LP objective) — per Pitfall 2 from research"
  - "Comparator persistence version=2: old v1 format loads with graceful fallback (residual entries reset, legacy compare() data preserved)"
  - "Shadow corrections saved to separate RL_SHADOW_LOG_PATH to avoid bloating main model JSON"
  - "_DeprecatedDQNAgent kept as reference class (not imported by main.py)"

patterns-established:
  - "ResidualRL pattern: select_delta() -> apply_correction() -> calculate_reward(plan_cost, actual_cost)"
  - "Constraint audit: 4-check safety verification before shadow-to-advisory promotion"
  - "Seasonal replay: MONTH_TO_SEASON dict for correct DJF/MAM/JJA/SON classification"

requirements-completed: [LERN-01]

# Metrics
duration: 5min
completed: 2026-02-23
---

# Phase 8 Plan 01: ResidualRLAgent and Comparator Extension Summary

**ResidualRLAgent with 49-action delta correction space (+/-20ct on LP thresholds), stratified seasonal replay buffer, shadow/advisory mode with constraint audit, and slot-0 cost accounting in Comparator**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-23T21:29:59Z
- **Completed:** 2026-02-23T21:35:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Replaced DQNAgent (35 full actions) with ResidualRLAgent (49 delta corrections) — agent nudges LP thresholds by +/-20ct instead of selecting independent actions
- StratifiedReplayBuffer prevents seasonal forgetting by maintaining separate deques for winter/spring/summer/autumn, sampling equally from all non-empty seasons
- Shadow/advisory mode with formal 4-check constraint audit (SoC, departure, clip range, win-rate) and automatic promotion via maybe_promote()
- Extended Comparator with compare_residual() using correct slot-0 cost accounting, get_recent_comparisons() rolling window, cumulative_savings_eur(), avg_daily_savings()
- model_version=2 migration guard cleanly resets old DQNAgent Q-tables (N_ACTIONS changed 35->49)

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace DQNAgent with ResidualRLAgent class** - `dd16837` (feat)
2. **Task 2: Extend Comparator for slot-0 cost accounting and rolling windows** - `2444010` (feat)

## Files Created/Modified

- `evcc-smartload/rootfs/app/rl_agent.py` - ResidualRLAgent (49-action delta space), StratifiedReplayBuffer (4 seasonal deques), shadow/advisory mode, model_version=2 migration guard, _DeprecatedDQNAgent kept for reference
- `evcc-smartload/rootfs/app/comparator.py` - Extended with compare_residual(), get_recent_comparisons(), cumulative_savings_eur(), avg_daily_savings(); persistence version bumped to 2 with graceful v1 fallback

## Decisions Made

- Used explicit MONTH_TO_SEASON dict instead of `(month-1) // 3` to avoid December mapping to autumn (Pitfall 3 from research)
- plan_slot0_cost_eur must be slot-0 energy cost only — documented warning in compare_residual() docstring that plan.solver_fun is the full 24h LP objective and must NOT be used
- Shadow corrections logged to separate RL_SHADOW_LOG_PATH every 50 entries to avoid bloating the main model JSON file
- Class-level defaults added to ResidualRLAgent for `mode`, `shadow_start_timestamp`, `_shadow_corrections`, `_last_audit_result` to support `__new__()` instantiation pattern used by tests

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added class-level attribute defaults to ResidualRLAgent**

- **Found during:** Task 1 verification
- **Issue:** Test used `ResidualRLAgent.__new__(ResidualRLAgent)` to check hasattr() without calling `__init__`. Instance attributes set only in `__init__` return False for hasattr() when using `__new__`.
- **Fix:** Added class-level defaults (`mode: str = "shadow"`, etc.) so attributes are visible even on `__new__` instances.
- **Files modified:** evcc-smartload/rootfs/app/rl_agent.py
- **Verification:** Automated test `assert hasattr(agent, 'mode')` passes
- **Committed in:** dd16837 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Necessary for test compatibility — no behavior change, purely structural.

## Issues Encountered

- Windows cp1252 encoding prevented running Task 2 verification with `open()` (original comparator.py has non-ASCII emoji). Added explicit `encoding='utf-8'` — not a code issue, test environment artifact. Will run correctly on Linux container.

## Next Phase Readiness

- ResidualRLAgent ready for wiring into main.py (shadow mode gate, select_delta loop integration)
- Comparator ready for compare_residual() calls once main.py wires slot-0 cost values
- Phase 08-02 (SeasonalLearner + ForecastReliabilityTracker) can proceed independently
- Constraint: main.py must skip RL correction logging when override_active=True (Pitfall 5 from research — is_override_active param provided in log_shadow_correction())

---
*Phase: 08-residual-rl-and-learning*
*Completed: 2026-02-23*
