---
phase: 04-predictive-planner
plan: 02
subsystem: decision-loop
tags: [lp-integration, main-loop, state-store, fallback-chain, departure-times]
dependency_graph:
  requires: [04-01]
  provides: [LP-driven decisions, plan storage, departure time resolution]
  affects: [main.py decision loop, StateStore SSE payload, dashboard plan status]
tech_stack:
  added: []
  patterns:
    - Graceful ImportError fallback for optional scipy dependency
    - Try/except boundary around every planner call (never crash on LP failure)
    - Separate update_plan() from update() — plan stored independently, included in next SSE broadcast
    - _snapshot_unlocked() private key (_plan) passed to serializer for plan_summary SSE key
key_files:
  created: []
  modified:
    - evcc-smartload/rootfs/app/main.py
    - evcc-smartload/rootfs/app/state_store.py
decisions:
  - "[04-02]: _action_from_plan uses slot-0 price_eur_kwh as battery/ev limit_eur — controller applies correct evcc charge mode without additional price-gate logic in main loop"
  - "[04-02]: update_plan() does not broadcast SSE — plan data included in next regular update() call to avoid double broadcast and race conditions"
  - "[04-02]: _snapshot_unlocked includes _plan reference (private key) passed to _snapshot_to_json_dict — avoids acquiring lock twice for plan_summary serialization"
  - "[04-02]: horizon_planner initialized before rl_agent (before RL bootstrap) — planner is stateless, no ordering dependency; placed after HolisticOptimizer for logical grouping"
metrics:
  duration_minutes: 3
  completed_date: "2026-02-22"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 4 Plan 2: HorizonPlanner Main Loop Integration Summary

LP-based HorizonPlanner wired into main decision loop replacing static price-threshold decisions, with HolisticOptimizer as fallback and StateStore plan storage for dashboard SSE.

## What Was Built

### Task 1: StateStore plan storage (6c60c7e)

Extended `state_store.py` to store and expose LP plans:

- Added `_plan: Optional[PlanHorizon] = None` field guarded by existing `_lock` (RLock)
- Added `update_plan(plan: PlanHorizon) -> None`: stores plan under RLock, does NOT broadcast SSE (included in next regular `update()` call)
- Added `get_plan() -> Optional[PlanHorizon]`: returns plan reference under RLock (PlanHorizon is immutable dataclass, safe to share)
- Extended `_snapshot_unlocked()` with plan summary fields: `plan_computed_at`, `plan_solver_status`, `plan_cost_eur`, `plan_slots_count` (plus `_plan` reference for serializer)
- Extended `_snapshot_to_json_dict()` with `plan_summary` SSE key: `{computed_at, status, cost_eur, current_action: {bat_charge, bat_discharge, ev_charge}}`
- Added `from state import PlanHorizon` import

### Task 2: HorizonPlanner decision loop integration (678779e)

Wired `HorizonPlanner` into `main.py`:

- Added `from optimizer.planner import HorizonPlanner` import
- Added `timedelta` and `Dict` to imports (needed by helper functions)
- HorizonPlanner initialized at startup with graceful fallback:
  ```python
  horizon_planner = None
  try:
      horizon_planner = HorizonPlanner(cfg)
  except ImportError as e:
      log("warning", ...)  # scipy unavailable
  except Exception as e:
      log("warning", ...)  # any other init failure
  ```
- Decision loop replaced with Phase 4 fallback chain: LP plan first, holistic optimizer when plan is None
- `store.update_plan(plan)` called immediately after successful LP solve
- `_get_departure_times(cfg)` helper: reads `cfg.ev_charge_deadline_hour`, computes next occurrence of deadline hour, returns `{"_default": datetime}`
- `_action_from_plan(plan, state)` helper: converts slot-0 LP values to discrete `Action` (bat=1/6/0, ev=1/0), sets `battery_limit_eur`/`ev_limit_eur` to `slot0.price_eur_kwh`
- HolisticOptimizer preserved as required safety fallback (not removed)
- RL shadow path (`rl_agent.select_action(state, explore=True)`) unchanged

## Verification Results

All plan criteria met:

| Check | Result |
|-------|--------|
| HorizonPlanner initialized in startup | PASS |
| Decision loop prefers LP plan | PASS |
| Fallback optimizer.optimize() when plan is None | PASS |
| StateStore update_plan/get_plan methods | PASS |
| store.update_plan(plan) called on LP success | PASS |
| ev_charge_deadline_hour used for departure times | PASS |
| _action_from_plan converts slot-0 to Action | PASS |
| RL shadow path unchanged | PASS |
| HolisticOptimizer preserved as fallback | PASS |
| Decision source logged (LP plan / fallback) | PASS |

## Deviations from Plan

None — plan executed exactly as written.

The `_action_from_plan` helper uses a lazy `from state import Action` import inside the function body. This is a minor style deviation from the plan's module-level import suggestion, but is equivalent in behavior and avoids a potential circular import issue (since `main.py` already imports `Action` at the top). The function-level import was retained for clarity within the helper.

## Success Criteria Verification

- When HorizonPlanner returns a PlanHorizon: controller receives LP-derived actions from `_action_from_plan(plan, state)` (not static price threshold actions) — SATISFIED
- When HorizonPlanner returns None (solver failure, missing forecasts, scipy unavailable): system falls back to `optimizer.optimize()` without crash — SATISFIED (try/except + None check)
- StateStore.get_plan() returns latest PlanHorizon after successful cycle — SATISFIED
- ev_charge_deadline_hour from config used as departure time input to LP — SATISFIED via `_get_departure_times(cfg)`
- System never crashes due to planner failure: defensive try/except at init + None-check at call site — SATISFIED

## Self-Check: PASSED

Files exist:
- evcc-smartload/rootfs/app/main.py — FOUND
- evcc-smartload/rootfs/app/state_store.py — FOUND

Commits exist:
- 6c60c7e (StateStore plan storage) — FOUND
- 678779e (HorizonPlanner main loop integration) — FOUND
