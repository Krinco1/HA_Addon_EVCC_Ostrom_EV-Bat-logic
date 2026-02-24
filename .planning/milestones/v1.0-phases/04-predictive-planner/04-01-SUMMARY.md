---
phase: 04-predictive-planner
plan: "01"
subsystem: optimizer
tags: [lp, scipy, highs, mpc, battery, ev, dispatch]
dependency_graph:
  requires: []
  provides: [HorizonPlanner, PlanHorizon, DispatchSlot]
  affects: [optimizer/__init__.py, state.py, Dockerfile]
tech_stack:
  added: [scipy.optimize.linprog, py3-scipy (Alpine apk)]
  patterns: [rolling-horizon MPC, LP joint dispatch, SoC equality constraints, lazy scipy import]
key_files:
  created:
    - evcc-smartload/rootfs/app/optimizer/planner.py
  modified:
    - evcc-smartload/rootfs/app/state.py
    - evcc-smartload/rootfs/app/optimizer/__init__.py
    - evcc-smartload/Dockerfile
decisions:
  - "Lazy scipy import inside _solve_lp() prevents ImportError at module load time if scipy not yet available"
  - "PV surplus reduces effective LP objective price coefficient proportionally to coverage ratio (Pitfall 3 mitigation)"
  - "Mutual exclusion guard bat_charge[t] + bat_discharge[t] <= P_max prevents LP degeneracy at unit efficiency (Open Question 1)"
  - "EV infeasibility pre-check logs informative warning before LP call rather than relying solely on LP status=2"
  - "Heavy price penalty (10x) for charging above config max price — acts as LP soft bound matching user's ev_max_price_ct / battery_max_price_ct intent"
metrics:
  duration: 4 min
  completed: 2026-02-22
  tasks_completed: 2
  files_changed: 4
---

# Phase 4 Plan 1: HorizonPlanner LP Engine Summary

**One-liner:** 96-slot joint battery+EV LP dispatch planner using scipy/HiGHS with SoC equality constraints and MPC receding-horizon pattern.

## What Was Built

### Task 1: Dockerfile + PlanHorizon/DispatchSlot dataclasses

Added `py3-scipy` to the Alpine `apk add` line in the Dockerfile (not pip — avoids musl compilation). Added two new dataclasses to `state.py` in a new "Predictive Planner data structures" section after the existing solar surplus helpers:

- `DispatchSlot`: 11-field per-slot decision container (slot_index, slot_start, bat_charge_kw, bat_discharge_kw, ev_charge_kw, ev_name, price_eur_kwh, pv_kw, consumption_kw, bat_soc_pct, ev_soc_pct)
- `PlanHorizon`: 8-field rolling plan container (computed_at, slots, solver_status, solver_fun, current_bat_charge, current_bat_discharge, current_ev_charge, current_price_limit)

### Task 2: HorizonPlanner LP formulation (optimizer/planner.py)

Created a 556-line `HorizonPlanner` class with:

- `plan()`: Public entry point. Converts tariffs → 96 price slots, pre-checks EV feasibility, calls `_solve_lp()`, extracts `PlanHorizon`. Returns None on any failure (triggers HolisticOptimizer fallback).
- `_tariffs_to_96slots()`: Reuses `holistic.py` tariff parsing pattern. Expands hourly prices to 4x 15-min slots. Returns None for < 32 slots (< 8h of price data). Pads to 96 with last known price.
- `_solve_lp()`: Builds LP with N_vars=5T+2=482 variables. Battery/EV SoC dynamics as equality constraints. EV departure time as inequality constraint. Mutual exclusion guard for simultaneous charge/discharge. Config max-price as 10x heavy penalty objective coefficient. PV surplus reduces effective grid cost coefficient. Calls `linprog` with `method='highs'` and `time_limit=10.0`. Returns result on status==0, None on failure.
- `_extract_plan()`: Clips all LP result values with `np.clip` (Pitfall 5 mitigation). Builds 96 `DispatchSlot` objects. Determines current-slot boolean actions using 0.1 kW threshold.
- `_check_ev_feasibility()`: Pre-solve check with informative warning log when departure constraint is physically infeasible.
- `_departure_slot()`: Static helper — `max(1, min(95, int(delta_minutes/15)))`.

Updated `optimizer/__init__.py` to export `HorizonPlanner`.

## Verification Results

All must_haves confirmed:

| Check | Result |
|-------|--------|
| `from state import PlanHorizon, DispatchSlot` | PASS — classes present at lines 374-405 |
| `from optimizer.planner import HorizonPlanner` | PASS — exported in __init__.py |
| Dockerfile contains `py3-scipy` via apk | PASS — line 8 of Dockerfile |
| `__init__.py` exports HorizonPlanner | PASS — `__all__` updated |
| `HorizonPlanner.plan()` returns `Optional[PlanHorizon]` | PASS — returns None on failure, PlanHorizon on success |
| scipy lazy-imported (not at module level) | PASS — `from scipy.optimize import linprog` inside `_solve_lp()` |
| `from state import.*PlanHorizon` pattern | PASS — line 36 |
| `linprog.*method.*highs` pattern | PASS — line 398 |
| planner.py min_lines=200 | PASS — 556 lines |
| state.py contains `class PlanHorizon` | PASS — line 391 |

## Key Decisions Made

1. **Lazy scipy import**: `from scipy.optimize import linprog` placed inside `_solve_lp()`, not at module level. Prevents `ImportError` if scipy is not yet installed in the container at Python module load time.

2. **PV surplus cost reduction**: Instead of a separate PV variable (which would add T more decision variables), PV surplus reduces the grid price coefficient in the objective: `effective_price = price[t] * (1 - min(1.0, pv_surplus_kw / P_bat_max))`. This correctly models free PV energy without adding variable complexity.

3. **Config max-price as LP objective penalty**: `ev_max_price_ct` and `battery_max_price_ct` are enforced as 10x objective coefficient penalties when price exceeds user limit. This makes charging above the user's configured max price undesirable to the LP without making the problem infeasible (avoids LP status=2 on tight price markets).

4. **Mutual exclusion guard**: Added `bat_charge[t] + bat_discharge[t] <= P_max` inequality constraint for all T slots. Addresses Research Open Question 1 — prevents LP degeneracy when `eta_c == eta_d == 1.0`.

5. **EV infeasibility pre-check**: Logs a clear warning before the LP solve if physical power limits cannot meet the departure SoC target. LP still attempts to solve (may relax constraint if SoC bounds allow, otherwise returns status=2 and plan() returns None → HolisticOptimizer fallback).

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

Files exist:
- FOUND: evcc-smartload/rootfs/app/optimizer/planner.py
- FOUND: evcc-smartload/rootfs/app/state.py (modified)
- FOUND: evcc-smartload/rootfs/app/optimizer/__init__.py (modified)
- FOUND: evcc-smartload/Dockerfile (modified)

Commits exist:
- FOUND: 6ab8e15 — feat(04-01): add scipy to Dockerfile and PlanHorizon/DispatchSlot dataclasses
- FOUND: 8d2a309 — feat(04-01): implement HorizonPlanner LP engine with scipy/HiGHS
