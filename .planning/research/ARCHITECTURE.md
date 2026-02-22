# Architecture Research

**Domain:** Home Energy Management System with Predictive Planning and Hybrid Residual RL
**Researched:** 2026-02-22
**Confidence:** MEDIUM (patterns from literature + direct codebase analysis; specific integration choices are design decisions)

---

## Standard Architecture

### System Overview

The target architecture introduces a Predictive Planner layer between data collection and the current optimizer. The RL agent shifts from shadow-mode imitator to residual corrector — learning deltas on top of planner decisions rather than full actions from scratch. Thread-safe shared state replaces ad-hoc global access across web/decision/polling threads.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        External Data Sources                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │  evcc API    │  │ Vehicle APIs │  │  Telegram (driver input) │   │
│  │ /api/state   │  │ Kia/Renault/ │  │  SoC confirmations       │   │
│  │ tariff slots │  │ Custom HTTP  │  │                          │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────────┘   │
└─────────┼─────────────────┼──────────────────────┼────────────────────┘
          │                 │                       │
┌─────────▼─────────────────▼───────────────────────▼──────────────────┐
│                     Data Collection Layer                              │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  DataCollector (evcc polling 60s)  │  VehicleMonitor (60 min)  │  │
│  └──────────────────────────┬──────────────────────────────────────┘  │
│                             │ writes to                                │
│  ┌──────────────────────────▼──────────────────────────────────────┐  │
│  │              StateStore  (thread-safe, RLock-guarded)            │  │
│  │  current_snapshot: SystemState    forecast_slots: List[Slot]    │  │
│  │  vehicle_data: Dict[str, Vehicle] plan_horizon: PlanHorizon     │  │
│  └──────┬──────────────────────────────────────────────────────────┘  │
└─────────┼────────────────────────────────────────────────────────────┘
          │ reads from
┌─────────▼────────────────────────────────────────────────────────────┐
│                  Predictive Planning Layer  (NEW)                      │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  HorizonPlanner                                                   │ │
│  │  - Ingests 24-48h price slots and PV forecast from evcc          │ │
│  │  - Runs LP/greedy optimization over entire horizon                │ │
│  │  - Outputs: PlanHorizon (list of DispatchSlot: time, battery_kw, │ │
│  │    ev_action, min_battery_soc, cost_estimate)                     │ │
│  │  - Recomputes every cycle; caches for dashboard                   │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  DynamicBufferCalc                                                │ │
│  │  - Computes situational minimum_battery_soc                       │ │
│  │  - Inputs: hour-of-day, PV forecast next 4h, home_power_avg,     │ │
│  │    price_spread, weather signal (if available)                    │ │
│  │  - Output: single float (replaces config.battery_min_soc)        │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  ConsumptionForecaster                                            │ │
│  │  - Rolling average by hour-of-day and day-of-week                │ │
│  │  - Persists to JSON, updates every cycle                         │ │
│  │  - Feeds HorizonPlanner with expected home_power per slot        │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────┬─────────────────────────┘
                                              │ plan + current slot action
┌─────────────────────────────────────────────▼─────────────────────────┐
│                    Hybrid Decision Layer                                │
│                                                                        │
│  ┌───────────────────────────┐   ┌────────────────────────────────┐   │
│  │  Planner Action (t)       │   │  Residual RL Agent             │   │
│  │  - battery_action         │   │  - Input: state + plan_action  │   │
│  │  - ev_action              │   │  - Output: delta corrections   │   │
│  │  - battery_limit_eur      │───▶  - delta_battery_limit_eur     │   │
│  │  - ev_limit_eur           │   │  - delta_ev_limit_eur          │   │
│  │  from current plan slot   │   │  - Not replacing, correcting   │   │
│  └───────────────────────────┘   └────────────────────┬───────────┘   │
│                                                        │               │
│  final_action = plan_action + rl_delta                 │               │
│  (RL delta clipped to ±MAX_CORRECTION_EUR)             │               │
│  ─────────────────────────────────────────────────────▼─────────────  │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  SeasonalLearner                                                  │ │
│  │  - Tracks correction patterns by (month, hour, weekday)          │ │
│  │  - Detects when planner systematically errs in a context         │ │
│  │  - Feeds context features to RL agent as seasonal embeddings     │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────┬─────────────────────────┘
                                              │ final_action
┌─────────────────────────────────────────────▼─────────────────────────┐
│                    Execution Layer                                      │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  Controller → evcc API (battery mode, smart cost limit)          │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  ChargeSequencer (event-driven transitions + polling fallback)    │ │
│  │  - Listens for connection events from StateStore                  │ │
│  │  - Falls back to 15-min cycle check if no event arrives          │ │
│  │  - Dispatches wallbox target vehicle via evcc API                 │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────┬─────────────────────────┘
                                              │ cost outcomes
┌─────────────────────────────────────────────▼─────────────────────────┐
│                  Learning & Evaluation Layer                            │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  Comparator — tracks planner cost vs actual cost vs RL cost      │ │
│  │  Residual RL trainer — reward = plan_cost - actual_cost (delta)  │ │
│  │  SeasonalLearner.update() — update slot with outcome             │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────────────────────────────────┐
│              Cross-Cutting: Web Server + Notification Layer             │
│  Web/server.py reads StateStore (lock-guarded)                         │
│  Dashboard shows: current plan, 24h timeline, RL deltas, costs         │
│  Telegram: driver SoC confirmations update StateStore                  │
└────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| StateStore | Thread-safe shared state hub; holds current snapshot + 24h plan | All layers (read); DataCollector, Sequencer (write) |
| DataCollector | Polls evcc every 60s, fetches 48h tariff + PV forecast slots | evcc API, StateStore, InfluxDB |
| VehicleMonitor | Polls vehicle APIs every 60 min, handles stale detection | Vehicle providers, StateStore |
| HorizonPlanner | Solves 24-48h dispatch LP; outputs DispatchSlot list | StateStore (reads forecast), produces PlanHorizon |
| DynamicBufferCalc | Computes situational minimum battery SoC per cycle | StateStore (reads PV/hour/spread), HorizonPlanner |
| ConsumptionForecaster | Maintains rolling hour-of-day consumption averages | StateStore (reads home_power), JSON persistence |
| Residual RL Agent | Learns signed corrections (deltas) on top of planner actions | StateStore, HorizonPlanner, SeasonalLearner |
| SeasonalLearner | Tracks and exposes (month, hour, weekday) correction patterns | Residual RL Agent, Comparator |
| ChargeSequencer | Coordinates multi-EV on single wallbox; event + poll hybrid | StateStore (vehicle events), evcc API, DriverManager |
| Controller | Translates final Action into evcc API calls | evcc API |
| Comparator | Records and compares plan vs actual energy costs | StateStore, RL trainer, InfluxDB |
| WebServer | Serves dashboard and REST endpoints | StateStore (read-only), DecisionLog |
| DriverManager + Telegram | Collects driver EV targets; feeds SoC into StateStore | StateStore, ChargeSequencer |

---

## Recommended Project Structure

The existing layout is sound. New components fit as new files/sub-packages under `app/`:

```
rootfs/app/
├── main.py                     # orchestration (unchanged entry point)
├── state.py                    # SystemState, Action (extend for PlanHorizon)
├── state_store.py              # NEW: StateStore class with RLock
│
├── planner/                    # NEW package
│   ├── __init__.py
│   ├── horizon_planner.py      # HorizonPlanner — 24-48h LP dispatch
│   ├── dynamic_buffer.py       # DynamicBufferCalc — situational SoC minimum
│   └── consumption_forecaster.py  # ConsumptionForecaster — rolling averages
│
├── optimizer/                  # EXISTING — keep HolisticOptimizer as fallback
│   ├── __init__.py
│   └── holistic.py
│
├── rl_agent.py                 # REFACTOR: residual corrections, not full actions
├── seasonal_learner.py         # NEW: (month, hour, weekday) pattern tracker
│
├── charge_sequencer.py         # REFACTOR: add event-driven transition trigger
├── comparator.py               # EXTEND: planner cost vs actual tracking
├── controller.py               # UNCHANGED
│
├── vehicles/                   # EXISTING
│   ├── base.py
│   ├── manager.py
│   ├── kia_provider.py
│   ├── renault_provider.py
│   ├── evcc_provider.py
│   └── custom_provider.py
│
├── web/                        # EXTEND: timeline view, plan JSON endpoint
│   ├── server.py
│   ├── template_engine.py
│   ├── templates/
│   └── static/
│
├── evcc_client.py              # UNCHANGED (evcc is the single data source)
├── influxdb_client.py          # UNCHANGED
├── config.py                   # EXTEND: remove static price limits; add planner params
├── decision_log.py             # UNCHANGED
├── notification.py             # UNCHANGED
├── driver_manager.py           # UNCHANGED
└── vehicle_monitor.py          # BUGFIX: stale detection for wallbox-connected vehicles
```

### Structure Rationale

- **planner/ as package:** Three new classes (horizon planner, dynamic buffer, consumption forecaster) form a coherent subsystem. Grouping prevents state.py from ballooning.
- **state_store.py separate from state.py:** The StateStore introduces concurrency primitives (RLock, threading.Event). Keeping it separate from the pure dataclass definitions in state.py prevents mixing concerns.
- **rl_agent.py refactored in-place:** The residual RL interface change (output = delta, not action) is a behavioral shift, not a new file; refactoring the existing file avoids import graph disruptions.
- **seasonal_learner.py top-level:** Consumed by both rl_agent.py and comparator.py — neither is its natural home, so a top-level file avoids circular imports.

---

## Architectural Patterns

### Pattern 1: StateStore — Single Thread-Safe State Hub

**What:** All threads (web, decision loop, vehicle polling, Telegram) access system state through a single `StateStore` object that wraps shared data behind a `threading.RLock`. Writers hold the lock briefly while updating snapshots; readers take a lock to get a consistent copy.

**When to use:** When three or more threads read/write the same data and the current ad-hoc approach (known race conditions in web server) causes bugs.

**Trade-offs:** Slight overhead on every read. Deadlock risk if locks are nested — mitigate by using `RLock` (reentrant) and never holding the lock across I/O calls.

**Example:**
```python
import threading
from dataclasses import dataclass, replace
from typing import Optional
from state import SystemState
from planner.horizon_planner import PlanHorizon

@dataclass
class SharedState:
    snapshot: Optional[SystemState] = None
    plan: Optional[PlanHorizon] = None

class StateStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._state = SharedState()
        self._plan_ready = threading.Event()

    def update_snapshot(self, snapshot: SystemState) -> None:
        with self._lock:
            self._state = replace(self._state, snapshot=snapshot)

    def update_plan(self, plan: PlanHorizon) -> None:
        with self._lock:
            self._state = replace(self._state, plan=plan)
        self._plan_ready.set()

    def get_snapshot(self) -> Optional[SystemState]:
        with self._lock:
            return self._state.snapshot

    def get_plan(self) -> Optional[PlanHorizon]:
        with self._lock:
            return self._state.plan
```

The web server thread calls `store.get_snapshot()` / `store.get_plan()` without any shared mutable access. The decision loop calls `store.update_snapshot()` after each collection cycle.

Source: [Python threading docs](https://docs.python.org/3/library/threading.html), [Real Python thread lock guide](https://realpython.com/python-thread-lock/) — MEDIUM confidence.

---

### Pattern 2: Rolling-Horizon Predictive Planner

**What:** Every decision cycle, HorizonPlanner ingests the full 24-48h tariff slot array and PV forecast from evcc, then solves a greedy LP (no external solver needed — greedy suffices for this problem size) to produce a PlanHorizon: a list of DispatchSlots each covering one 15-minute interval.

**When to use:** When static threshold decisions cannot adapt to day-ahead context (e.g., "charge now at 28ct because tomorrow drops to 18ct").

**Trade-offs:** Forecast accuracy matters — the plan degrades if PV or consumption forecasts are off. Mitigate with ConsumptionForecaster providing realistic home load, and by using only the first 1-2 slots with high confidence.

**Example:**
```python
@dataclass
class DispatchSlot:
    start: datetime
    end: datetime
    grid_price_ct: float
    pv_forecast_w: float
    expected_home_w: float
    battery_action: str    # "charge_grid", "charge_pv", "hold", "discharge"
    battery_target_pct: float  # target SoC by end of slot
    ev_action: str         # "charge", "hold"
    ev_limit_eur: float
    cost_estimate_eur: float

@dataclass
class PlanHorizon:
    computed_at: datetime
    slots: list[DispatchSlot]

    def current_slot(self) -> DispatchSlot | None:
        now = datetime.now(timezone.utc)
        return next((s for s in self.slots if s.start <= now < s.end), None)
```

The planner recomputes every 15-minute cycle but only applies `current_slot()`. This is the receding-horizon (MPC) pattern — future slots inform the present decision but are never directly applied until they become current.

Source: [PyPSA rolling horizon docs](https://docs.pypsa.org/latest/examples/rolling-horizon/), [MPC EV charging ScienceDirect 2025](https://www.sciencedirect.com/science/article/pii/S2352467725003455) — MEDIUM confidence.

---

### Pattern 3: Residual RL — Correction Deltas, Not Full Actions

**What:** The RL agent no longer selects a full action from the 7×5 action space. Instead, it outputs a signed correction (delta) on the planner's price limit recommendations. The agent's action space shrinks to a small delta space: e.g., `{-15, -10, -5, 0, +5, +10, +15}` ct/kWh for both battery and EV limits independently.

**When to use:** When a strong planner exists but systematic biases occur in specific contexts (e.g., planner overestimates PV in winter mornings, so RL learns to tighten the threshold then).

**Trade-offs:** Agent trains much faster because the search space is small and the planner handles the heavy lifting. Risk: if the planner has a structural flaw, the delta space may be too narrow to correct it. Cap deltas at ±MAX_CORRECTION (e.g., 20 ct) to prevent RL from overriding the planner entirely.

**Example:**
```python
# RL output: index into delta_space
DELTA_SPACE_CT = [-20, -15, -10, -5, 0, +5, +10, +15, +20]  # ct/kWh

def build_final_action(plan_action: Action, rl_delta_battery_idx: int,
                       rl_delta_ev_idx: int) -> Action:
    db = DELTA_SPACE_CT[rl_delta_battery_idx]
    de = DELTA_SPACE_CT[rl_delta_ev_idx]
    return Action(
        battery_action=plan_action.battery_action,  # categorical: unchanged
        ev_action=plan_action.ev_action,            # categorical: unchanged
        battery_limit_eur=max(0, plan_action.battery_limit_eur + db / 100),
        ev_limit_eur=max(0, plan_action.ev_limit_eur + de / 100),
    )
```

The reward signal is `plan_cost_eur - actual_cost_eur` (positive when RL correction saved money vs naive plan execution). Seasonal context (month, hour, weekday) is added to the RL state vector so the agent learns that winter morning corrections differ from summer evening corrections.

Source: [Residual RL survey 2024-2025 (EmergentMind)](https://www.emergentmind.com/topics/residual-reinforcement-learning-rl), [Expert-guided DRL SAC (MDPI Energies 2025)](https://www.mdpi.com/1996-1073/18/22/6054) — MEDIUM confidence.

---

### Pattern 4: Dynamic Buffer — Forecast-Based Minimum SoC

**What:** DynamicBufferCalc computes a `min_battery_soc` float per cycle, replacing the static config value. The calculation uses: hour-of-day, PV forecast for the next 4 hours, average home power, price_spread, and optionally a "night risk" flag (quiet hours approaching).

**When to use:** When a fixed minimum SoC is either too conservative (wastes battery capacity in sunny afternoons) or too aggressive (leaves nothing for evening peaks).

**Trade-offs:** Must be tunable — the formula must remain inspectable in the dashboard so the user understands why the battery is "protected." Keep the formula simple (linear combination) rather than a black-box neural net.

**Suggested formula (starting point, validate empirically):**
```python
def compute_min_soc(hour: int, pv_next_4h_kwh: float, home_avg_w: float,
                    price_spread_ct: float, battery_cap_kwh: float,
                    night_in_hours: float) -> float:
    # Base: cover expected home consumption until solar restores battery
    hours_to_pv = max(0, 6 - hour) if hour < 6 else 0     # hours until dawn
    home_need_kwh = (home_avg_w / 1000) * max(hours_to_pv, 1)
    base_soc = min(80, (home_need_kwh / battery_cap_kwh) * 100)

    # Bonus: high price spread → keep more reserve (arbitrage headroom)
    spread_bonus = min(10, price_spread_ct * 0.3)

    # Reduction: strong PV incoming → can afford lower floor
    pv_reduction = min(15, pv_next_4h_kwh * 2)

    return max(10, base_soc + spread_bonus - pv_reduction)
```

The result feeds into both HorizonPlanner (as a constraint per slot) and Controller (as a hard lower bound for battery discharge actions).

Source: [H-RPEM health-aware hybrid RL-MPC (MDPI 2025)](https://www.mdpi.com/2313-0105/12/1/5) — LOW-MEDIUM confidence (formula is original design informed by the pattern, not directly from literature).

---

### Pattern 5: Event-Driven Sequencer Transitions with Polling Fallback

**What:** ChargeSequencer registers a callback with StateStore to be notified immediately when vehicle connection status changes (e.g., EV disconnects). For changes where no event fires (gradual SoC rise, quiet hours boundary), the 15-minute polling cycle handles the transition. This hybrid approach eliminates the current up-to-15-minute delay on vehicle change.

**When to use:** When immediate response to discrete events matters (vehicle disconnect/connect) but the system is already polling-based for everything else. Full event-driven architecture would require rewriting the main loop.

**Trade-offs:** Two trigger paths (event + poll) must not conflict. The sequencer must be idempotent: calling `evaluate_transitions()` twice with the same state produces the same result.

**Example:**
```python
class ChargeSequencer:
    def __init__(self, cfg, evcc, state_store: StateStore):
        self._store = state_store
        # Register for immediate vehicle connection changes
        state_store.register_ev_change_callback(self._on_ev_change)

    def _on_ev_change(self, old_snapshot: SystemState,
                      new_snapshot: SystemState) -> None:
        """Called immediately from DataCollector thread when EV status changes."""
        if old_snapshot.ev_connected != new_snapshot.ev_connected:
            # Trigger immediate re-evaluation in sequencer thread
            self._transition_event.set()

    def run(self) -> None:
        """Sequencer thread: wake on event OR every 15 min (poll fallback)."""
        while not self._stop_event.is_set():
            triggered = self._transition_event.wait(timeout=900)  # 15 min
            self._transition_event.clear()
            self._evaluate_and_apply()
```

Source: [python-statemachine event docs](https://python-statemachine.readthedocs.io/en/latest/transitions.html), [pytransitions GitHub](https://github.com/pytransitions/transitions) — MEDIUM confidence.

---

### Pattern 6: Seasonal Learning via Context Indexing

**What:** SeasonalLearner maintains a 3-dimensional lookup table indexed by (month_bucket, hour_bucket, is_weekend). Each cell stores: count, sum_plan_error_ct, sum_rl_correction_ct. It is updated every cycle with actual vs plan cost. The RL agent reads the normalized values from the current cell as additional state features.

**When to use:** When the planner's systematic errors are seasonal (e.g., it underestimates PV in spring, overestimates in winter) and the RL agent alone is too data-sparse to learn this from scratch quickly.

**Trade-offs:** Simple indexing is transparent and inspectable. Does not handle gradual drift (e.g., PV panel degradation). Adding exponential decay to the running average addresses this.

**Example:**
```python
# Buckets: 4 seasons × 6 time-of-day periods × 2 (weekday/weekend) = 48 cells
MONTH_TO_SEASON = {1:0,2:0,3:1,4:1,5:1,6:2,7:2,8:2,9:3,10:3,11:3,12:0}
HOUR_TO_PERIOD = lambda h: min(5, h // 4)  # 0-3=night, 4-7=dawn, ..., 20-23=evening

class SeasonalLearner:
    def __init__(self, decay: float = 0.99):
        self._decay = decay  # for exponential moving average
        # shape: [4 seasons][6 periods][2 weekend flags]
        self._avg_plan_error = [[[0.0]*2 for _ in range(6)] for _ in range(4)]
        self._count = [[[0]*2 for _ in range(6)] for _ in range(4)]

    def _cell(self, ts: datetime):
        s = MONTH_TO_SEASON[ts.month]
        p = HOUR_TO_PERIOD(ts.hour)
        w = 1 if ts.weekday() >= 5 else 0
        return s, p, w

    def update(self, ts: datetime, plan_error_ct: float) -> None:
        s, p, w = self._cell(ts)
        old = self._avg_plan_error[s][p][w]
        self._avg_plan_error[s][p][w] = (
            self._decay * old + (1 - self._decay) * plan_error_ct
        )
        self._count[s][p][w] += 1

    def get_context_features(self, ts: datetime) -> list[float]:
        """Returns 2 floats: [avg_plan_error_ct (normalized), log_count]"""
        s, p, w = self._cell(ts)
        err = self._avg_plan_error[s][p][w] / 20.0  # normalize to ~[-1, 1]
        cnt = min(1.0, self._count[s][p][w] / 500.0)
        return [err, cnt]
```

These 2 features are appended to the RL agent's state vector, growing it from 31 to 33 dimensions.

Source: [Seasonal electricity demand forecasting ANFIS+LSTM (Scientific Reports 2025)](https://www.nature.com/articles/s41598-025-91878-0) — LOW confidence (specific implementation is original design, seasonal pattern splitting is established practice).

---

## Data Flow

### Main Decision Cycle (v6 Target)

```
Every 15 minutes:
  DataCollector.collect()
      │ evcc /api/state + tariff forecast slots
      ▼
  StateStore.update_snapshot(new_state)
      │ (triggers EV change callback → ChargeSequencer if connection changed)
      ▼
  ConsumptionForecaster.record(home_power)
      │ updates rolling hour-of-day averages
      ▼
  DynamicBufferCalc.compute(snapshot, forecast)
      │ returns min_battery_soc float
      ▼
  HorizonPlanner.compute(snapshot, forecast, consumption_forecast, min_soc)
      │ returns PlanHorizon with 24-48h of DispatchSlots
      ▼
  StateStore.update_plan(plan)
      │
      ▼
  plan_action = plan.current_slot() → Action
      │
  rl_delta = ResidualRLAgent.select_delta(snapshot, plan_action,
                                           seasonal_learner.get_context())
      │
  final_action = plan_action + rl_delta (clipped)
      │
  Controller.apply(final_action) → evcc API
      │
  Comparator.record(snapshot, plan_action, final_action)
      │
  ResidualRLAgent.train_step(reward=plan_cost - actual_cost)
  SeasonalLearner.update(ts, plan_cost - actual_cost)
      │
  DecisionLog.append(...)
  InfluxDB.write(...)
```

### State Management Across Threads

```
Thread 1: Main decision loop (15 min cycle)
    writes: StateStore.update_snapshot(), StateStore.update_plan()

Thread 2: DataCollector background (60s poll)
    writes: StateStore.update_snapshot() [partial updates between cycles]
    reads:  evcc API

Thread 3: VehicleMonitor (60 min poll)
    writes: StateStore.update_vehicle_data(vehicle_name, data)

Thread 4: WebServer (HTTP on demand)
    reads:  StateStore.get_snapshot(), StateStore.get_plan()
    writes: StateStore.update_manual_soc() [user input]

Thread 5: ChargeSequencer (event + 15min poll)
    reads:  StateStore.get_snapshot(), StateStore.get_plan()
    writes: evcc API (vehicle selection)

Thread 6: TelegramBot (optional, continuous poll)
    writes: StateStore.update_vehicle_target_soc() [driver response]

Rule: All writes to StateStore acquire RLock. All reads get a consistent copy.
Rule: No thread holds the lock across a network call.
Rule: StateStore.update_snapshot() fires registered callbacks (EV change detection)
      AFTER releasing the lock to prevent deadlocks.
```

### evcc Tariff Data Format

evcc returns tariff forecast as JSON arrays with 15-minute slots:
```json
[
  {"start": "2026-02-22T14:00:00Z", "end": "2026-02-22T14:15:00Z", "value": 0.1823},
  {"start": "2026-02-22T14:15:00Z", "end": "2026-02-22T14:30:00Z", "value": 0.1791}
]
```

HorizonPlanner consumes this directly from `evcc_client.get_tariff_forecast()`. The DataCollector fetches and stores the full 24-48h array in StateStore every cycle. The planner reads from StateStore — never directly from evcc — ensuring consistent state across the cycle.

Source: [evcc tariff docs](https://docs.evcc.io/en/docs/tariffs) — MEDIUM confidence (verified against evcc documentation structure).

---

## Build Order and Phase Dependencies

The components have strict dependencies that dictate build order:

```
Phase 1: Foundation (must come first)
  StateStore                  ← all other phases depend on thread-safe state
  Vehicle polling bugfixes    ← bad SoC data corrupts everything downstream
  Charge sequencer events     ← visible UX fix, validates event callback mechanism

Phase 2: Predictive Planner (requires Phase 1 state infrastructure)
  ConsumptionForecaster       ← needs clean home_power data from Phase 1
  HorizonPlanner              ← needs ConsumptionForecaster + clean vehicle SoC
  DynamicBufferCalc           ← needs HorizonPlanner for PV context
  Dashboard timeline view     ← needs PlanHorizon in StateStore

Phase 3: Residual RL (requires Phase 2 plan as the base to correct)
  ResidualRLAgent refactor    ← replaces shadow RL; needs plan_action as input
  SeasonalLearner             ← needs several weeks of data from Phase 2
  Comparator extension        ← tracks plan_cost vs actual_cost

Phase 4: Transparency + Polish (independent but rewards Phase 2-3 completion)
  Dashboard WARUM explanations ← reads plan + RL delta + seasonal context
  Telegram planning integration ← EV need queries inform HorizonPlanner slots
  Config simplification        ← remove static price limits, expose planner params
```

**Critical dependency:** Residual RL (Phase 3) cannot be built meaningfully until HorizonPlanner (Phase 2) is producing reliable plans. Without a strong baseline planner, the "residual" has nothing to correct — it reverts to full RL from scratch.

**Second critical dependency:** SeasonalLearner (Phase 3) needs months of data to be statistically meaningful. Build and deploy it early in Phase 3 so it is learning while other Phase 3 work completes. Do not block on it for RL functionality.

---

## Anti-Patterns

### Anti-Pattern 1: RL Replacing the Planner Entirely

**What people do:** Skip building a predictive planner and instead train RL end-to-end to learn the 24h context implicitly.

**Why it's wrong:** End-to-end RL on a 15-minute cycle with real energy costs needs thousands of real cycles (weeks) to converge. It produces decisions the user cannot explain. Negative rewards from learning mistakes directly cost money. On a Raspberry Pi, a large NN needed for end-to-end RL exceeds compute budget.

**Do this instead:** Build the deterministic planner first. RL learns only corrections. Planner handles 95% of the decision; RL handles systematic deviations in specific contexts.

---

### Anti-Pattern 2: Storing Plan in a Module-Level Global

**What people do:** `current_plan = None` at module level in `main.py`, shared with web server via import.

**Why it's wrong:** The existing web server race conditions come exactly from this pattern. Adding a 24h plan object to a global makes the concurrency problem much worse — the plan is a large object written every 15 minutes and read constantly by the dashboard.

**Do this instead:** Route all shared state through `StateStore` with RLock. The web server receives a reference to `StateStore` at startup and reads from it with lock protection.

---

### Anti-Pattern 3: Making the Dynamic Buffer a Neural Network

**What people do:** Train a small NN to predict the optimal `min_battery_soc` from features.

**Why it's wrong:** A NN for buffer computation is a black box that the user cannot inspect. If it fails silently (returns 0 or 100), the consequence is either battery over-discharge or wasted capacity. The formula is simple enough that a human-readable calculation (3-4 terms) is sufficient and auditable.

**Do this instead:** Implement as a transparent formula with tunable coefficients. Log the formula inputs and output every cycle so the dashboard can show "buffer is 35% because PV forecast is strong (−12%) and price spread is moderate (+7%)."

---

### Anti-Pattern 4: Fetching Tariff Data Per-Component

**What people do:** HorizonPlanner, ChargeSequencer, and DynamicBufferCalc each call `evcc_client.get_tariff_forecast()` independently.

**Why it's wrong:** Three API calls per cycle, possible inconsistencies if evcc updates forecast mid-cycle, harder to test.

**Do this instead:** DataCollector fetches the full tariff array once per cycle, stores it in StateStore. All planning components read from StateStore. Single source of truth per cycle.

---

### Anti-Pattern 5: Event-Only Sequencer Without Polling Fallback

**What people do:** Remove the 15-minute polling loop from ChargeSequencer entirely and rely only on EV connection events.

**Why it's wrong:** Events can be missed if the callback throws, if the StateStore update happens during startup, or if the vehicle disconnects while the system is restarting. Quiet hours boundary transitions, SoC target completion, and price changes all happen without a discrete EV connection event.

**Do this instead:** Events trigger immediate re-evaluation. Polling every 15 minutes acts as a guaranteed safety net. Both paths call the same `evaluate_and_apply()` method, which is idempotent.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| evcc REST API | DataCollector polls `/api/state` every 60s; tariff forecast cached in StateStore | evcc is the only source for prices, PV, battery; never bypass |
| Vehicle APIs (Kia/Renault/Custom) | VehicleMonitor polls every 60 min per vehicle; results in StateStore | Stale threshold 90 min — if data older than this, mark stale in dashboard |
| InfluxDB | Write-only from MainLoop; read during bootstrap | Non-critical; silently drop on failure |
| Telegram Bot | Long-polling in separate thread; writes driver SoC targets to StateStore | Optional; system runs without it |

### Internal Boundaries

| Boundary | Communication | Constraint |
|----------|---------------|------------|
| DataCollector → StateStore | Direct method call (lock-guarded write) | Must not hold lock during evcc API call |
| ChargeSequencer → StateStore | Callback registration + read | Callback must not re-acquire lock (deadlock risk) — fire-and-signal pattern |
| WebServer → StateStore | Read-only `get_*()` calls | Web handler must copy data out of lock, not hold lock during render |
| HorizonPlanner → StateStore | Read-only snapshot + forecast access | Planner computation happens outside lock; only StateStore.update_plan() takes lock |
| ResidualRLAgent → HorizonPlanner | Direct: receives `plan_action` as argument | RL agent does not call StateStore directly — keeps it testable in isolation |
| SeasonalLearner → ResidualRLAgent | Features passed as argument to `select_delta()` | Avoids circular dependency |

---

## Scaling Considerations

This system runs on a single Docker container on a Raspberry Pi. Scaling means "stays fast and stable under load," not horizontal scaling.

| Concern | Current State | Target (v6) |
|---------|--------------|-------------|
| Main cycle latency | ~1-2s (evcc poll + optimizer) | <3s (add planner LP solve, must stay fast) |
| Memory use (RL model) | Q-table JSON (~1MB) | Delta Q-table (smaller action space — fewer rows) |
| InfluxDB write volume | 1 write / 15 min | Same; add plan horizon as a single JSON field |
| Thread count | 4 threads | 5-6 threads (add sequencer dedicated thread) |
| Startup time | Slow (RL bootstrap 168h InfluxDB query) | Fix: limit bootstrap to 24h or skip if recent model exists |

### Scaling Priorities

1. **First bottleneck: HorizonPlanner solve time.** If LP solve over 96 slots (24h at 15min) takes >2s on RPi, switch to greedy dispatch (sort slots by price, fill cheapest first with SoC constraints). No external solver dependency — pure NumPy.

2. **Second bottleneck: StateStore lock contention.** If dashboard polling is frequent (every 5s), the web server thread competes with the decision loop for the RLock. Mitigate by caching a `dashboard_snapshot` (deep copy) after each decision cycle — web server reads from cache, never from live state.

---

## Sources

- [Residual RL survey 2024-2025 (EmergentMind)](https://www.emergentmind.com/topics/residual-reinforcement-learning-rl) — MEDIUM confidence
- [H-RPEM health-aware hybrid RL-MPC for PV-EV microgrids (MDPI Batteries 2025)](https://www.mdpi.com/2313-0105/12/1/5) — MEDIUM confidence
- [MPC-RL hybrid for EV smart charging (ScienceDirect 2025)](https://www.sciencedirect.com/science/article/pii/S2352467725003455) — MEDIUM confidence
- [PyPSA rolling horizon optimization](https://docs.pypsa.org/latest/examples/rolling-horizon/) — MEDIUM confidence
- [evcc tariff forecast documentation](https://docs.evcc.io/en/docs/tariffs) — MEDIUM confidence
- [Python threading documentation (official)](https://docs.python.org/3/library/threading.html) — HIGH confidence
- [Real Python thread lock guide](https://realpython.com/python-thread-lock/) — HIGH confidence
- [python-statemachine event/transition docs](https://python-statemachine.readthedocs.io/en/latest/transitions.html) — HIGH confidence
- [pytransitions library (GitHub)](https://github.com/pytransitions/transitions) — HIGH confidence
- [Seasonal electricity demand forecasting with ANFIS+LSTM (Scientific Reports 2025)](https://www.nature.com/articles/s41598-025-91878-0) — LOW confidence (seasonal pattern design is informed by, not derived from, this paper)
- [RL-MPC for distributed energy systems (Springer Building Simulation 2024)](https://link.springer.com/article/10.1007/s12273-024-1227-9) — MEDIUM confidence
- [Home Assistant asyncio thread safety docs](https://developers.home-assistant.io/docs/asyncio_thread_safety/) — HIGH confidence (relevant context: HA uses same threading model)

---

*Architecture research for: SmartLoad v6 — Predictive Energy Management with Hybrid Residual RL*
*Researched: 2026-02-22*
