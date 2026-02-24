---
status: complete
phase: 04-predictive-planner
source: [04-01-SUMMARY.md, 04-02-SUMMARY.md, 04-03-SUMMARY.md]
started: 2026-02-22T20:00:00Z
updated: 2026-02-22T20:15:00Z
---

## Current Test

[testing complete]

## Tests

### 1. scipy installed via apk (not pip)
expected: Dockerfile contains `py3-scipy` in the `apk add` line — NOT a `pip install scipy` line.
result: pass

### 2. PlanHorizon and DispatchSlot dataclasses exist in state.py
expected: `state.py` contains `@dataclass` classes `PlanHorizon` (8 fields: computed_at, slots, solver_status, solver_fun, current_bat_charge, current_bat_discharge, current_ev_charge, current_price_limit) and `DispatchSlot` (11 fields including bat_charge_kw, bat_discharge_kw, ev_charge_kw, bat_soc_pct, ev_soc_pct).
result: pass

### 3. HorizonPlanner LP uses scipy linprog with HiGHS and time_limit
expected: `planner.py` calls `linprog()` with `method='highs'` and `options={'time_limit': 10.0}`. The import is lazy (inside `_solve_lp()`, not at module level).
result: pass

### 4. LP fallback returns None on solver failure
expected: When `linprog` returns status != 0, `_solve_lp()` returns None. The `plan()` method wraps everything in try/except and returns None on any exception — never raises.
result: pass

### 5. Main loop calls HorizonPlanner before HolisticOptimizer
expected: In `main.py`, the decision loop calls `horizon_planner.plan()` first. If plan is not None, `_action_from_plan(plan, state)` derives the Action. If plan is None, falls back to `optimizer.optimize()`. Both paths produce a valid Action without crashing.
result: pass

### 6. Static price limits no longer gate decisions when LP succeeds
expected: `ev_max_price_ct` and `battery_max_price_ct` are NOT used as if/else gates in the main decision path. They appear only as LP objective penalty coefficients in `planner.py` and in config logging/validation — not as `if price < max_price` checks controlling charge decisions in `main.py`.
result: pass

### 7. StateStore has update_plan() and get_plan() with thread safety
expected: `state_store.py` has `update_plan(plan)` and `get_plan()` methods, both acquiring `_lock` (RLock). The SSE snapshot includes a `plan_summary` key with `computed_at`, `status`, `cost_eur`, and `current_action`.
result: pass

### 8. Departure time from config passed to planner
expected: `main.py` has `_get_departure_times(cfg)` that reads `cfg.ev_charge_deadline_hour` and computes the next occurrence as a datetime. This dict is passed to `horizon_planner.plan()`. In `planner.py`, the departure time creates an LP inequality constraint on EV SoC at the departure slot.
result: pass

### 9. HorizonPlanner graceful init when scipy unavailable
expected: In `main.py`, `HorizonPlanner(cfg)` is wrapped in try/except ImportError + except Exception. If scipy is missing, `horizon_planner` is set to None and a warning is logged — the system continues with HolisticOptimizer only.
result: pass

### 10. Test suite covers all 7 required scenarios
expected: `test_planner.py` contains tests for: (1) basic LP solve with 96 slots, (2) price valley triggers battery charging, (3) EV departure urgency, (4) no-EV produces zero EV charge, (5) solver failure returns None, (6) SoC bounds respected, (7) different prices produce different plans. File is 600+ lines with 14 test methods.
result: pass

## Summary

total: 10
passed: 10
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
