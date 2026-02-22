---
phase: 04-predictive-planner
verified: 2026-02-22T20:00:00Z
status: passed
score: 5/5 success-criteria verified
re_verification: false
---

# Phase 4: Predictive Planner Verification Report

**Phase Goal:** A rolling-horizon LP optimizer produces a 24-48h joint battery and EV dispatch plan every decision cycle, replacing all static euro price limits
**Verified:** 2026-02-22
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Every 15-min decision cycle, system produces a fresh PlanHorizon covering next 24-48h with per-slot dispatch decisions for battery and EV | VERIFIED | `main.py` lines 273-293: `horizon_planner.plan()` called unconditionally every loop iteration with fresh state, tariffs, and forecasts. PlanHorizon contains 96 DispatchSlots. |
| 2 | `ev_max_price_ct` and `battery_max_price_ct` no longer gate charging decisions; all grid-charging decisions come from LP plan | VERIFIED | No `if price <= battery_max_price_ct` gate in the main decision path. These values are passed as LP objective penalty inputs in `planner.py` lines 272-282. In main.py, they appear only in: startup log (line 52), config validation defaults (lines 69-74), and the separate `_run_bat_to_ev()` helper — not in the LP decision branch. |
| 3 | When real-world conditions diverge mid-cycle, next cycle's plan reflects updated inputs — old plans are never cached | VERIFIED | `planner.plan()` builds `price_96` fresh from `tariffs` every call (line 116). MPC receding-horizon re-initializes `bat_soc[0]` from `state.battery_soc` every cycle (line 315). No plan cache exists in the planner or main loop. `test_planner.py` TestHorizonPlannerPriceNoCache confirms different inputs produce different outputs. |
| 4 | If LP solver fails or times out, system falls back to holistic optimizer and logs a warning — never crashes | VERIFIED | `main.py` lines 284-293: `if plan is not None` → LP action, `else` → `optimizer.optimize(state, tariffs)`. `planner.plan()` has try/except wrapping entire body (line 134) returning None on any exception. `horizon_planner` initialization is also try/except (lines 121-128). `test_planner.py` Test 5 validates None return on infeasible LP. |
| 5 | Per-EV departure time from config or driver input is factored into plan so urgency windows are sized correctly | VERIFIED | `_get_departure_times(cfg)` in `main.py` (lines 416-427) reads `cfg.ev_charge_deadline_hour` and computes next deadline datetime. Passed to `horizon_planner.plan()` on line 281. `planner.py` `_solve_lp()` applies `_departure_slot()` to compute slot index and adds `ev_soc[dep_slot] >= target_soc` inequality constraint (lines 344-355). `test_planner.py` Test 3 validates urgent (3h) vs distant (12h) departure behavior. |

**Score:** 5/5 truths verified

---

## Required Artifacts

### Plan 01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `evcc-smartload/rootfs/app/optimizer/planner.py` | HorizonPlanner class with LP formulation and MPC loop; min 200 lines | VERIFIED | 554 lines. Contains `HorizonPlanner` class with all required methods: `plan()`, `_tariffs_to_96slots()`, `_solve_lp()`, `_extract_plan()`, `_check_ev_feasibility()`, `_departure_slot()`. |
| `evcc-smartload/rootfs/app/state.py` | PlanHorizon and DispatchSlot dataclasses | VERIFIED | `class DispatchSlot` at line 375, `class PlanHorizon` at line 391. All 11 DispatchSlot fields and 8 PlanHorizon fields present as specified. |
| `evcc-smartload/Dockerfile` | py3-scipy Alpine package installation | VERIFIED | Line 7: `py3-scipy` in `apk add --no-cache` block. Not pip — uses pre-compiled Alpine package as required. |

### Plan 02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `evcc-smartload/rootfs/app/state_store.py` | `update_plan()` and `get_plan()` methods | VERIFIED | `update_plan()` at line 109, `get_plan()` at line 118. Both guarded by `self._lock` (RLock). `_plan` field initialized at line 58. SSE payload includes `plan_summary` key at line 288. Snapshot includes plan metadata fields (lines 160-171). |
| `evcc-smartload/rootfs/app/main.py` | HorizonPlanner initialization, `plan()` call in decision loop, fallback chain, `_action_from_plan()`, `_get_departure_times()` | VERIFIED | `HorizonPlanner` import at line 35, init with try/except at lines 121-128, decision loop integration at lines 273-293, `_get_departure_times()` at lines 416-427, `_action_from_plan()` at lines 430-467. |

### Plan 03 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `evcc-smartload/rootfs/app/test_planner.py` | Integration tests for HorizonPlanner edge cases; min 100 lines | VERIFIED | 617 lines. 14 test methods across 7 TestCase classes covering: flat prices, price valley, EV urgency (urgent + distant), no-EV, solver failure (2 variants), short horizon (3 variants), SoC bounds (max + min), no-cache behavior. Self-contained with mock Config and SystemState; no external dependencies. |

---

## Key Link Verification

### Plan 01 Key Links

| From | To | Via | Status | Evidence |
|------|----|-----|--------|----------|
| `optimizer/planner.py` | `scipy.optimize.linprog` | LP solver call with `method='highs'` | VERIFIED | Line 391-400: `result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs", options={"time_limit": 10.0, ...})`. Pattern `linprog.*method.*highs` confirmed. Lazy import at line 224 inside `_solve_lp()`. |
| `optimizer/planner.py` | `state.py` | imports PlanHorizon, DispatchSlot | VERIFIED | Line 36: `from state import DispatchSlot, PlanHorizon, SystemState`. Pattern `from state import.*PlanHorizon` confirmed. |

### Plan 02 Key Links

| From | To | Via | Status | Evidence |
|------|----|-----|--------|----------|
| `main.py` | `optimizer/planner.py` | `horizon_planner.plan()` call in decision loop | VERIFIED | Lines 275-282: `plan = horizon_planner.plan(state=state, tariffs=tariffs, ...)`. Pattern `horizon_planner\.plan\(` confirmed. |
| `main.py` | `state_store.py` | `store.update_plan(plan)` after successful LP solve | VERIFIED | Line 286: `store.update_plan(plan)` called immediately after `plan is not None` check. Pattern `store\.update_plan\(` confirmed. |
| `main.py` | `optimizer/holistic.py` | fallback: `optimizer.optimize()` when plan is None | VERIFIED | Line 292: `lp_action = optimizer.optimize(state, tariffs)` in the `else` branch. Pattern `optimizer\.optimize\(` confirmed. |

### Plan 03 Key Links

| From | To | Via | Status | Evidence |
|------|----|-----|--------|----------|
| `test_planner.py` | `optimizer/planner.py` | import and instantiate HorizonPlanner for testing | VERIFIED | Line 203: `from optimizer.planner import HorizonPlanner`. Pattern `from optimizer.planner import HorizonPlanner` confirmed. Import isolation via `_patch_imports()` (lines 127-200) prevents real filesystem access. |

---

## Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|----------------|-------------|--------|----------|
| PLAN-01 | 04-01, 04-02, 04-03 | System creates a 24-48h rolling-horizon energy plan that jointly optimizes battery and EV | SATISFIED | `HorizonPlanner.plan()` produces `PlanHorizon` with 96 `DispatchSlot` objects covering joint battery (`bat_charge_kw`, `bat_discharge_kw`) and EV (`ev_charge_kw`) dispatch. Called every 15-min decision cycle in main.py. |
| PLAN-02 | 04-01, 04-02, 04-03 | Static euro charge limits (`ev_max_price_ct`, `battery_max_price_ct`) replaced by dynamic plan-based optimization | SATISFIED | Main loop's primary decision branch (lines 284-293 of main.py) uses `_action_from_plan(plan, state)` when LP succeeds. `battery_max_price_ct`/`ev_max_price_ct` appear only as LP objective penalty inputs in `planner.py` (making them LP soft bounds, not hard gates) and in config validation / bat-to-EV helper — not in the decision path. |

**Orphaned requirements check:** No additional requirements mapped to Phase 4 in REQUIREMENTS.md beyond PLAN-01 and PLAN-02.

---

## Anti-Patterns Found

No blockers or warnings found.

| File | Pattern | Severity | Notes |
|------|---------|----------|-------|
| `main.py` line 493 | `battery_max_price_ct` in `_run_bat_to_ev()` | INFO | Used to calculate battery-to-EV profitability in a separate optimization path (not the primary LP decision). This is correct usage — not a static price gate for charging decisions. |
| `main.py` lines 69-74 | `battery_max_price_ct`/`ev_max_price_ct` in config validation | INFO | Correct usage: applies safe defaults for invalid config values at startup. Not a decision gate. |

---

## Human Verification Required

The following items cannot be verified programmatically and require runtime validation in the container:

### 1. scipy import succeeds inside Alpine container

**Test:** Run `python3 -c "from scipy.optimize import linprog; print('OK')"` inside the running Docker container.
**Expected:** Prints `OK` without error.
**Why human:** Cannot execute Docker build or container commands in this verification context. The `py3-scipy` apk line is correct, but runtime confirmation of the Alpine musl-compatible library link requires container execution.

### 2. LP solver wall-clock time stays under 10 seconds

**Test:** Run `python -m unittest test_planner -v` from `evcc-smartload/rootfs/app/` inside the container; observe elapsed time for each test.
**Expected:** All 14 tests complete within 30 seconds total; no individual test times out.
**Why human:** Cannot execute scipy LP solver in this verification context. The `time_limit: 10.0` option is set in code; actual HiGHS performance on Alpine-compiled scipy requires runtime measurement.

### 3. Full test suite passes inside container

**Test:** `cd /app && python -m unittest test_planner -v` inside the running container.
**Expected:** 14 tests pass, 0 failures, 0 errors.
**Why human:** Tests were verified analytically against source code. Python is not available on the Windows development machine (runs only in the Alpine Docker container per SUMMARY.md notes).

---

## Gaps Summary

None. All 5 success criteria verified. All artifacts exist, are substantive, and are wired. All key links confirmed. Requirements PLAN-01 and PLAN-02 are fully satisfied. No placeholder or stub patterns found.

The only uses of `ev_max_price_ct`/`battery_max_price_ct` in `main.py` are:
1. Startup config log (informational)
2. Config validation defaults (startup only, not in loop)
3. `_run_bat_to_ev()` profitability helper (separate battery-to-EV path, not the primary LP decision)

None of these are static price gates on the primary charging decision path, which is now exclusively LP-driven with HolisticOptimizer fallback.

---

_Verified: 2026-02-22T20:00:00Z_
_Verifier: Claude (gsd-verifier)_
