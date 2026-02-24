# Phase 4: Predictive Planner - Research

**Researched:** 2026-02-22
**Domain:** Linear programming (LP), rolling-horizon MPC, joint battery + EV dispatch optimization, scipy/HiGHS on Alpine Linux
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PLAN-01 | System erstellt einen 24-48h Rolling-Horizon Energieplan der Batterie und EV gemeinsam optimiert | scipy.optimize.linprog (HiGHS) confirmed available on Alpine via `apk add py3-scipy`; 96-slot LP formulation with SoC dynamics and joint battery+EV decision variables documented; MPC rolling loop pattern established |
| PLAN-02 | Statische Euro-Ladegrenzen (ev_max_price_ct, battery_max_price_ct) werden durch dynamische planbasierte Optimierung ersetzt | LP output (DispatchSlot per slot) replaces price-threshold gating; controller.apply() receives plan-derived Action objects; config params retained as fallback bounds only; StateStore.update_plan() extension documented |
</phase_requirements>

---

## Summary

Phase 4 introduces a `HorizonPlanner` that runs `scipy.optimize.linprog` (HiGHS backend) every 15-minute decision cycle to produce a rolling 24-48h dispatch schedule for the battery and all connected EVs. The LP operates on 96 decision slots (15-min resolution) and directly outputs per-slot charge/discharge decisions. These decisions replace the static `ev_max_price_ct` and `battery_max_price_ct` price-gate logic in `HolisticOptimizer`; the existing optimizer becomes the fallback when the LP fails or times out.

The LP formulation is purely continuous (no MILP) to keep solve times under 1 second on a Raspberry Pi: simultaneous charge+discharge is prevented via non-negative variable split (charge_kw ≥ 0, discharge_kw ≥ 0) rather than Boolean flags. SoC dynamics are encoded as equality constraints linking adjacent slots. The departure-time constraint for EVs is an equality (or inequality) constraint on the SoC variable at the slot corresponding to the configured departure time. The planner receives 96-slot price, PV, and consumption vectors from Phase 3 forecasters already wired into the main loop.

`scipy 1.17.0` is the version in Alpine edge community (`apk add py3-scipy`), which ships the HiGHS backend. The `time_limit` option in the HiGHS options dict provides a hard timeout. If `result.status != 0` (solver failure) or an exception occurs, the system logs a warning and falls back to `HolisticOptimizer.optimize()`. Plans are never cached — every 15-min cycle produces a fresh plan from the current state. The `StateStore` gains a `update_plan()` method that stores the current `PlanHorizon` for dashboard and SSE use.

**Primary recommendation:** Implement `HorizonPlanner` in `/app/optimizer/planner.py` using `scipy.optimize.linprog` with `method='highs'` and `options={'time_limit': 10.0}`. Build constraint matrices with `numpy` arrays (not sparse — at 96 slots the dense matrices are ~100KB, well within Pi memory). Wire it into `main.py` before `HolisticOptimizer` and use the existing `Action` dataclass output for `controller.apply()`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `scipy.optimize.linprog` | 1.17.0 (Alpine apk) | LP solver with HiGHS backend | Confirmed available via `apk add py3-scipy`; HiGHS is the fastest LP solver in SciPy; no glibc requirement |
| `numpy` | already installed | Constraint matrix construction, vector operations | Already in container; required by scipy anyway |
| `scipy` (via `apk add py3-scipy`) | 1.17.0-r1 | Entire SciPy stack including linprog | Pre-compiled musl-compatible binary; avoids pip build-from-source complexity |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `datetime` (stdlib) | stdlib | Slot-to-index mapping, departure time arithmetic | Every cycle for timestamp → slot-index conversion |
| `threading.Lock` (stdlib) | stdlib | Protect `_current_plan` in StateStore from concurrent reads | Same pattern as ManualSocStore and ConsumptionForecaster |
| `dataclasses` (stdlib) | stdlib | `PlanHorizon`, `DispatchSlot` data structures | Clean typed containers for plan output |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `scipy.optimize.linprog` (HiGHS) | PuLP + CBC | PuLP not in Alpine apk; CBC must be built from source; no benefit over HiGHS for pure LP |
| `scipy.optimize.linprog` (HiGHS) | PyPSA / linopy | PyPSA requires pandas + networkx (heavy); overkill for single-home optimization |
| `scipy.optimize.linprog` (HiGHS) | GLPK via `py3-glpk` apk | GLPK is slower than HiGHS for LP; HiGHS is already in scipy |
| Dense numpy arrays for constraints | `scipy.sparse.csr_matrix` | At 96 slots the constraint matrix is ~300×300 (dense ~720KB float64) — sparse adds complexity without memory benefit on Raspberry Pi |
| Continuous LP (charge + discharge split) | MILP with Boolean charge/discharge flags | MILP requires integer branching; solve time on Pi could exceed 15 min; continuous LP prevents simultaneous charge+discharge via separate non-negative vars, which is sufficient for this use case |

**Installation (add to Dockerfile):**
```dockerfile
RUN apk add --no-cache \
    py3-scipy
```

Note: `py3-scipy` depends on `openblas`, `libgfortran`, `libstdc++` — all handled by Alpine package manager automatically. No `pip install` needed; this avoids musl compilation issues.

---

## Architecture Patterns

### Recommended Project Structure

```
/app/
├── optimizer/
│   ├── __init__.py          # export HolisticOptimizer, EventDetector, HorizonPlanner
│   ├── holistic.py          # (existing) fallback optimizer — unchanged
│   ├── events.py            # (existing) EventDetector — unchanged
│   └── planner.py           # NEW: HorizonPlanner (LP formulation + MPC loop)
├── state_store.py           # extend: add _plan, update_plan(), plan in snapshot()
├── state.py                 # extend: add PlanHorizon, DispatchSlot dataclasses
├── config.py                # extend: add departure_time config per vehicle (optional)
└── main.py                  # wire: call planner.plan() before holistic.optimize()
```

### Pattern 1: LP Variable Layout (96-slot joint formulation)

**What:** Pack all decision variables for all assets into a single flat vector `x` of length `N_vars`. Index ranges are computed once per solve and used to slice `x` for constraints and objective.

**When to use:** Every 15-minute decision cycle. The same variable layout is used whether or not an EV is connected — EV variables are clamped to 0 via bounds when not connected.

**Variable layout (example with 1 EV, 96 slots = T=96):**

```python
# Source: standard LP formulation pattern for energy management MPC
T = 96  # 15-min slots in 24h

# Decision variables (all continuous, non-negative):
# bat_charge[t]    t=0..T-1   kW battery charge power at slot t
# bat_discharge[t] t=0..T-1   kW battery discharge power at slot t
# ev_charge[t]     t=0..T-1   kW EV charge power at slot t (per EV)
# bat_soc[t]       t=0..T     % battery SoC (auxiliary, T+1 values)
# ev_soc[t]        t=0..T     % EV SoC (auxiliary, T+1 values, per EV)

# Index offsets:
i_bat_chg = 0              # bat_charge:    [0, T)
i_bat_dis = T              # bat_discharge: [T, 2T)
i_ev_chg  = 2*T            # ev_charge:     [2T, 3T)
i_bat_soc = 3*T            # bat_soc:       [3T, 3T+T+1)
i_ev_soc  = 3*T + (T+1)   # ev_soc:        [3T+T+1, 3T+2T+2)
N_vars = 3*T + 2*(T+1)    # total = 5*T + 2 = 482 for T=96
```

**Objective (minimize cost):**

```python
# Source: scipy.optimize.linprog convention (minimization)
# Objective: sum over t of price[t] * (bat_charge[t] + ev_charge[t])
#            - feed_in[t] * bat_discharge[t]
# (discharge earns feed-in revenue, so negative cost)
c = np.zeros(N_vars)
for t in range(T):
    c[i_bat_chg + t] = price_eur_per_kwh[t]   # grid cost for bat charge
    c[i_ev_chg  + t] = price_eur_per_kwh[t]   # grid cost for EV charge
    c[i_bat_dis + t] = -feed_in_eur_per_kwh    # revenue from discharge
```

**SoC dynamics (equality constraints — banded structure):**

```python
# Battery SoC: soc[t+1] = soc[t] + (charge[t]*eta_c - discharge[t]/eta_d) * dt / capacity
# As equality: soc[t+1] - soc[t] - charge[t]*eta_c*dt/cap + discharge[t]*dt/(eta_d*cap) = 0
dt_h = 0.25  # 15 minutes = 0.25 hours
eta_c = cfg.battery_charge_efficiency
eta_d = cfg.battery_discharge_efficiency
cap = cfg.battery_capacity_kwh

A_eq_rows = []
b_eq = []
# SoC dynamics for t=0..T-1:
for t in range(T):
    row = np.zeros(N_vars)
    row[i_bat_soc + t + 1] = 1.0     # soc[t+1]
    row[i_bat_soc + t]     = -1.0    # -soc[t]
    row[i_bat_chg + t]     = -eta_c * dt_h / cap   # charge contribution
    row[i_bat_dis + t]     = 1.0 / (eta_d * cap) * dt_h  # discharge cost
    A_eq_rows.append(row)
    b_eq.append(0.0)

# Initial SoC constraint:
row = np.zeros(N_vars)
row[i_bat_soc] = 1.0
A_eq_rows.append(row)
b_eq.append(current_bat_soc / 100.0)  # fraction

# Same pattern for EV SoC dynamics...
```

**Departure constraint (EV must reach target SoC by departure slot):**

```python
# Source: standard EV charging LP pattern
# departure_slot = index of slot at or before departure time
# EV SoC at departure must be >= target_soc
# As inequality: -ev_soc[departure_slot] <= -target_soc/100
row = np.zeros(N_vars)
row[i_ev_soc + departure_slot] = -1.0
A_ub_rows.append(row)
b_ub.append(-target_soc / 100.0)
```

**Bounds:**

```python
bounds = ([(0, cfg.battery_charge_power_kw)] * T      # bat_charge: [0, P_max]
        + [(0, cfg.battery_charge_power_kw)] * T      # bat_discharge: [0, P_max]
        + [(0, ev_charge_power_kw)] * T                # ev_charge: [0, P_ev]
        + [(cfg.battery_min_soc/100, cfg.battery_max_soc/100)] * (T+1)  # bat_soc
        + [(0, 1.0)] * (T+1))                          # ev_soc: [0, 100%]

# If EV not connected: clamp ev_charge to 0
if not ev_connected:
    for t in range(T):
        bounds[i_ev_chg + t] = (0, 0)
```

### Pattern 2: Rolling-Horizon MPC Loop

**What:** Every 15-min cycle: collect current state → build LP from scratch using current SoC, prices, forecasts, departure time → solve → extract current-slot decision → apply to controller. The plan covers the full horizon but only the first slot's decision is applied (MPC "receding horizon" principle).

**When to use:** This is the core `HorizonPlanner.plan()` call in the main loop.

```python
# Source: MPC pattern from academic literature + codebase adaptation
class HorizonPlanner:
    def plan(self, state: SystemState, tariffs: List[Dict],
             consumption_96: List[float], pv_96: List[float],
             ev_departure_times: Dict[str, datetime]) -> Optional[PlanHorizon]:
        """
        Solve LP for the next 24h horizon. Returns PlanHorizon on success,
        None on solver failure (triggers fallback to HolisticOptimizer).

        Never caches: called fresh every cycle with current state.
        """
        try:
            price_96 = self._tariffs_to_96slots(tariffs)
            result = self._solve_lp(state, price_96, consumption_96, pv_96,
                                    ev_departure_times)
            if result is None or not result.success:
                log("warning", f"HorizonPlanner: LP failed (status={getattr(result,'status','exc')}), "
                               "falling back to HolisticOptimizer")
                return None
            return self._extract_plan(result, price_96, state)
        except Exception as e:
            log("warning", f"HorizonPlanner: exception in LP solve: {e}, falling back")
            return None

    def _solve_lp(self, state, price_96, consumption_96, pv_96,
                  ev_departure_times):
        # Build c, A_ub, b_ub, A_eq, b_eq, bounds from current state
        # ...
        from scipy.optimize import linprog
        return linprog(
            c, A_ub=A_ub, b_ub=b_ub,
            A_eq=A_eq, b_eq=b_eq,
            bounds=bounds,
            method='highs',
            options={'time_limit': 10.0, 'disp': False, 'presolve': True}
        )
```

### Pattern 3: PlanHorizon and DispatchSlot Data Structures

**What:** Typed containers for the LP output that StateStore stores and Phase 6 (transparency) and Phase 7 (driver interaction) consume.

```python
# Source: new dataclass in state.py (extend existing module)
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

@dataclass
class DispatchSlot:
    """Decision for one 15-min slot in the horizon."""
    slot_index: int              # 0..95 (0 = current slot)
    slot_start: datetime         # UTC timestamp of slot start
    bat_charge_kw: float         # kW battery charges from grid (0 if not charging)
    bat_discharge_kw: float      # kW battery discharges to home (0 if not discharging)
    ev_charge_kw: float          # kW EV charges from grid (per EV)
    ev_name: str                 # which EV (empty if no EV)
    price_eur_kwh: float         # grid price for this slot
    pv_kw: float                 # PV generation forecast for this slot
    consumption_kw: float        # expected house consumption for this slot
    bat_soc_pct: float           # battery SoC at start of slot (from LP)
    ev_soc_pct: float            # EV SoC at start of slot (from LP)

@dataclass
class PlanHorizon:
    """Complete rolling-horizon plan for the next 24h."""
    computed_at: datetime        # when this plan was computed
    slots: List[DispatchSlot]    # 96 slots (or fewer if price data short)
    solver_status: int           # linprog result.status (0=optimal)
    solver_fun: float            # objective value (total cost in EUR)
    # Current-slot action (for immediate controller.apply() use):
    current_bat_charge: bool     # True if battery should charge this slot
    current_bat_discharge: bool  # True if battery should discharge this slot
    current_ev_charge: bool      # True if EV should charge this slot
    current_price_limit: float   # effective price limit for this slot (EUR/kWh)
```

### Pattern 4: Main Loop Integration (replacing static price limits)

**What:** In `main.py`, call `horizon_planner.plan()` first. If it returns a `PlanHorizon`, derive the `Action` from the plan's current slot. If it returns `None`, fall back to `lp_action = optimizer.optimize()` (HolisticOptimizer). The `ev_max_price_ct` and `battery_max_price_ct` config params are removed from the Action selection path but retained as fallback bounds in the LP.

```python
# Source: main.py decision loop — proposed modification
# --- Phase 4: Predictive Planner (LP-based) ---
plan = None
if horizon_planner is not None:
    plan = horizon_planner.plan(
        state, tariffs,
        consumption_96=consumption_96,
        pv_96=pv_96,
        ev_departure_times=_get_departure_times(cfg, driver_mgr),
    )

if plan is not None:
    # LP plan succeeded: derive Action from current slot
    lp_action = _action_from_plan(plan, state)
    store.update_plan(plan)          # store for dashboard
else:
    # LP failed or planner not ready: fall back to HolisticOptimizer
    lp_action = optimizer.optimize(state, tariffs)

# RL shadow decision is unchanged (still trains on LP output)
rl_action = rl_agent.select_action(state, explore=True)
```

### Pattern 5: StateStore.update_plan() Extension

**What:** Extend `StateStore` with a `_plan` field and `update_plan()` / `get_plan()` methods. The plan is stored separately from the 15-min state update to allow dashboard reads without re-solving.

```python
# Source: state_store.py extension following existing RLock pattern
class StateStore:
    def __init__(self):
        # ... existing fields ...
        self._plan: Optional[PlanHorizon] = None  # NEW

    def update_plan(self, plan: PlanHorizon) -> None:
        """Store the latest plan. Called from main loop after successful LP solve."""
        with self._lock:
            self._plan = plan
        # No SSE broadcast here — plan included in next regular update()

    def get_plan(self) -> Optional[PlanHorizon]:
        """Return current plan snapshot. Thread-safe."""
        with self._lock:
            return self._plan  # PlanHorizon is immutable after construction
```

### Pattern 6: Departure Time Resolution

**What:** Per-EV departure time sourced in priority order: (1) driver reply via Telegram (Phase 7, future), (2) `ev_charge_deadline_hour` from config (existing field), (3) default 24h from now. Phase 4 uses (2) and (3) only; Phase 7 will add (1).

```python
def _get_departure_times(cfg: Config, driver_mgr: DriverManager) -> Dict[str, datetime]:
    """Return departure datetime per EV name for LP formulation.

    Phase 4: uses cfg.ev_charge_deadline_hour as the single deadline.
    Phase 7 will extend this with per-driver Telegram input.
    """
    now = datetime.now(timezone.utc)
    deadline_hour = cfg.ev_charge_deadline_hour  # e.g. 6 (06:00 local)

    # Convert to UTC datetime for today or tomorrow
    local_deadline = now.replace(hour=deadline_hour, minute=0, second=0, microsecond=0)
    if local_deadline <= now:
        local_deadline += timedelta(days=1)

    # For Phase 4: single departure time applied to all EVs
    # Phase 7 will provide per-EV departure times from DriverManager
    return {"_default": local_deadline}
```

### Anti-Patterns to Avoid

- **Caching the LP plan across cycles:** Each 15-min cycle MUST re-solve from scratch with fresh prices, SoC, and forecasts. The rolling horizon is "open loop" — never re-use a previous plan.
- **Using MILP (integrality=1) for charge/discharge mutual exclusion:** Solving time is 10-100x slower than LP on Raspberry Pi. Use separate non-negative variables (`bat_charge`, `bat_discharge`) instead — the LP will not simultaneously charge and discharge when prices are uniform (same cost on both sides), and the objective will never prefer it when asymmetric.
- **Building constraint matrices row-by-row with Python lists then converting:** Build in numpy directly using index arithmetic. Constructing row-by-row is O(N²) in memory reallocation.
- **Setting `time_limit` to None:** Always set a timeout. HiGHS rarely needs more than 1 second for 96-slot LP, but a malformed constraint matrix can cause it to iterate indefinitely.
- **Replacing the HolisticOptimizer entirely:** The holistic optimizer is the required fallback for LP failures. Keep it intact and unchanged in Phase 4.
- **Accessing `result.x` when `result.status != 0`:** HiGHS may return a partial solution even on failure. Always gate on `result.status == 0` and `result.success == True` before extracting variables.
- **Treating `ev_max_price_ct` and `battery_max_price_ct` as obsolete:** These config values serve as upper bounds in the LP (the LP will never charge the battery at a price above `battery_max_price_ct`). They are input parameters to the LP, not price-gate thresholds. The LP replaces the *gating logic*, not the user's price preferences.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LP solver | Custom greedy/heuristic 96-slot optimizer | `scipy.optimize.linprog` (HiGHS) | HiGHS is a state-of-the-art LP solver; custom greedy will miss globally optimal charge windows |
| Simultaneous charge/discharge prevention | Boolean MILP flag per slot | Non-negative variable split (charge_kw ≥ 0, discharge_kw ≥ 0 separately) | LP naturally avoids simultaneous charge+discharge when efficiency < 1 (roundtrip loss makes it unprofitable) |
| Timeout mechanism | `signal.alarm()` or `threading.Timer` | `options={'time_limit': 10.0}` in linprog | HiGHS has built-in time limit; no signal/thread overhead required |
| Sparse matrix construction | Manual sparse dict format | `numpy` dense arrays for T=96 (small enough) | At 96 slots, the A_eq matrix is ~200×500 floats = ~800KB — dense is faster to construct and passes to HiGHS unchanged |
| Departure-slot index calculation | Hardcoded hour offsets | `datetime` arithmetic → slot index via `(hour*60+minute)//15` | Same `_slot_index()` helper used in ConsumptionForecaster |

**Key insight:** The LP formulation at 96 slots is small by LP standards. HiGHS will solve it in 10-100ms on a Raspberry Pi 4. The implementation challenge is correct constraint matrix construction, not solver performance.

---

## Common Pitfalls

### Pitfall 1: Infeasible LP Due to Tight SoC + Departure Constraints

**What goes wrong:** If the EV current SoC is 20%, target is 80%, and departure is in 2 hours (8 slots), but the max charge power for those 8 slots can only deliver 30% SoC, the LP is infeasible — no solution satisfies the departure constraint.

**Why it happens:** Departure constraint forces `ev_soc[departure_slot] >= 0.80`, but the power bounds physically cannot reach it.

**How to avoid:** Detect infeasibility (`result.status == 2`) and relax the departure constraint to a soft constraint (add a penalty slack variable). Or: check before solving whether `(departure_slots * ev_charge_power_kw * dt_h / ev_capacity_kwh)` >= `(target_soc - current_soc)/100`. Log a warning if infeasible; fall back to holistic optimizer.

**Warning signs:** LP returns `status=2` ("infeasible") more than once — check departure time config or EV capacity values.

### Pitfall 2: Price Array Length Mismatch (tariffs vs. 96 slots)

**What goes wrong:** evcc returns fewer than 96 price slots (e.g., only 24 hourly slots for the next 24h or only until midnight). The LP expects exactly `T` prices.

**Why it happens:** Dynamic tariffs (Tibber, aWATTar) publish 24h ahead once daily. At 23:00, only 1h of tomorrow is known. evcc tariff API may return 25 or 48 hourly slots.

**How to avoid:** In `_tariffs_to_96slots()`, interpolate/repeat the last known price to fill up to 96 slots. Log the number of available slots. Reduce planning horizon `T` to the number of available price slots if fewer than 32 slots are available (< 8h of prices insufficient for meaningful planning — fall back to holistic). Use the Phase 3 `_tariffs_to_hourly()` parsing logic as a reference.

**Warning signs:** `IndexError` in price array access inside LP construction.

### Pitfall 3: PV Surplus Misrepresented as Grid-Charged Energy

**What goes wrong:** PV generation during a slot reduces net grid import. The LP formulation must account for this: `net_grid_import[t] = bat_charge[t] + ev_charge[t] - pv_surplus[t]`. If PV surplus is not subtracted, the LP pays the full grid price for energy that actually came from PV.

**Why it happens:** Naive formulation puts grid price on all charge decisions without accounting for PV.

**How to avoid:** The objective coefficient for battery/EV charging is the effective grid price net of PV surplus: `effective_price[t] = max(0, price[t])` when `pv_kw[t] - consumption_kw[t] < charge_kw[t]`, else 0 (free PV surplus). Simplest implementation: compute `pv_surplus_kw[t] = max(0, pv_96[t] - consumption_96[t] / 1000)` and reduce available charge power accordingly via bounds rather than modifying the objective coefficient. See Pattern 1 above for objective structure.

**Warning signs:** LP recommends charging at 100% PV hours as expensive (high price coefficient) instead of free.

### Pitfall 4: scipy Not Installed in Dockerfile

**What goes wrong:** `ImportError: No module named 'scipy'` at runtime.

**Why it happens:** `scipy` is not in the current Dockerfile (only `numpy`, `requests`, `pyyaml`, `hyundai-kia-connect-api`, `renault-api`, `aiohttp`).

**How to avoid:** Add `py3-scipy` via `apk add` in the Dockerfile. Do NOT use `pip install scipy` on Alpine — this triggers a compilation from source against musl that requires `gcc`, `fortran`, and `openblas-dev` build dependencies and takes 30+ minutes. The `apk` package is pre-compiled.

**Warning signs:** Build time > 5 minutes when adding scipy to Dockerfile (means pip is compiling from source — switch to apk).

### Pitfall 5: result.x Contains Negative Values Despite Non-Negative Bounds

**What goes wrong:** Numerical precision in HiGHS can produce tiny negative values (e.g., -1e-10) for variables bounded at 0. Treating these as discharge/charge decisions causes spurious controller calls.

**Why it happens:** Floating-point tolerance in LP solver near bound constraints.

**How to avoid:** Always clip extracted values: `bat_charge_kw = max(0.0, result.x[i_bat_chg + t])`. Apply `np.clip(result.x[idx_start:idx_end], 0, power_max)` to all power variable slices before interpretation.

### Pitfall 6: Battery SoC Drift Due to Efficiency Modeling

**What goes wrong:** The LP models SoC with constant `eta_c` and `eta_d` efficiencies. In reality, the battery controller may use a different efficiency or may not charge at exactly the requested kW. After a few cycles, the LP's predicted SoC diverges from the real SoC.

**Why it happens:** Model-plant mismatch is inherent in MPC. The LP assumes perfect tracking of its dispatch decisions.

**How to avoid:** The MPC receding horizon naturally corrects for this — each cycle re-initializes `bat_soc[0]` from `state.battery_soc`. The LP only needs to be approximately right for the next slot; subsequent slots are re-optimized. This is a feature of rolling-horizon MPC, not a bug. Document this in the planner module docstring.

### Pitfall 7: Forgetting to Handle "No EV Connected" Case

**What goes wrong:** LP adds EV SoC dynamics constraints even when no EV is connected. With `ev_soc[0]` initialized to 0 and departure constraint active, the LP may allocate zero charge for the battery to "save" capacity for a non-existent EV.

**Why it happens:** Forgetting to set EV charge bounds to (0, 0) and remove departure constraints when `state.ev_connected == False`.

**How to avoid:** Always branch on `state.ev_connected` before adding EV decision variables and constraints. When no EV: set all `ev_charge[t]` bounds to `(0, 0)`, remove departure constraint, set `ev_soc` dynamics to identity (no state changes). Alternatively, set `ev_charge_power_kw = 0` in bounds and skip departure constraint entirely.

---

## Code Examples

Verified patterns from official documentation and existing codebase:

### linprog Call with HiGHS and Time Limit

```python
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html
from scipy.optimize import linprog
import numpy as np

result = linprog(
    c,                          # objective coefficients (1-D array, length N_vars)
    A_ub=A_ub,                 # inequality constraint matrix (shape: n_ineq x N_vars)
    b_ub=b_ub,                 # inequality RHS (length n_ineq)
    A_eq=A_eq,                 # equality constraint matrix (shape: n_eq x N_vars)
    b_eq=b_eq,                 # equality RHS (length n_eq)
    bounds=bounds,             # list of (low, high) tuples, length N_vars
    method='highs',            # auto-selects dual simplex or interior-point
    options={
        'time_limit': 10.0,    # hard timeout in seconds (HiGHS-specific)
        'disp': False,         # suppress HiGHS output
        'presolve': True,      # enable presolve (reduces problem size)
    }
)

if result.status == 0 and result.success:
    x = result.x              # optimal variable vector
    obj_value = result.fun    # total cost in EUR
    # Access dual values (shadow prices) for constraint analysis (Phase 6):
    # result.eqlin.marginals  -- dual values for equality constraints
    # result.ineqlin.marginals -- dual values for inequality constraints
else:
    # status codes: 0=optimal, 1=iter_limit, 2=infeasible, 3=unbounded, 4=numerical
    log("warning", f"LP failed: status={result.status}, message={result.message}")
```

### Price Array Construction from evcc Tariffs (96-slot)

```python
# Source: adapted from holistic.py _tariffs_to_hourly() pattern
def _tariffs_to_96slots(self, tariffs: List[Dict], now: datetime) -> np.ndarray:
    """Convert evcc tariff list to 96-element price array (EUR/kWh, 15-min slots).

    Fills missing slots with the last known price (conservative: don't assume cheap).
    Returns array of length T (may be less than 96 if price horizon short).
    """
    hourly = self._holistic._tariffs_to_hourly(tariffs, now)  # reuse existing parser
    prices = []
    for hour_dt, price_eur_kwh in hourly:
        prices.extend([price_eur_kwh] * 4)  # each hour = 4 x 15-min slots

    if len(prices) < 32:
        return None  # insufficient horizon — fall back to holistic

    # Truncate or pad to exactly T slots
    T = 96
    if len(prices) >= T:
        return np.array(prices[:T], dtype=np.float64)
    else:
        # Pad with last known price
        pad = [prices[-1]] * (T - len(prices))
        return np.array(prices + pad, dtype=np.float64)
```

### Departure Slot Index Calculation

```python
# Source: same _slot_index() pattern from forecaster/consumption.py
from datetime import datetime, timezone, timedelta

def _departure_slot(departure_dt: datetime, now: datetime) -> int:
    """Return the 15-min slot index (0..95) for a departure datetime.

    Slot 0 = current slot. Returns min(95, max(1, slot_offset)).
    """
    delta_minutes = (departure_dt - now).total_seconds() / 60
    slot_offset = int(delta_minutes / 15)
    return max(1, min(95, slot_offset))
```

### Extracting Current-Slot Action from LP Result

```python
# Source: new pattern for HorizonPlanner
def _action_from_plan(plan: PlanHorizon, state: SystemState) -> Action:
    """Derive Action for controller.apply() from the plan's current (slot 0) decision.

    The LP plan gives continuous kW values. Convert to the existing Action.battery_action
    integer codes for backward compatibility with controller.py.
    """
    slot0 = plan.slots[0]

    # Battery decision
    if slot0.bat_charge_kw > 0.1:
        # Charging: set limit to current slot price (the LP approved this price)
        battery_action = 1  # charge (use as catch-all; Phase 6 adds granularity)
        battery_limit_eur = slot0.price_eur_kwh
    elif slot0.bat_discharge_kw > 0.1:
        battery_action = 6  # discharge
        battery_limit_eur = None
    else:
        battery_action = 0  # hold
        battery_limit_eur = None

    # EV decision
    if slot0.ev_charge_kw > 0.1 and state.ev_connected:
        ev_action = 1  # charge (LP approved this slot's price)
        ev_limit_eur = slot0.price_eur_kwh
    else:
        ev_action = 0
        ev_limit_eur = None

    return Action(
        battery_action=battery_action,
        battery_limit_eur=battery_limit_eur,
        ev_action=ev_action,
        ev_limit_eur=ev_limit_eur,
    )
```

### Fallback Chain in main.py

```python
# Source: proposed main.py modification
# --- LP plan (replaces static price gating) ---
plan = None
if horizon_planner is not None and consumption_96 is not None and pv_96 is not None:
    plan = horizon_planner.plan(
        state=state,
        tariffs=tariffs,
        consumption_96=consumption_96,
        pv_96=pv_96,
        ev_departure_times=_get_departure_times(cfg, driver_mgr),
    )

if plan is not None:
    lp_action = _action_from_plan(plan, state)
    store.update_plan(plan)
else:
    # Fallback: holistic optimizer (unchanged from Phase 3)
    lp_action = optimizer.optimize(state, tariffs)

# RL shadow (unchanged)
rl_action = rl_agent.select_action(state, explore=True)
```

---

## State of the Art

| Old Approach | Current Approach (Phase 4) | When Changed | Impact |
|--------------|---------------------------|--------------|--------|
| Static `battery_max_price_ct` threshold gates battery charging | LP determines optimal charge price based on 24h price forecast | Phase 4 | LP exploits cheap overnight windows that static threshold misses or charges too aggressively |
| Static `ev_max_price_ct` threshold gates EV charging | LP schedules EV charging around departure time with urgency weighting | Phase 4 | Vehicle departing in 2h charges immediately even at P60; vehicle departing in 12h waits for P20 window |
| HolisticOptimizer greedy scheduling (hourly slots) | Rolling-horizon MPC (96 x 15-min slots) | Phase 4 | 4x finer resolution; captures intra-hour price spikes from dynamic tariffs |
| Single-asset optimization (battery or EV independently) | Joint battery + EV optimization in one LP | Phase 4 | Avoids double-counting cheap slots; no more "battery charges because cheap" then "EV also charges because cheap" when only one can be served |

**Deprecated/outdated after Phase 4:**
- `battery_max_price_ct` and `ev_max_price_ct` in `main.py` decision logic: retained as LP upper bounds in the planner, but no longer used as direct price gates in `HolisticOptimizer` paths when LP succeeds.
- `HolisticOptimizer._assess_battery_urgency()`: still used in fallback path; do not modify it in Phase 4.

---

## Open Questions

1. **Simultaneous charge/discharge prevention robustness**
   - What we know: Non-negative variable split (separate `bat_charge` and `bat_discharge` vars) prevents simultaneous charge+discharge when efficiency < 1 because the roundtrip loss `(1 - eta_c * eta_d)` makes it always suboptimal.
   - What's unclear: If `battery_charge_efficiency == battery_discharge_efficiency == 1.0` (unit efficiency), the LP may be degenerate and allow simultaneous charge+discharge.
   - Recommendation: Add an explicit mutual exclusion inequality: `bat_charge[t] + bat_discharge[t] <= max(P_charge, P_discharge)`. This is a linear constraint and maintains LP (not MILP). Alternatively, add a tiny penalty on `bat_discharge` in the objective to break degeneracy.
   - Confidence: MEDIUM (theoretical — may not occur in practice with real efficiency values of 0.92)

2. **EV capacity and charge power source of truth**
   - What we know: `state.ev_capacity_kwh` and `state.ev_charge_power_kw` come from evcc's vehicle state. `VehicleStatus.capacity_kwh` is set per-vehicle from `vehicles.yaml`.
   - What's unclear: If evcc reports 0 for `ev_capacity_kwh` (unknown vehicle), the LP bounds collapse to 0. Need a fallback.
   - Recommendation: Use `state.ev_capacity_kwh or cfg.ev_default_energy_kwh` and `state.ev_charge_power_kw or cfg.sequencer_default_charge_power_kw`. This mirrors the existing `HolisticOptimizer.optimize()` pattern (line 77-78 in holistic.py).

3. **Multi-EV LP formulation (more than 1 EV)**
   - What we know: The current codebase has a single wallbox (single connected EV at a time, managed by ChargeSequencer). Phase 4 description mentions "per-EV departure time" but only one EV charges at once.
   - What's unclear: Should the LP model the ChargeSequencer's vehicle selection as an additional decision, or just plan for the single currently-connected EV?
   - Recommendation: Phase 4 LP should plan only for the currently-connected EV (`state.ev_connected`, `state.ev_name`). Other pending vehicles from `sequencer.requests` can have their departure urgency passed as soft constraints in future phases. This keeps the LP formulation simple (single EV = ~300 decision variables vs multi-EV = ~500 variables) and avoids the ChargeSequencer integration complexity in Phase 4.
   - Confidence: HIGH (supported by phase description: "every 15-minute decision cycle, the system produces a fresh PlanHorizon")

4. **PV surplus handling in LP objective**
   - What we know: `pv_96` gives 96-slot kW values of expected PV generation. `consumption_96` gives expected house load in Watts (divide by 1000 for kW).
   - What's unclear: The net PV surplus available for charging is `max(0, pv_kw[t] - consumption_kw[t])`. Should this reduce the grid cost coefficient in the LP objective (free energy), or be modeled as a separate PV charge variable?
   - Recommendation: Simplest correct approach: compute `pv_surplus_kw[t] = max(0, pv_96[t] - consumption_96[t]/1000)` and add it as a separate non-decision input. Reduce the effective grid charge power available by subtracting PV surplus: effective grid needed = `grid_charge[t] = max(0, total_charge[t] - pv_surplus_kw[t])`. The objective only pays for `grid_charge[t]`. This avoids a 4th variable type while correctly accounting for free PV energy.

---

## Sources

### Primary (HIGH confidence)

- `/app/optimizer/holistic.py` — confirmed `_tariffs_to_hourly()` reusable parser, Action dataclass usage, fallback pattern
- `/app/state_store.py` — confirmed `update()` extension pattern, `_lock` pattern for new fields
- `/app/state.py` — confirmed `Action` fields (`battery_action`, `battery_limit_eur`, `ev_action`, `ev_limit_eur`); `SystemState` field names (`battery_soc`, `ev_soc`, `ev_capacity_kwh`, `ev_charge_power_kw`)
- `/app/config.py` — confirmed `battery_capacity_kwh`, `battery_charge_power_kw`, `battery_charge_efficiency`, `battery_discharge_efficiency`, `battery_min_soc`, `battery_max_soc`, `ev_max_price_ct`, `battery_max_price_ct`, `ev_charge_deadline_hour` field names
- `/app/controller.py` — confirmed `apply(action)` accepts `Action.battery_limit_eur` and `Action.ev_limit_eur`; `set_battery_grid_charge_limit()` and `set_smart_cost_limit()` are the evcc API calls
- `/app/forecaster/consumption.py` and `pv.py` — confirmed `get_forecast_24h()` returns 96-element list; `_slot_index()` pattern for datetime → slot conversion
- [scipy.optimize.linprog official docs v1.17.0](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html) — confirmed `method='highs'`, `options={'time_limit': 10.0}`, result fields `status`, `success`, `x`, `fun`, `eqlin.marginals`, `ineqlin.marginals`
- [linprog(method='highs') v1.17.0](https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs.html) — confirmed `time_limit` option is supported by all HiGHS methods
- [Alpine py3-scipy package](https://pkgs.alpinelinux.org/package/edge/community/x86/py3-scipy) — confirmed version 1.17.0-r1, musl-compatible, available via `apk add py3-scipy`, built 2026-02-09

### Secondary (MEDIUM confidence)

- WebSearch: "scipy linprog HiGHS Alpine Linux musl Python apk 2025" — multiple sources confirm `apk add py3-scipy` installs HiGHS-backed linprog with openblas
- WebSearch: MPC rolling horizon energy storage EV LP formulation literature — confirmed 96-slot (15-min) discretization is standard; rolling horizon MPC with re-initialization from real SoC each cycle is the correct pattern
- WebSearch: joint battery + EV LP formulation patterns — confirmed SoC equality constraints, departure SoC inequality constraints, non-negative variable split for charge/discharge
- [Real Python: Hands-On Linear Programming](https://realpython.com/linear-programming-python/) — confirmed linprog minimization-only convention, negation for maximization, A_ub/b_ub constraint form
- STATE.md decision: `[Research]: scipy/HiGHS via apk (musl-safe)` — confirms the team already validated scipy is available via apk in this Alpine environment

### Tertiary (LOW confidence)

- WebSearch: EV departure constraint LP infeasibility handling — community patterns suggest slack variable relaxation; not verified against specific scipy version
- Simultaneous charge/discharge LP degeneracy at unit efficiency — theoretical concern; no codebase evidence this will occur with `eta=0.92`

---

## Metadata

**Confidence breakdown:**
- Standard stack (scipy via apk): HIGH — confirmed by Alpine package page (v1.17.0-r1, built 2026-02-09) and STATE.md team decision
- LP formulation (variable layout, constraints): HIGH — standard academic formulation verified against scipy docs and literature
- Architecture (main loop integration): HIGH — derived directly from existing main.py and holistic.py patterns
- Departure time handling: HIGH — `ev_charge_deadline_hour` confirmed in config.py; slot index pattern from consumption.py
- Multi-EV handling: MEDIUM — single connected EV assumption is correct for Phase 4 scope but needs confirmation
- Simultaneous charge/discharge prevention: MEDIUM — continuous split is standard; degeneracy at unit efficiency is theoretical

**Research date:** 2026-02-22
**Valid until:** 2026-05-22 (scipy/HiGHS API stable; Alpine apk package updated regularly)
