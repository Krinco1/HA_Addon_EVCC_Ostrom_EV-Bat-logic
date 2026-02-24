# Phase 8: Residual RL and Learning - Research

**Researched:** 2026-02-23
**Domain:** Residual reinforcement learning, seasonal time-series learning, forecast calibration, dashboard widgets
**Confidence:** HIGH (all findings grounded in codebase inspection + established ML patterns)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**RL Promotion Path**
- Automatic promotion: system runs constraint audit after 30-day shadow period, promotes to advisory automatically if all checks pass
- No Telegram notifications for RL status — Telegram is reserved exclusively for charging plan integration and errors
- Dashboard is the sole UI channel for RL status, audit results, and promotion info

**Dashboard RL Widget**
- Dashboard language: German throughout (consistent with existing dashboard) — 'Lernmodus', 'Beobachtung', 'Gewinnrate', 'Tagesersparnis'
- No mixed DE/EN for RL terms

### Claude's Discretion

- **RL Promotion:** Audit failure handling (continue shadow + retry, clip-range reduction, or other). Two-stage vs three-stage model (Shadow+Advisory vs Shadow+Advisory+Active). Audit UI representation (badge vs checklist vs other)
- **Dashboard Widget:** Placement within existing tab structure (new tab vs embedded vs integrated). Primary metrics selection (EUR savings, win-rate, or both). Shadow-phase visibility (show learning progress during shadow or hide until advisory)
- **Forecast Confidence:** Whether/how to display confidence to user. Impact on planner behavior (conservative planning vs weighting only). Storage approach (rolling window vs seasonal cells). Whether to couple with DynamicBufferCalc
- **Learning Speed:** SeasonalLearner conservatism (minimum sample threshold per cell). Decay strategy (exponential vs none). Adaptive reaction timing approach (learned vs fixed thresholds). Replay buffer strategy (stratified vs FIFO)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LERN-01 | RL-Agent lernt Korrekturen zum Planer (Residual Learning) statt eigenständige Entscheidungen | ResidualRLAgent replaces DQNAgent full-action selection with signed delta corrections (+/-20ct clip) on planner's battery and EV price thresholds |
| LERN-02 | System erkennt und adaptiert saisonale Muster (Verbrauch, PV-Ertrag, Preisverhalten über Jahreszeiten) | SeasonalLearner 48-cell lookup table (4 seasons × 6 time-periods × 2 weekend flags) tracks average plan errors; each cell has sample_count for confidence weighting |
| LERN-03 | System lernt angemessene Reaktionszeiten (wann Plan sofort anpassen vs Abweichung abwarten) | ReactionTimingTracker classifies each deviation as self-corrected vs required intervention; learns wait threshold via EMA over labeled episodes |
| LERN-04 | System lernt die Zuverlässigkeit aller Prognosen (PV, Preis, Verbrauch) und korrigiert künftige Planungen mit Konfidenz-Faktoren | ForecastReliabilityTracker per source (pv, consumption, price) with rolling MAE; confidence factor applied in HorizonPlanner and DynamicBufferCalc |
| TRAN-03 | Dashboard zeigt RL vs Planer Vergleichsdaten (Win-Rate, Kostenvergleich) | New "Lernen" tab (or embedded widget) with German labels: Gewinnrate, Tagesersparnis, Kumulierte Ersparnis, Lernmodus/Beobachtung status, 30-day shadow gate, audit checklist |
</phase_requirements>

---

## Summary

Phase 8 is a refactoring-plus-extension phase. The existing `DQNAgent` in `rl_agent.py` selects full actions (7 battery × 5 EV = 35 discrete actions). Phase 8 replaces this with a `ResidualRLAgent` that outputs signed ct/kWh delta corrections to the LP planner's battery and EV price thresholds. This is architecturally simpler: the agent never decides independently — it nudges the already-computed optimal LP plan by small signed amounts, clipped to +/-20 ct. The reward function becomes `plan_cost - actual_cost` per cycle, making it directly economically interpretable. The key migration risk is that existing Q-table data and replay memory are incompatible (different state/action space) and must be cleanly discarded at startup — the existing migration guard in `DQNAgent.load()` already handles this pattern.

Three companion learning systems are added alongside the RL refactor: (1) `SeasonalLearner` — a 48-cell lookup table (4 seasons × 6 time periods × 2 weekend flags) of average plan errors, deployed immediately at Phase 8 start to begin accumulating data even before RL has enough episodes; (2) `ForecastReliabilityTracker` — per-source rolling mean absolute error for PV, consumption, and price forecasts, with computed confidence factors fed into `HorizonPlanner` and `DynamicBufferCalc`; (3) `ReactionTimingTracker` — classifies each observed plan deviation as either self-correcting or intervention-requiring, and learns a threshold for triggering re-plan vs waiting. All four systems must be JSON-persistent to survive container restarts, following the established pattern used by `PVForecaster`, `DynamicBufferCalc`, and `comparator.py`.

The dashboard gets a new "Lernen" tab (fourth tab, after Status/Plan/Historie) showing the RL performance widget in German, a 30-day shadow countdown, and a structured constraint audit checklist that auto-populates once the shadow period ends. Automatic promotion from shadow to advisory mode occurs when the audit passes with zero constraint violations. The `Comparator` class already tracks win-rate and cumulative cost delta — Phase 8 extends it with rolling 7-day windows and rewires it to consume `ResidualRLAgent` corrections rather than full-action comparisons.

**Primary recommendation:** Treat Phase 8 as five tightly coupled but independently committable changes: (1) `ResidualRLAgent` class with delta output + stratified replay buffer, (2) `SeasonalLearner` class with persistence, (3) `ForecastReliabilityTracker` with planner integration, (4) `ReactionTimingTracker` with EMA threshold, (5) dashboard "Lernen" tab with shadow gate logic. Implement in that order so each commit is verifiable.

---

## Standard Stack

### Core (all already present in the container)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `numpy` | already installed | Delta clipping, EMA, seasonal cell arithmetic | Used by `rl_agent.py`, `state.py`, `optimizer/planner.py` |
| `scipy.optimize.linprog` | already installed | HorizonPlanner LP (unchanged) | Phase 4 established this |
| `json` + stdlib | stdlib | Persistence for all new learners | All existing learners (PVForecaster, comparator, rl_agent) use JSON files under `/data/` |
| `sqlite3` | stdlib | `RLDeviceController` persistence (already used) | `comparator.py` uses SQLite for device_control |
| `collections.deque` | stdlib | Rolling windows for ForecastReliabilityTracker | DynamicBufferCalc uses `deque` for event log |
| `threading.Lock` | stdlib | Thread safety for all new learners | Established pattern from `DynamicBufferCalc` and `StateStore` |
| `datetime` + `timezone` | stdlib | Timestamp handling, season/period classification | Used consistently throughout codebase |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dataclasses` | stdlib | `DeltaCorrection`, `SeasonCell`, `ForecastError` value objects | All new data structures |
| `pathlib.Path` | stdlib | Safe file path construction for new `/data/` model files | Consistent with `DynamicBufferCalc` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| JSON file persistence | InfluxDB for learner state | InfluxDB is for time-series telemetry, not model state; JSON files are simpler and match existing pattern |
| Custom stratified replay | Full deep RL library (stable-baselines3) | No GPU, no neural network warranted; Q-table + stratified reservoir sampling is sufficient and already scaffolded |
| Rolling MAE window | Bayesian updating | Rolling MAE with configurable window (default 50 cycles) is interpretable and matches project simplicity preference |

**Installation:** No new dependencies required. All libraries are already present in the container image.

---

## Architecture Patterns

### Recommended Project Structure

```
rootfs/app/
├── rl_agent.py              # REFACTOR: DQNAgent → ResidualRLAgent (delta corrections)
├── seasonal_learner.py      # NEW: SeasonalLearner (48-cell lookup table)
├── forecast_reliability.py  # NEW: ForecastReliabilityTracker (per-source rolling MAE)
├── reaction_timing.py       # NEW: ReactionTimingTracker (wait vs re-plan threshold)
├── comparator.py            # EXTEND: Comparator wired to ResidualRLAgent; rolling 7d window
├── optimizer/planner.py     # EXTEND: accept confidence_factors kwarg from reliability tracker
├── dynamic_buffer.py        # EXTEND: accept pv_confidence_factor from reliability tracker
├── main.py                  # WIRE: instantiate new learners, inject, run shadow gate logic
├── web/server.py            # EXTEND: GET /rl-learning endpoint; /rl-audit endpoint
└── web/templates/dashboard.html  # EXTEND: 4th tab "Lernen" with RL widget
```

### Pattern 1: ResidualRLAgent — Delta Corrections on LP Thresholds

**What:** Replace full action selection with a signed ct/kWh correction output. The agent's action space becomes a small set of signed deltas: e.g., `[-20, -10, -5, 0, +5, +10, +20]` ct for battery threshold and a corresponding set for EV threshold. The Q-table maps state keys to delta-action Q-values. After selection, `planner_bat_price + delta_bat` and `planner_ev_price + delta_ev` produce the adjusted thresholds, both clipped to enforce safety constraints.

**When to use:** Always (this is the sole RL decision path once Phase 8 is complete).

**State vector:** Reuse existing `state.to_vector()` (31 features) — no state space change needed. The action space change is what causes Q-table incompatibility with the existing model; the migration guard in `load()` handles the reset.

**Safety constraint enforcement:**
```python
# Source: Phase 8 architecture decision — delta corrections, not full actions
BAT_DELTA_OPTIONS_CT = [-20, -10, -5, 0, +5, +10, +20]  # 7 battery deltas
EV_DELTA_OPTIONS_CT  = [-20, -10, -5, 0, +5, +10, +20]  # 7 EV deltas
DELTA_CLIP_CT = 20.0  # hard clip magnitude

def apply_correction(self, plan_bat_price_ct: float, plan_ev_price_ct: float,
                     delta_bat_ct: float, delta_ev_ct: float,
                     state: SystemState) -> tuple[float, float]:
    """Returns (adj_bat_ct, adj_ev_ct) with safety constraints enforced."""
    adj_bat = np.clip(plan_bat_price_ct + delta_bat_ct, 0, plan_bat_price_ct + DELTA_CLIP_CT)
    adj_ev  = np.clip(plan_ev_price_ct  + delta_ev_ct,  0, plan_ev_price_ct  + DELTA_CLIP_CT)
    # Battery safety: cannot push below min_soc (planner already guarantees this for plan price,
    # so only negative corrections need guard — if correction would push threshold below 0, clip)
    adj_bat = max(adj_bat, 0.0)
    adj_ev  = max(adj_ev, 0.0)
    return adj_bat, adj_ev
```

**Reward function:**
```python
# reward = plan_cost - actual_cost (positive when RL correction saved money)
def calculate_reward(self, plan_cost_eur: float, actual_cost_eur: float) -> float:
    return plan_cost_eur - actual_cost_eur  # positive = RL improved on plan
```

**Stratified replay buffer:** Keep one sub-buffer per season (spring/summer/autumn/winter), each with capacity `total_capacity // 4`. When sampling, draw equally from all non-empty season buffers. This ensures the agent doesn't forget winter behavior when running in summer, which FIFO alone cannot guarantee.

```python
SEASONS = ["spring", "summer", "autumn", "winter"]

def _get_season(self, dt: datetime) -> str:
    month = dt.month
    if month in (3, 4, 5):   return "spring"
    elif month in (6, 7, 8): return "summer"
    elif month in (9, 10, 11): return "autumn"
    else:                     return "winter"
```

### Pattern 2: SeasonalLearner — 48-Cell Lookup Table

**What:** A 48-cell table indexed by `(season, time_period, is_weekend)` that accumulates average plan errors (actual_cost - plan_cost). Each cell stores `{sum_error, count, mean_error}`. "Plan error" here means the LP cost prediction was off by this amount — positive means plan underestimated cost. This signal informs the planner about systematic biases in specific seasonal/time contexts.

**Cell indexing:**
- `season`: 0=winter(DJF), 1=spring(MAM), 2=summer(JJA), 3=autumn(SON) — 4 values
- `time_period`: 0=00-04h, 1=04-08h, 2=08-12h, 3=12-16h, 4=16-20h, 5=20-24h — 6 values
- `is_weekend`: 0=weekday, 1=weekend — 2 values
- Total: 4 × 6 × 2 = 48 cells

**Persistence pattern (matches DynamicBufferCalc):**
```python
SEASONAL_MODEL_PATH = "/data/smartprice_seasonal_model.json"

def save(self):
    """Atomic write pattern from DynamicBufferCalc."""
    tmp = SEASONAL_MODEL_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"version": 1, "cells": self._cells_to_dict()}, f, indent=2)
    os.replace(tmp, SEASONAL_MODEL_PATH)

def get_cell(self, dt: datetime) -> dict:
    """Returns {"mean_error": float, "count": int} for the current context."""
    key = self._cell_key(dt)
    return self._cells.get(key, {"sum_error": 0.0, "count": 0, "mean_error": 0.0})
```

**Minimum sample threshold (Claude's discretion):** Cells with `count < 10` are treated as low-confidence and their `mean_error` is not applied to planner adjustments. The `count` is always exposed so downstream consumers can make their own weighting decisions. This is conservative — 10 samples at 15-min intervals = 2.5 hours of data, which is achievable within the first week.

**Decay strategy (Claude's discretion):** No exponential decay for now. The lookup table is inherently bounded by the cell structure. Decay can be added in Phase 9 if cells drift too slowly when seasonal conditions change. Keeping it simple avoids introducing a hyperparameter that needs tuning before any data exists.

### Pattern 3: ForecastReliabilityTracker

**What:** Per-source rolling mean absolute error tracking. At every cycle where actual and forecast are available, compute `|actual - forecast|` and add to a fixed-length deque. The confidence factor is `1.0 - clamp(MAE / reference_scale, 0, 1)`. A source with MAE of 0 gets confidence 1.0; a source consistently 30%+ off gets confidence below 0.7.

**Three sources tracked:**
- `pv`: actual `state.pv_power` (W) vs `pv_96[current_slot]` (kW * 1000)
- `consumption`: actual `state.home_power` (W) vs `consumption_96[current_slot]`
- `price`: actual `state.current_price` (EUR/kWh) vs `tariffs[current_slot]['value']`

**Confidence factor computation:**
```python
# Reference scales for normalizing MAE to [0, 1]
REFERENCE_SCALE = {
    "pv": 5000.0,          # W — 5 kW is a "large" PV error
    "consumption": 2000.0,  # W — 2 kW is a large consumption error
    "price": 0.10,          # EUR/kWh — 10ct is a large price error
}
WINDOW_SIZE = 50  # cycles (~12.5 hours at 15-min intervals)

def get_confidence(self, source: str) -> float:
    errors = self._windows[source]  # deque of absolute errors
    if len(errors) < 5:
        return 1.0  # insufficient data — assume reliable until proven otherwise
    mae = sum(errors) / len(errors)
    scale = REFERENCE_SCALE[source]
    return max(0.0, 1.0 - min(mae / scale, 1.0))
```

**Integration into HorizonPlanner:** The confidence factor for price is applied as a scaling modifier on objective coefficients — a low-confidence price forecast causes the LP to act more conservatively (weight price slots less aggressively). The confidence factor for PV affects the effective PV surplus reduction in the objective. The existing `DynamicBufferCalc` already takes `pv_confidence` — this becomes `pv_reliability_confidence` from the tracker.

**Display (Claude's discretion):** Show a compact "Prognose-Qualität" panel on the Status tab (not a separate tab) listing confidence percentages for each source. This is informational only; no user action required.

### Pattern 4: ReactionTimingTracker

**What:** At each cycle, compare expected plan action vs actual controller output. If they diverge, record a "deviation episode". On the next cycle, check whether the system self-corrected (actual aligned with plan without RL correction) or required an intervention. EMA over labeled episodes produces a `wait_threshold` (percentage of deviations that self-correct) which informs whether to re-plan immediately or wait one cycle.

**Deviation classification:**
```python
@dataclass
class DeviationEpisode:
    timestamp: datetime
    plan_action: str        # "bat_charge", "bat_hold", "ev_charge", etc.
    actual_action: str
    resolved_in_cycles: int # 0=immediate, 1=next cycle, 2+=slow/never
    self_corrected: bool    # True if plan and actual re-aligned without external trigger

def update(self, plan_action: str, actual_action: str, next_cycle_aligned: bool):
    episode = DeviationEpisode(...)
    episode.self_corrected = next_cycle_aligned
    self._episodes.append(episode)
    self._update_ema()

def should_replan_immediately(self) -> bool:
    """Return True if historical data says most deviations don't self-correct."""
    return self._ema_self_correction_rate < self._wait_threshold
```

**EMA approach (Claude's discretion):** Simple EMA with alpha=0.05 (slow-moving, stable threshold). Initial `wait_threshold` = 0.6 (if fewer than 60% of deviations self-correct, trigger immediate re-plan). This is a conservative default — the system will tend to re-plan unless it learns that deviations usually resolve themselves.

**Persistence:** JSON file `/data/smartprice_reaction_timing.json` — same atomic-write pattern.

### Pattern 5: Shadow Mode Gate and Constraint Audit

**What:** The `ResidualRLAgent` has a `mode` attribute (`"shadow"` or `"advisory"`). In shadow mode, corrections are logged but not applied — the LP plan runs unmodified. After `SHADOW_DAYS = 30` have elapsed (tracked via `shadow_start_timestamp`), an automatic constraint audit runs.

**Constraint audit checklist:**
1. Zero shadow corrections would have pushed battery below `min_soc`
2. Zero shadow corrections would have caused any EV to miss departure target SoC
3. Zero shadow corrections had magnitude > DELTA_CLIP_CT (already guaranteed by clipping — but verify)
4. Win-rate over shadow period is positive (RL corrections improved cost in > 50% of cycles)

**Automatic promotion logic:**
```python
def maybe_promote(self, audit_result: dict) -> bool:
    """Promote shadow→advisory if audit passes. Returns True if promoted."""
    if self.mode != "shadow":
        return False
    if not audit_result["all_constraints_passed"]:
        # Failed: continue shadow, reset 30-day counter, log reason
        self.shadow_start_timestamp = datetime.now(timezone.utc)
        log("warning", f"RL constraint audit failed: {audit_result['failures']} — shadow period reset")
        return False
    self.mode = "advisory"
    self._save()
    log("info", "RL promoted to advisory mode after constraint audit passed")
    return True
```

**Audit failure handling (Claude's discretion):** On audit failure, reset the 30-day shadow period. No clip-range reduction (that adds complexity without strong justification). The retry approach is simpler and gives the agent more time to learn safer corrections. The dashboard shows the specific failures so the user understands why promotion didn't happen.

**Two-stage model (Claude's discretion):** Shadow → Advisory only (not Shadow → Advisory → Active). "Advisory" means corrections are applied but logged prominently. A future phase can add "Active" with fewer restrictions. This matches the project's incremental safety philosophy.

### Pattern 6: Dashboard "Lernen" Tab

**What:** A fourth tab added to the existing `tab-nav` in `dashboard.html`. Following the established pattern (Status/Plan/Historie tabs), the tab is lazy-loaded on first click via `switchTab('lernen')` in `app.js`.

**German labels (locked decisions):**

| English concept | German label |
|-----------------|--------------|
| Learning mode | Lernmodus |
| Shadow mode (observation) | Beobachtung |
| Advisory mode | Beratung |
| Win-rate | Gewinnrate |
| Daily savings | Tagesersparnis |
| Cumulative savings | Kumulierte Ersparnis |
| Constraint audit | Sicherheitsprüfung |
| Audit passed | Alle Prüfungen bestanden |
| Audit failed | Prüfung fehlgeschlagen |
| Days remaining in shadow | Noch X Tage Beobachtung |

**Widget layout:**
```
[Lernen Tab]
┌─────────────────────────────────────────────────────┐
│ Lernmodus: Beobachtung (noch 18 Tage)               │  ← Mode badge
│ ─────────────────────────────────────────────────── │
│ Gewinnrate (7 Tage): 62%                            │  ← Rolling win-rate
│ Tagesersparnis (Ø):  0,14 EUR                       │  ← Avg daily cost delta
│ Kumulierte Ersparnis: 2,84 EUR                      │  ← Cumulative savings
│ ─────────────────────────────────────────────────── │
│ Sicherheitsprüfung (nach 30 Tagen)                  │
│  ✓ SoC-Mindestgrenze eingehalten                    │
│  ✓ Abfahrtsziel eingehalten                         │
│  ✓ Korrekturbereich eingehalten                     │
│  ✓ Positive Gewinnrate                              │
│  → Automatische Förderung verfügbar                 │
└─────────────────────────────────────────────────────┘
```

**API endpoint:** `GET /rl-learning` returns `{mode, shadow_days_elapsed, shadow_days_remaining, win_rate_7d, avg_daily_savings_eur, cumulative_savings_eur, audit: {all_passed, checks: [...]}}`.

**Shadow-phase visibility (Claude's discretion):** Show the widget immediately from Phase 8 start, including shadow-period learning progress (win_rate, daily_savings computed from simulation). This gives the user visibility into RL learning behavior during the mandatory 30-day observation period, which builds trust in the eventual promotion.

### Anti-Patterns to Avoid

- **Modifying HorizonPlanner state inside ResidualRLAgent:** The RL agent must receive the LP plan's price thresholds as inputs and return corrected thresholds. It must not hold a reference to `HorizonPlanner` or call `plan()` internally.
- **Applying RL corrections to EV departure constraints:** The EV departure constraint is a hard LP equality/inequality. RL corrections only adjust the price threshold above which EV charging is gated — they never modify the departure time or target SoC.
- **Storing ForecastReliabilityTracker data in InfluxDB:** This is a lightweight rolling-window model, not telemetry. JSON file persistence is correct.
- **Sending RL mode changes via Telegram:** Locked decision — all RL status through dashboard only.
- **Resetting SeasonalLearner when promoting to advisory:** The SeasonalLearner accumulates data continuously from Phase 8 start regardless of RL mode. Do not clear it on promotion.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Stratified reservoir sampling | Custom complex sampler | Simple per-season deque of fixed capacity | Sufficient for 4-class stratification; no need for weighted priority sampling |
| Atomic file writes | `open(path, 'w')` directly | `open(tmp); os.replace(tmp, path)` | Prevents partial-write corruption on container restart — established pattern in codebase |
| EMA smoothing | numpy exponential smoothing library | `ema = alpha * new + (1-alpha) * ema` inline | One-liner, no dependency needed |
| Season detection | External calendar library | Month-based branching (DJF/MAM/JJA/SON) | Simple, deterministic, matches meteorological seasons |
| Thread safety for learners | asyncio or multiprocessing | `threading.Lock()` per learner instance | Matches existing pattern (DynamicBufferCalc, StateStore) |

**Key insight:** All learning components in this phase operate on 15-minute aggregated data, not streaming micro-events. This means simple Python data structures with file persistence and a single read/write lock are always sufficient — no message queue, no database ORM, no async framework needed.

---

## Common Pitfalls

### Pitfall 1: Q-Table Incompatibility After ResidualRLAgent Refactor

**What goes wrong:** Old Q-table keyed for 7×5=35 full actions gets loaded into the new delta-correction agent (7 battery deltas × 7 EV deltas = 49 actions). Values are silently misinterpreted.

**Why it happens:** The existing `DQNAgent.load()` checks `n_actions` and `state_size` but will fail gracefully only if these fields are saved. The new `ResidualRLAgent` must have different `N_ACTIONS` (49) and declare a distinct `STATE_SIZE` or a new model version field.

**How to avoid:** Increment the model version field in the JSON (`"model_version": 2`). In `load()`, check version and reset if mismatch. Keep the path as `/data/smartprice_rl_model.json` — the old file will be read, version mismatch detected, and Q-table reset cleanly.

**Warning signs:** If `epsilon` loads correctly but Q-table values seem random/noisy from the first cycle, version mismatch didn't get caught.

### Pitfall 2: Shadow Corrections Computed Against Wrong Baseline

**What goes wrong:** The "plan_cost" used in the reward function is the LP objective value (`plan.solver_fun`), but this is the total 24h planned cost, not the per-cycle cost. Comparing 24h plan cost to a 15-min actual cost produces nonsense rewards.

**Why it happens:** `plan.solver_fun` is the full-horizon LP objective. The per-slot cost must be derived from slot-0 only: `slot0.price_eur_kwh * (slot0.bat_charge_kw + slot0.ev_charge_kw) * 0.25` (15-min energy).

**How to avoid:** Define `plan_slot0_cost_eur` as the slot-0 grid energy cost at the plan price, and `actual_slot0_cost_eur` from `state.current_price * actual_power_kw * 0.25`. The reward is the difference.

**Warning signs:** Reward values outside the range [-0.5, +0.5] EUR per cycle are suspicious.

### Pitfall 3: SeasonalLearner Cell Index Wrap at Year Boundary

**What goes wrong:** December (month 12) is winter, same as January and February. Using `(month - 1) // 3` for season index gives `(12-1)//3 = 3` (autumn), not 0 (winter).

**Why it happens:** Naive quarter-based indexing from month number doesn't match meteorological seasons.

**How to avoid:** Use explicit month-to-season mapping:
```python
MONTH_TO_SEASON = {12: 0, 1: 0, 2: 0,  # winter (DJF)
                    3: 1, 4: 1, 5: 1,   # spring (MAM)
                    6: 2, 7: 2, 8: 2,   # summer (JJA)
                    9: 3, 10: 3, 11: 3} # autumn (SON)
```

### Pitfall 4: ForecastReliabilityTracker PV Unit Mismatch

**What goes wrong:** `pv_96` from `PVForecaster.get_forecast_24h()` is in kW. `state.pv_power` is in W. Computing `|actual_W - forecast_kW|` produces a ~1000x inflated error.

**Why it happens:** The codebase has a documented unit ambiguity for PV data — see `pv.py` lines 9-16 ("Reuses the median heuristic from state.py").

**How to avoid:** In `ForecastReliabilityTracker`, always convert to the same unit before computing error:
```python
actual_pv_kw = state.pv_power / 1000.0  # always convert W→kW
forecast_pv_kw = pv_96[current_slot_idx]  # already in kW from PVForecaster
error = abs(actual_pv_kw - forecast_pv_kw)
```

### Pitfall 5: Shadow Mode Bypass During Boost Override

**What goes wrong:** When a Boost override is active, the main loop already forces `ev_action=1` with no price limit (see `main.py` lines 383-389). If the ResidualRLAgent also runs and its correction is logged as a "shadow correction", it will log a correction against a state where the EV was forced-on — polluting the constraint audit with false positives.

**Why it happens:** The RL agent runs every cycle regardless of override status.

**How to avoid:** Skip RL correction logging (and shadow episode recording) when `_override_active` is True. The `_override_status` dict from `override_manager.get_status()` is already available in the main loop.

### Pitfall 6: SeasonalLearner Plan Error Sign Convention

**What goes wrong:** If "plan error" is defined as `plan_cost - actual_cost` (positive = plan overestimated cost), the learner's mean_error informs the planner to be bolder in that cell context. If it's `actual_cost - plan_cost` (positive = plan underestimated), it means be more conservative. Inconsistent sign use produces the opposite of intended behavior.

**How to avoid:** Define once and document in the class docstring: `plan_error = actual_cost_eur - plan_cost_eur` (positive = actual was more expensive than planned = plan was optimistic). Document that positive `mean_error` in a cell means the planner should apply a conservatism factor for that context.

### Pitfall 7: Dashboard "Lernen" Tab Metrics Before Any Data Exists

**What goes wrong:** On first startup, all learner cells are empty. The dashboard shows `NaN` or crashes when computing win-rate with 0 comparisons denominator.

**Why it happens:** `rl_wins / n` when `n=0` raises `ZeroDivisionError`, or returns `nan` if numpy division.

**How to avoid:** The existing `Comparator.get_status()` already guards this (`self.rl_wins / n if n else 0`). Apply the same pattern for all new metrics in `GET /rl-learning`. Return `"ausstehend"` (pending) instead of `0%` when `n < 10`.

---

## Code Examples

### ResidualRLAgent Delta Action Selection

```python
# Source: Phase 8 architecture — extends DQNAgent pattern from rl_agent.py
DELTA_OPTIONS_CT = [-20, -10, -5, 0, +5, +10, +20]  # 7 delta levels
N_BAT_DELTAS = len(DELTA_OPTIONS_CT)   # 7
N_EV_DELTAS  = len(DELTA_OPTIONS_CT)   # 7
N_ACTIONS = N_BAT_DELTAS * N_EV_DELTAS # 49

def select_delta(self, state: SystemState, explore: bool = True) -> tuple[float, float]:
    """Returns (bat_delta_ct, ev_delta_ct) — signed corrections to LP thresholds."""
    state_key = self._discretize_state(state.to_vector())
    if explore and random.random() < self.epsilon:
        action_idx = random.randint(0, N_ACTIONS - 1)
    else:
        action_idx = int(np.argmax(self.q_table[state_key]))
    bat_idx = action_idx // N_EV_DELTAS
    ev_idx  = action_idx  % N_EV_DELTAS
    return float(DELTA_OPTIONS_CT[bat_idx]), float(DELTA_OPTIONS_CT[ev_idx])
```

### SeasonalLearner Update Pattern

```python
# Source: Phase 8 design — 48-cell lookup with sample counts
def update(self, dt: datetime, plan_error_eur: float):
    """Record one plan error for the current (season, time_period, is_weekend) cell."""
    key = self._cell_key(dt)
    with self._lock:
        cell = self._cells.setdefault(key, {"sum_error": 0.0, "count": 0, "mean_error": 0.0})
        cell["sum_error"] += plan_error_eur
        cell["count"] += 1
        cell["mean_error"] = cell["sum_error"] / cell["count"]
    # Persist every 10 updates (not every cycle — file I/O outside lock)
    if cell["count"] % 10 == 0:
        self.save()

def get_correction_factor(self, dt: datetime, min_samples: int = 10) -> Optional[float]:
    """Returns mean plan error for this cell if count >= min_samples, else None."""
    key = self._cell_key(dt)
    with self._lock:
        cell = self._cells.get(key)
    if cell is None or cell["count"] < min_samples:
        return None  # insufficient data — caller treats as no correction
    return cell["mean_error"]
```

### ForecastReliabilityTracker Integration in Main Loop

```python
# Source: Phase 8 — wired into main.py after forecasters run
# After collecting actual state and running forecasters:
if pv_96 is not None and state.pv_power is not None:
    forecast_reliability.update("pv",
        actual=state.pv_power / 1000.0,
        forecast=pv_96[current_slot_idx])

if consumption_96 is not None and state.home_power is not None:
    forecast_reliability.update("consumption",
        actual=state.home_power,
        forecast=consumption_96[current_slot_idx])

if tariffs:
    forecast_reliability.update("price",
        actual=state.current_price,
        forecast=float(tariffs[0].get("value", state.current_price)))

# Pass confidence factors into planner
confidence_factors = {
    "pv": forecast_reliability.get_confidence("pv"),
    "consumption": forecast_reliability.get_confidence("consumption"),
    "price": forecast_reliability.get_confidence("price"),
}
```

### Shadow Mode Gate in Main Loop

```python
# Source: Phase 8 — ResidualRLAgent shadow mode integration in main.py
bat_delta_ct, ev_delta_ct = rl_agent.select_delta(state, explore=True)

if rl_agent.mode == "shadow":
    # Log correction but do NOT apply it
    rl_agent.log_shadow_correction(
        bat_delta_ct, ev_delta_ct,
        plan_bat_price_ct=lp_action.battery_limit_eur * 100 if lp_action.battery_limit_eur else 0,
        plan_ev_price_ct=lp_action.ev_limit_eur * 100 if lp_action.ev_limit_eur else 0,
        state=state,
    )
    final = lp_action  # unmodified LP plan
elif rl_agent.mode == "advisory":
    # Apply correction to LP thresholds
    adj_bat_ct, adj_ev_ct = rl_agent.apply_correction(
        plan_bat_price_ct=lp_action.battery_limit_eur * 100 if lp_action.battery_limit_eur else 0,
        plan_ev_price_ct=lp_action.ev_limit_eur * 100 if lp_action.ev_limit_eur else 0,
        delta_bat_ct=bat_delta_ct,
        delta_ev_ct=ev_delta_ct,
        state=state,
    )
    final = Action(
        battery_action=lp_action.battery_action,
        battery_limit_eur=adj_bat_ct / 100,
        ev_action=lp_action.ev_action,
        ev_limit_eur=adj_ev_ct / 100,
    )
```

### GET /rl-learning API Response Structure

```python
# Source: Phase 8 — new endpoint in web/server.py
def _api_rl_learning(self) -> dict:
    agent = self.rl  # ResidualRLAgent instance
    shadow_elapsed = agent.shadow_elapsed_days()
    shadow_remaining = max(0, 30 - shadow_elapsed)

    comparisons_7d = agent.get_recent_comparisons(days=7)
    n = len(comparisons_7d)
    wins = sum(1 for c in comparisons_7d if c.get("rl_better"))
    win_rate_7d = wins / n if n else None

    return {
        "mode": agent.mode,                                    # "shadow" | "advisory"
        "shadow_days_elapsed": shadow_elapsed,
        "shadow_days_remaining": shadow_remaining,
        "win_rate_7d": win_rate_7d,                           # None if < 10 comparisons
        "avg_daily_savings_eur": agent.avg_daily_savings(),   # None if < 1 day data
        "cumulative_savings_eur": agent.cumulative_savings(),
        "audit": agent.get_audit_result() if shadow_remaining == 0 else None,
        "seasonal_cells_populated": self.seasonal_learner.populated_cell_count(),
        "forecast_confidence": {
            "pv": self.forecast_reliability.get_confidence("pv"),
            "consumption": self.forecast_reliability.get_confidence("consumption"),
            "price": self.forecast_reliability.get_confidence("price"),
        },
    }
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| DQNAgent selects full 7×5 actions independently | ResidualRLAgent outputs signed delta corrections to LP thresholds | Phase 8 | Agent never conflicts with safety guarantees; LP always maintains feasibility |
| FIFO replay buffer (single queue) | Stratified replay buffer (one deque per season) | Phase 8 | Prevents seasonal forgetting; critical for annual-cycle energy patterns |
| `rl_ready` boolean (win-rate threshold on comparator) | Explicit shadow mode + constraint audit + automatic promotion | Phase 8 | Formal safety gate replaces implicit readiness metric |
| No seasonal adaptation | 48-cell SeasonalLearner + ForecastReliabilityTracker | Phase 8 | System adapts to winter/summer PV and price pattern differences |

**Deprecated/outdated:**
- `DQNAgent.select_action()` returning `Action` with full battery/EV action codes: replaced by `ResidualRLAgent.select_delta()` returning `(bat_delta_ct, ev_delta_ct)` tuples
- `Comparator.compare()` simulating RL cost via heuristic: replaced by actual plan_cost vs actual_cost comparison using slot-0 energy accounting
- `rl_auto_switch` config field and `RLDeviceController` auto-switch logic: shadow/advisory mode now controlled by explicit audit gate, not per-device win-rate threshold

---

## Key Integration Points (Critical for Planning)

### Existing Code to Modify (not rewrite)

1. **`rl_agent.py`** — Replace `DQNAgent` class with `ResidualRLAgent`. Keep file, add new class, deprecate old. The `bootstrap_from_influxdb()` method can be adapted or dropped (shadow mode means bootstrap imitation learning is less critical). Keep `ReplayMemory` class as it's reused by the new agent.

2. **`comparator.py`** — `Comparator.compare()` needs a new overload or parameter accepting `(plan_cost_eur, actual_cost_eur, delta_bat_ct, delta_ev_ct)` instead of the existing heuristic simulation. The existing `get_status()` dict structure should be preserved for backward compat with the existing dashboard (Status tab still uses `/comparisons` endpoint).

3. **`main.py`** — Add instantiation of `SeasonalLearner`, `ForecastReliabilityTracker`, `ReactionTimingTracker`. Wire into the decision loop. Add shadow mode branching around RL correction application. Add `maybe_promote()` call once per cycle when shadow period has elapsed.

4. **`optimizer/planner.py`** — Add optional `confidence_factors: dict = None` parameter to `plan()`. When provided, scale price objective coefficients by `confidence_factors.get("price", 1.0)` and PV surplus by `confidence_factors.get("pv", 1.0)`.

5. **`dynamic_buffer.py`** — Add optional `pv_reliability_factor: float = 1.0` parameter to `step()`. Apply as a multiplier on the `pv_confidence` input: `effective_confidence = pv_confidence * pv_reliability_factor`.

6. **`web/server.py`** — Add `GET /rl-learning` endpoint. Add `self.seasonal_learner`, `self.forecast_reliability`, `self.reaction_timing` late-attribute injection (matching pattern of `buffer_calc`, `plan_snapshotter`).

7. **`web/templates/dashboard.html`** — Add 4th tab button `<button class="tab-btn" onclick="switchTab('lernen')">Lernen</button>` and corresponding `<div id="tab-lernen" ...>` panel.

### New Files to Create

1. `seasonal_learner.py` — `SeasonalLearner` class
2. `forecast_reliability.py` — `ForecastReliabilityTracker` class
3. `reaction_timing.py` — `ReactionTimingTracker` class

### New `/data/` Persistence Paths

```python
SEASONAL_MODEL_PATH    = "/data/smartprice_seasonal_model.json"
RELIABILITY_MODEL_PATH = "/data/smartprice_forecast_reliability.json"
REACTION_TIMING_PATH   = "/data/smartprice_reaction_timing.json"
RL_SHADOW_LOG_PATH     = "/data/smartprice_rl_shadow_log.json"
```

---

## Open Questions

1. **HorizonPlanner confidence_factors integration depth**
   - What we know: The planner uses `price_96[t]` directly as LP objective coefficients. Scaling them by a confidence factor < 1.0 would make the optimizer treat uncertain prices as if they were lower, producing more conservative dispatch.
   - What's unclear: Whether reducing price coefficients by a confidence factor is the right semantic (it means "act as if prices are lower when we're uncertain about them") vs. widening SoC margins instead.
   - Recommendation: For Phase 8, apply confidence scaling only to the PV surplus reduction in the objective (where the effect is clearest). Price confidence affects planning conservatism via DynamicBufferCalc rather than LP coefficients directly. This is lower-risk and easier to explain.

2. **ResidualRLAgent state vector — include seasonal cell error?**
   - What we know: The 31-feature state vector from `state.to_vector()` already includes season index (feature 30: `tm_yday / 365`). Adding `seasonal_learner.get_correction_factor(now)` as feature 31 would give the agent direct access to historical plan error context.
   - What's unclear: Whether adding this feature is worth extending the state vector (which invalidates any partially-trained Q-table) vs. letting the agent discover seasonal patterns on its own via the stratified replay buffer.
   - Recommendation: Do NOT extend the state vector in Phase 8. The stratified replay buffer already provides seasonal memory. Feature 31 can be added later if the replay buffer proves insufficient. Keeping STATE_SIZE=31 also means the migration guard from old Q-tables works correctly (old size was also 31 — will reset cleanly because N_ACTIONS differs: 35→49).

3. **Cumulative savings EUR computation accuracy**
   - What we know: The existing `Comparator` tracks `rl_simulated_cost` as a heuristic offset from `actual_cost`. This isn't a real EUR saving — it's an estimate.
   - What's unclear: The dashboard will show "Kumulierte Ersparnis: 2,84 EUR" — if this number is based on heuristic simulation it's not reliable.
   - Recommendation: In shadow mode, cumulative savings = sum of `(plan_slot0_cost - simulated_cost_with_correction)` per cycle. These are simulated savings computed from actual slot-0 energy × price difference. Prefix display with "ca." to communicate it's an estimate, consistent with existing dashboard conventions (Phase 06-01 decision in STATE.md).

---

## Sources

### Primary (HIGH confidence)

- Codebase inspection — `rootfs/app/rl_agent.py` — existing DQNAgent action space, Q-table structure, migration guard, persistence pattern
- Codebase inspection — `rootfs/app/optimizer/planner.py` — LP objective coefficient structure, slot-0 cost computation, price array layout
- Codebase inspection — `rootfs/app/comparator.py` — existing win-rate tracking, Comparator.get_status(), RLDeviceController
- Codebase inspection — `rootfs/app/dynamic_buffer.py` — atomic JSON write pattern, threading.Lock pattern, observation mode model
- Codebase inspection — `rootfs/app/main.py` — decision loop structure, component wiring, RL shadow comment on line 369, override_active guard
- Codebase inspection — `rootfs/app/web/server.py` — API endpoint patterns, tab navigation, late-attribute injection model
- Codebase inspection — `rootfs/app/state.py` — SystemState.to_vector() 31-feature layout, season feature (index 30), unit conventions
- Codebase inspection — `rootfs/app/forecaster/pv.py` — unit handling (W vs kW), EMA pattern, atomic save
- `.planning/phases/08-residual-rl-and-learning/08-CONTEXT.md` — locked decisions, Claude's discretion areas
- `.planning/REQUIREMENTS.md` — LERN-01 through LERN-04, TRAN-03 requirement text

### Secondary (MEDIUM confidence)

- Residual learning architecture pattern — standard ML practice for learning corrections to a known-good model rather than full action selection; widely used in model predictive control + RL hybrid systems
- Stratified replay buffer — documented technique for preventing catastrophic forgetting in seasonal/non-stationary RL environments; referenced in RL literature as "experience replay with class stratification"
- Meteorological season classification (DJF/MAM/JJA/SON) — standard convention for European climate analysis; matches the quarterly energy price pattern in German electricity markets

### Tertiary (LOW confidence)

- Specific EMA alpha values (0.05 for reaction timing, 0.1 for PV correction) — design estimates based on existing codebase conventions; should be validated against 1-2 weeks of live data after Phase 8 deployment

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in container, patterns established in Phases 4-7
- Architecture: HIGH — all patterns derived from direct codebase inspection; no external API dependencies
- Pitfalls: HIGH — all derived from codebase analysis of existing unit handling, lock patterns, division guards
- Integration points: HIGH — line-level references to existing code verified by reading source files

**Research date:** 2026-02-23
**Valid until:** 2026-05-23 (90 days — stable codebase, no fast-moving external dependencies)
