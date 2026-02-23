# Phase 5: Dynamic Buffer - Research

**Researched:** 2026-02-23
**Domain:** Battery SoC management, PV forecast confidence scoring, observation-mode state machines, dashboard time-series logging
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Buffer Formula & Aggressiveness**
- Conservative approach: minimum buffer 20% even at highest confidence (hard floor remains 10% but practical minimum is 20%)
- PV-Confidence is the dominant input; price spread and time of day act as modifiers
- Recalculation interval: every 15 minutes
- All calculation inputs logged per event

**Dashboard Logging**
- Dual view: Line chart showing buffer level over time + expandable detail table per event
- Full input visibility per event: PV confidence, price spread, time of day, expected PV production, old buffer -> new buffer, reason for change
- 7-day history in chart view, older data scrollable in log
- No notifications — passive logging only, user checks dashboard on demand

**Observation Mode**
- "Would have changed" log: entries show what DynamicBufferCalc would have done, clearly marked as simulation
- Auto-transition to live after 14 days
- User can manually activate live early OR extend observation period beyond 2 weeks
- Countdown/status indicator visible in dashboard during observation

**Confidence Definition**
- Numeric 0-100% confidence value (continuous, not discrete levels)
- Combined data sources: historical forecast accuracy (last 7 days) + current weather conditions
- Displayed as collapsible widget: collapsed = single summary line with key info; expanded = full details + graph
- Confidence value logged with every buffer event

### Claude's Discretion
- Buffer transition behavior (gradual vs. immediate when conditions change)
- Confidence threshold at which buffer starts being lowered (somewhere above 50%)
- Observation mode status banner design and prominence
- Chart styling, exact widget layout, spacing

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PLAN-03 | Hausakku-Mindest-SoC passt sich situationsabhängig an (Tageszeit, PV-Prognose, erwarteter Verbrauch, Preislage) | DynamicBufferCalc engine reads pv_forecaster.confidence (already in StateStore as pv_confidence), price_spread from SystemState, time-of-day from datetime, and pv_96 slots for expected PV; applies conservative formula; evcc API call set_buffer_soc() already exists in EvccClient; observation mode controls whether the API call fires |
</phase_requirements>

---

## Summary

Phase 5 adds a `DynamicBufferCalc` engine that reads existing signals already computed by Phase 3/4 (`pv_forecaster.confidence`, `state.price_spread`, time-of-day, `pv_96` slots) and adjusts evcc's `bufferSoc` setting every 15 minutes. The codebase already has all data dependencies in place: `PVForecaster.confidence` returns a continuous 0.0–1.0 value, `SystemState.price_spread` is computed each cycle, and `EvccClient.set_buffer_soc()` exists and is already called by `Controller.apply_battery_to_ev()`. The new engine slots into the existing 15-minute main loop with minimal coupling.

The core design challenge is not algorithmic complexity — the formula is intentionally conservative — but rather the **observation-mode lifecycle** (tracking deployment timestamp, auto-transition after 14 days, manual override) and the **7-day buffer event log** (persisted across restarts, powering a dual chart+table dashboard widget). Both require a persistent JSON store following the same atomic-write pattern used by `PVForecaster._save()`.

The dashboard extension follows the established pattern in `dashboard.html` + `app.js`: a new section receives data via the existing SSE endpoint at `/events`, no polling needed. The collapsible confidence widget and observation-mode countdown banner can be added as static HTML sections filled dynamically by JS, consistent with how the forecast section was added in Phase 3.

**Primary recommendation:** Implement `DynamicBufferCalc` as a standalone module in `rootfs/app/`, with its own JSON persistence for the event log and observation-mode state, wired into the main loop after the LP/holistic step, before `store.update()`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`json`, `os`, `threading`, `datetime`) | built-in | Persistence, thread safety, time calculations | Already used for PV model store, StateStore; no new dependencies |
| Python stdlib (`collections.deque`) | built-in | In-memory event log (bounded size) | Same pattern as DecisionLog |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `numpy` | already installed | Array operations if needed for confidence history | Already a dependency (state.py, optimizer) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| JSON flat file for event log | SQLite | SQLite is overkill for ~14 days x 96 events; JSON matches every other persistence file in the codebase |
| In-memory deque for events | Full DB | No restart persistence with deque alone; use JSON with deque as in-memory cache |

**Installation:**
```bash
# No new packages required — stdlib only
```

---

## Architecture Patterns

### Recommended Project Structure

```
rootfs/app/
├── dynamic_buffer.py        # DynamicBufferCalc engine + event log + persistence
├── main.py                  # wire-in: call calc.step() each cycle, extend store.update()
├── state_store.py           # extend snapshot with buffer_log field
└── web/
    ├── templates/
    │   └── dashboard.html   # new buffer section: chart + table + confidence widget + obs banner
    └── static/
        └── app.js           # SSE handler updates for buffer_log and observation_state
```

### Pattern 1: DynamicBufferCalc Module

**What:** Self-contained class that owns formula, log, observation mode state, and persistence. Called every 15-min cycle from `main.py`. Returns a result dict that main.py passes to `store.update()`.

**When to use:** Follows the `PVForecaster` module pattern — one class owns one domain, with `_load()` / `_save()` for persistence and a single public `step()` method called from the main loop.

**Example:**
```python
# rootfs/app/dynamic_buffer.py

import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import List, Optional

BUFFER_MODEL_PATH = "/data/smartload_buffer_model.json"
BUFFER_MODEL_VERSION = 1

# Hard floor: buffer NEVER drops below this regardless of inputs
HARD_FLOOR_PCT = 10

# Practical minimum even at highest confidence (user decision: conservative)
PRACTICAL_MIN_PCT = 20

# Maximum buffer reduction allowed (from configured battery_min_soc)
# e.g. if cfg.battery_min_soc=30, max lowering is to 20% (practical min)
MAX_BUFFER_PCT = 100  # bounded by battery_max_soc in practice

# Confidence threshold above which buffer reduction begins
# (Claude's discretion: recommended 0.65 — above 50%, conservative)
CONFIDENCE_REDUCTION_THRESHOLD = 0.65

# Observation mode duration in seconds (14 days)
OBSERVATION_PERIOD_SECONDS = 14 * 24 * 3600

# Max log entries kept in memory (7 days x 96 cycles/day = 672 entries)
MAX_LOG_ENTRIES = 700


class BufferEvent:
    """Single buffer adjustment event — logged regardless of mode."""

    __slots__ = (
        "ts", "mode", "pv_confidence", "price_spread_ct",
        "hour_of_day", "expected_pv_kw", "old_buffer_pct",
        "new_buffer_pct", "reason", "applied"
    )

    def __init__(
        self, pv_confidence: float, price_spread_ct: float,
        hour_of_day: int, expected_pv_kw: float,
        old_buffer_pct: int, new_buffer_pct: int,
        reason: str, applied: bool, mode: str
    ):
        self.ts = datetime.now(timezone.utc)
        self.pv_confidence = pv_confidence
        self.price_spread_ct = price_spread_ct
        self.hour_of_day = hour_of_day
        self.expected_pv_kw = expected_pv_kw
        self.old_buffer_pct = old_buffer_pct
        self.new_buffer_pct = new_buffer_pct
        self.reason = reason
        self.applied = applied   # False in observation mode
        self.mode = mode         # "observation" or "live"

    def to_dict(self) -> dict:
        return {
            "ts": self.ts.isoformat(),
            "mode": self.mode,
            "pv_confidence": round(self.pv_confidence * 100, 1),
            "price_spread_ct": round(self.price_spread_ct * 100, 2),
            "hour_of_day": self.hour_of_day,
            "expected_pv_kw": round(self.expected_pv_kw, 2),
            "old_buffer_pct": self.old_buffer_pct,
            "new_buffer_pct": self.new_buffer_pct,
            "reason": self.reason,
            "applied": self.applied,
        }


class DynamicBufferCalc:
    """
    Computes and (in live mode) applies dynamic battery minimum SoC.

    Observation mode: runs formula, logs what it would do, does NOT call evcc.
    Live mode: runs formula, logs, calls evcc.set_buffer_soc() when threshold changes.

    Thread safety: all state access guarded by _lock (called from main loop only,
    but StateStore reads the log snapshot from web thread).
    """

    def __init__(self, cfg, evcc_client) -> None:
        self._cfg = cfg
        self._evcc = evcc_client
        self._lock = threading.Lock()

        # Observation mode state (persisted)
        self._deployment_ts: Optional[datetime] = None   # when add-on first ran with Phase 5
        self._live_override: Optional[bool] = None       # manual override (True=live, False=extend obs)
        self._observation_extended_until: Optional[datetime] = None  # for manual extension

        # Current effective buffer SoC (persisted, last applied value)
        self._current_buffer_pct: int = cfg.battery_min_soc

        # Event log (bounded, persisted to JSON across restarts)
        self._log: deque = deque(maxlen=MAX_LOG_ENTRIES)

        self._load()

    def step(
        self,
        pv_confidence: float,         # 0.0-1.0 from PVForecaster.confidence
        price_spread: float,           # EUR/kWh from SystemState.price_spread
        pv_96: list,                   # 96-slot kW forecast from PVForecaster
        now: Optional[datetime] = None
    ) -> dict:
        """
        Run one calculation cycle. Returns result dict for StateStore.
        Called every 15 minutes from main loop.

        Returns:
            {
                "current_buffer_pct": int,
                "mode": "observation" | "live",
                "days_remaining": int | None,
                "log_recent": [dict, ...],
                "observation_live_at": ISO str | None,
            }
        """
        if now is None:
            now = datetime.now(timezone.utc)

        mode = self._determine_mode(now)
        target_buffer = self._compute_target(pv_confidence, price_spread, pv_96, now)
        old_buffer = self._current_buffer_pct

        reason = self._build_reason(pv_confidence, price_spread, target_buffer, mode)
        applied = (mode == "live")

        if applied and target_buffer != old_buffer:
            self._evcc.set_buffer_soc(target_buffer)
            with self._lock:
                self._current_buffer_pct = target_buffer

        # Always log (observation entries marked applied=False)
        if target_buffer != old_buffer or True:  # always log each cycle for chart continuity
            event = BufferEvent(
                pv_confidence=pv_confidence,
                price_spread_ct=price_spread,
                hour_of_day=now.hour,
                expected_pv_kw=self._sum_next_4h_pv(pv_96),
                old_buffer_pct=old_buffer,
                new_buffer_pct=target_buffer,
                reason=reason,
                applied=applied,
                mode=mode,
            )
            with self._lock:
                self._log.append(event)

        self._save()

        with self._lock:
            log_recent = [e.to_dict() for e in list(self._log)[-100:]]

        days_remaining = self._days_remaining(now) if mode == "observation" else None
        live_at = self._live_activation_ts()

        return {
            "current_buffer_pct": self._current_buffer_pct,
            "mode": mode,
            "days_remaining": days_remaining,
            "log_recent": log_recent,
            "observation_live_at": live_at.isoformat() if live_at else None,
        }

    def _compute_target(self, confidence: float, spread: float, pv_96: list, now: datetime) -> int:
        """
        Conservative formula: practical minimum 20%, hard floor 10%.

        Base: cfg.battery_min_soc (user-configured safe minimum, e.g. 20-30%)
        Reduction triggers when confidence > CONFIDENCE_REDUCTION_THRESHOLD (e.g. 0.65)

        Modifiers (all reduce from base, never below PRACTICAL_MIN_PCT):
          - confidence_bonus: scales linearly from 0 at threshold to max_reduction at 1.0
          - spread_bonus: small extra reduction when price spread is wide (good arbitrage)
          - time_bonus: small extra reduction in morning (5:00-10:00) when PV is incoming

        Hard floor: HARD_FLOOR_PCT (10%) always enforced.
        """
        base = self._cfg.battery_min_soc  # e.g. 20%
        max_reduction = max(0, base - PRACTICAL_MIN_PCT)  # e.g. 0 if base is already 20%

        if confidence <= CONFIDENCE_REDUCTION_THRESHOLD or max_reduction == 0:
            return base

        # confidence_bonus: 0..1 over threshold range
        conf_factor = (confidence - CONFIDENCE_REDUCTION_THRESHOLD) / (1.0 - CONFIDENCE_REDUCTION_THRESHOLD)

        # spread_bonus: small modifier (spread > 0.10 EUR/kWh = "good arbitrage day")
        spread_bonus = 0.1 if spread > 0.10 else 0.0

        # time_bonus: morning hours 5-10 when solar ramp-up is imminent
        hour = now.hour
        time_bonus = 0.1 if 5 <= hour <= 10 else 0.0

        # Combined factor — clamped to [0.0, 1.0]
        total_factor = min(1.0, conf_factor + spread_bonus + time_bonus)

        reduction = int(max_reduction * total_factor)
        target = base - reduction

        # Enforce floors
        target = max(target, PRACTICAL_MIN_PCT)
        target = max(target, HARD_FLOOR_PCT)

        return target

    def _sum_next_4h_pv(self, pv_96: list) -> float:
        """Sum PV kW over next 4 hours (16 slots). Used for logging only."""
        if not pv_96:
            return 0.0
        return sum(pv_96[:16])

    def _determine_mode(self, now: datetime) -> str:
        with self._lock:
            if self._live_override is True:
                return "live"
            if self._live_override is False:
                # User extended observation
                if self._observation_extended_until and now < self._observation_extended_until:
                    return "observation"
                # Extended period over — go live
                return "live"
            # Auto mode: check deployment timestamp
            if self._deployment_ts is None:
                self._deployment_ts = now
                self._save_unlocked()
            elapsed = (now - self._deployment_ts).total_seconds()
            if elapsed >= OBSERVATION_PERIOD_SECONDS:
                return "live"
            return "observation"

    def _days_remaining(self, now: datetime) -> Optional[int]:
        with self._lock:
            if self._deployment_ts is None:
                return 14
            elapsed = (now - self._deployment_ts).total_seconds()
            remaining = OBSERVATION_PERIOD_SECONDS - elapsed
            return max(0, int(remaining / 86400))

    def _live_activation_ts(self) -> Optional[datetime]:
        with self._lock:
            if self._deployment_ts is None:
                return None
            from datetime import timedelta
            return self._deployment_ts + timedelta(seconds=OBSERVATION_PERIOD_SECONDS)

    def _build_reason(self, confidence: float, spread: float, target: int, mode: str) -> str:
        parts = [f"Konfidenz {confidence*100:.0f}%"]
        if spread > 0.10:
            parts.append(f"Spread {spread*100:.0f}ct")
        parts.append(f"Puffer {target}%")
        if mode == "observation":
            parts.append("[Simulation]")
        return " · ".join(parts)

    # --- Manual override API (called from web server POST handler) ---

    def activate_live(self) -> None:
        """User manually activates live mode early."""
        with self._lock:
            self._live_override = True
        self._save()

    def extend_observation(self, extra_days: int = 14) -> None:
        """User extends observation by N more days from now."""
        from datetime import timedelta
        with self._lock:
            self._live_override = False
            self._observation_extended_until = datetime.now(timezone.utc) + timedelta(days=extra_days)
        self._save()

    # --- Persistence (atomic write, same pattern as PVForecaster) ---

    def _load(self) -> None:
        try:
            with open(BUFFER_MODEL_PATH, "r") as f:
                model = json.load(f)
            if model.get("version") != BUFFER_MODEL_VERSION:
                return
            ts_str = model.get("deployment_ts")
            if ts_str:
                if ts_str.endswith("Z"):
                    self._deployment_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                else:
                    self._deployment_ts = datetime.fromisoformat(ts_str)
            self._live_override = model.get("live_override")
            self._current_buffer_pct = int(model.get("current_buffer_pct", self._cfg.battery_min_soc))
            # Restore log entries
            for entry_dict in model.get("log", []):
                # Reconstruct BufferEvent from dict (approximate — fields only)
                pass  # log is rebuilt each run; history only used for chart data
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
            pass

    def _save(self) -> None:
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        """Must be called while holding self._lock."""
        model = {
            "version": BUFFER_MODEL_VERSION,
            "deployment_ts": self._deployment_ts.isoformat() if self._deployment_ts else None,
            "live_override": self._live_override,
            "current_buffer_pct": self._current_buffer_pct,
            "log": [e.to_dict() for e in self._log],
        }
        tmp = BUFFER_MODEL_PATH + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(model, f, indent=2)
            os.rename(tmp, BUFFER_MODEL_PATH)
        except Exception:
            pass
```

### Pattern 2: Main Loop Integration

**What:** Wire `DynamicBufferCalc.step()` into the 15-minute cycle, after LP/holistic decision, before `store.update()`.

**When to use:** Every cycle, unconditionally. The calculator handles its own mode logic.

**Example:**
```python
# In main.py decision loop (after plan/optimizer, before store.update):

buffer_result = None
if buffer_calc is not None:
    buffer_result = buffer_calc.step(
        pv_confidence=pv_forecaster.confidence,
        price_spread=state.price_spread,
        pv_96=pv_96 or [],
        now=datetime.now(timezone.utc),
    )

store.update(
    state=state,
    lp_action=lp_action,
    rl_action=rl_action,
    # ... existing fields ...
    buffer_result=buffer_result,   # NEW: None or dict
)
```

### Pattern 3: StateStore Extension

**What:** Add `buffer_result` to `StateStore.update()` signature and `_snapshot_unlocked()`, mirroring how `pv_confidence` was added in Phase 3.

**Example:**
```python
# state_store.py: add to __init__
self._buffer_result: Optional[dict] = None

# update() signature addition:
def update(self, ..., buffer_result: Optional[dict] = None) -> None:
    with self._lock:
        ...
        self._buffer_result = buffer_result
        ...

# _snapshot_unlocked(): add field
snap["buffer_result"] = copy.copy(self._buffer_result)

# _snapshot_to_json_dict(): add to SSE payload
"buffer": snap.get("buffer_result"),  # mode, current_buffer_pct, log_recent, days_remaining
```

### Pattern 4: Dashboard Extension

**What:** New dashboard section receives `data.buffer` from SSE events. Collapsible confidence widget, observation banner, buffer history chart (line), expandable event table. Uses same CSS variables and dark theme as existing sections.

**When to use:** JS `handleSSEUpdate()` already dispatches SSE data to all DOM updaters — add a new `updateBufferSection(data.buffer)` call there.

**Example layout:**
```html
<!-- Observation mode banner (hidden in live mode) -->
<div id="bufferObsBanner" class="obs-banner" style="display:none;">
    <span id="bufferObsText">Beobachtungsmodus — noch X Tage</span>
    <button onclick="activateBufferLive()">Jetzt aktivieren</button>
    <button onclick="extendBufferObs()">Verlängern</button>
</div>

<!-- Buffer status + confidence widget -->
<div class="chart-card" id="bufferCard">
    <h3>Dynamischer Puffer</h3>
    <!-- Collapsible confidence widget -->
    <div id="confWidget">
        <div id="confSummary" onclick="toggleConfDetail()">
            PV-Konfidenz: <span id="confValue">--</span> · Puffer: <span id="bufferValue">--</span>%
        </div>
        <div id="confDetail" style="display:none;">
            <!-- expanded: confidence breakdown, 7-day accuracy history graph -->
        </div>
    </div>
    <!-- Buffer level over time: line chart (SVG, same as forecast chart) -->
    <div id="bufferChart" style="height:150px;"></div>
    <!-- Event log table (expandable rows) -->
    <table id="bufferLog">...</table>
</div>
```

### Pattern 5: Web Server API Endpoints

**What:** Two new POST endpoints for manual observation-mode control. Follows existing POST pattern in `server.py` (e.g. `/sequencer/request`).

```
POST /buffer/activate-live     — calls buffer_calc.activate_live()
POST /buffer/extend-obs        — calls buffer_calc.extend_observation(days)
```

### Anti-Patterns to Avoid

- **Calling `set_buffer_soc()` every cycle unconditionally:** Only call when target changes AND in live mode. Unnecessary evcc API calls add latency and log noise.
- **Storing 7-day history in memory only:** Use JSON persistence — the add-on restarts regularly (HA updates, power cycles). A deque without `_save()` loses all history.
- **Computing confidence inside DynamicBufferCalc:** Confidence is already computed by `PVForecaster`. Do not duplicate the calculation. Receive it as a parameter.
- **Blocking the main loop with file I/O:** `_save()` is fast (< 1ms for ~700 entries in JSON), but use atomic rename (`.tmp` → final) to prevent corruption, exactly as `PVForecaster._save()` does.
- **Using notification/alerts for buffer changes:** User decision: passive logging only. No Telegram, no banner alerts on change.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PV confidence value | Custom accuracy tracker in this phase | `PVForecaster.confidence` (already computed from `_coverage_hours`) | Already maintained, thread-safe, persisted |
| Price spread | Custom percentile computation | `SystemState.price_spread` (P80-P20, computed each cycle in main loop) | Already in state every 15 min |
| Setting evcc buffer SoC | Raw HTTP call | `EvccClient.set_buffer_soc(pct)` | Already tested and used by `Controller.apply_battery_to_ev()` |
| SSE broadcast of new state | New push mechanism | Extend existing `StateStore.update()` + `_snapshot_to_json_dict()` | SSE already active, zero new infrastructure |
| Observation-mode timer | External scheduler, cron | Inline datetime arithmetic in `_determine_mode()` | Simpler, no dependencies, restarts fine because `_deployment_ts` is persisted |
| Chart rendering | Chart.js or other lib | Vanilla SVG path generation (same as existing forecast chart in app.js) | No CDN dependency, works offline (HA add-on), same codebase style |

**Key insight:** All data inputs for the DynamicBufferCalc are already produced as a side-effect of Phase 3/4 work. This phase is primarily about wiring them into a formula, persisting the log, and displaying it.

---

## Common Pitfalls

### Pitfall 1: Confidence Value Is 0.0 at Night (Expected, Not a Bug)
**What goes wrong:** `PVForecaster.confidence` returns 0.0 when `_coverage_hours == 0` (API failure) OR when the forecast data is stale. At night, the API may still return data (future slots have 0 kW PV but are still present), so confidence typically stays at 1.0 overnight — but if evcc restarts or solar API is unreachable, it drops to 0.0.
**Why it happens:** `confidence = min(1.0, coverage_hours / 24.0)` — total API failure gives 0.0.
**How to avoid:** When confidence == 0.0, buffer formula should return `cfg.battery_min_soc` (safe max — this is the intended conservative fallback behavior). Already handled by `if confidence <= CONFIDENCE_REDUCTION_THRESHOLD` returning base.
**Warning signs:** Logs showing buffer oscillating between min_soc and reduced value every few cycles — indicates intermittent API failures.

### Pitfall 2: Lock Contention Between Main Loop and Web Thread
**What goes wrong:** `DynamicBufferCalc._save()` holds `_lock` during file I/O. The web thread reading `log_recent` for SSE also needs the lock. If `_save()` is slow (large log on spinning disk), SSE broadcast blocks.
**Why it happens:** Atomic rename is fast, but the full log JSON serialization (700 entries) takes ~1-5ms.
**How to avoid:** Use a two-phase approach: serialize to string first, then write under lock. Or — simpler — copy the log list under lock, release, then write. The existing `PVForecaster._save()` does not hold the lock during file write; follow the same pattern.

### Pitfall 3: Observation Mode Timestamp Not Persisted Across Restarts
**What goes wrong:** `_deployment_ts` is set once on first `step()` call. If not persisted, every restart resets the 14-day clock to today, making observation mode permanent.
**Why it happens:** Easy to forget to include `_deployment_ts` in the JSON model.
**How to avoid:** `_save_unlocked()` MUST include `deployment_ts`. `_load()` MUST restore it.
**Warning signs:** Observation mode never ends despite being deployed for weeks.

### Pitfall 4: Buffer Oscillation (Thrashing)
**What goes wrong:** Confidence oscillates above/below threshold between cycles (e.g., 66% then 64% then 67%), causing buffer to toggle between two values every 15 minutes, generating noisy log entries and unnecessary evcc API calls.
**Why it happens:** `PVForecaster.confidence` is based on `coverage_hours` which can change slightly each hourly refresh.
**How to avoid:** Two options (Claude's discretion): (a) hysteresis — only change buffer if new target differs from current by >=2% (rounding to 5% increments), or (b) throttle writes — only call `set_buffer_soc()` if value changed AND it has been at least 2 cycles at the new value. Recommended: option (a) with 5% rounding.

### Pitfall 5: Dashboard Log Grows Unboundedly in JSON
**What goes wrong:** 7 days x 96 cycles/day = 672 entries x ~200 bytes/entry = ~130KB. Fine. But if `MAX_LOG_ENTRIES` is too high or entries are larger than expected, the JSON file grows and `_save()` slows.
**Why it happens:** Not accounting for actual entry size.
**How to avoid:** Cap at `MAX_LOG_ENTRIES = 700` (slightly over 7 days). JSON file stays < 200KB. Monitor in testing.

### Pitfall 6: `set_buffer_soc()` Conflicts with `apply_battery_to_ev()`
**What goes wrong:** `Controller.apply_battery_to_ev()` also calls `set_buffer_soc()` when `battery_to_ev_dynamic_limit` is True. If `DynamicBufferCalc` also sets it, the two compete for the same evcc setting.
**Why it happens:** Two code paths writing the same evcc parameter without coordination.
**How to avoid:** Phase 5 buffer value sets the MINIMUM baseline. `apply_battery_to_ev()` sets a TEMPORARY higher value for the duration of the bat-to-EV discharge. The current code already does `self.evcc.set_buffer_soc(new_buffer)` where `new_buffer` is dynamic based on bat-to-EV state. Document that the bat-to-EV logic takes precedence while active; `DynamicBufferCalc` applies only when bat-to-EV is NOT active. Add a check: `if not controller._bat_to_ev_active: buffer_calc.step(...)`.

---

## Code Examples

### Wiring Into Main Loop

```python
# Source: main.py pattern analysis

# After line: horizon_planner = None (around line 121)
buffer_calc = None
try:
    from dynamic_buffer import DynamicBufferCalc
    buffer_calc = DynamicBufferCalc(cfg, evcc)
    log("info", "DynamicBufferCalc: initialized")
except Exception as e:
    log("warning", f"DynamicBufferCalc: init failed ({e}), buffer management disabled")

# In the while True loop, after LP/holistic decision, before store.update():
buffer_result = None
if buffer_calc is not None and not controller._bat_to_ev_active:
    buffer_result = buffer_calc.step(
        pv_confidence=pv_forecaster.confidence,
        price_spread=state.price_spread,
        pv_96=pv_96 or [],
        now=datetime.now(timezone.utc),
    )
```

### Extending StateStore.update() Signature

```python
# Source: state_store.py pattern — add parameter alongside pv_confidence

def update(
    self,
    state, lp_action, rl_action,
    solar_forecast=None, consumption_forecast=None, pv_forecast=None,
    pv_confidence=0.0, pv_correction_label="", pv_quality_label="",
    forecaster_ready=False, forecaster_data_days=0, ha_warnings=None,
    buffer_result=None,   # NEW
) -> None:
    with self._lock:
        ...
        self._buffer_result = buffer_result
        ...
```

### SSE JSON Payload Addition

```python
# Source: _snapshot_to_json_dict() pattern in state_store.py

"buffer": snap.get("buffer_result"),   # None or {mode, current_buffer_pct, days_remaining, log_recent}
```

### Confidence Widget in JavaScript

```javascript
// Source: app.js SSE handler pattern (updateForecastSection style)

function updateBufferSection(buffer) {
    if (!buffer) return;

    // Observation mode banner
    const banner = document.getElementById('bufferObsBanner');
    if (buffer.mode === 'observation') {
        banner.style.display = '';
        document.getElementById('bufferObsText').textContent =
            `Beobachtungsmodus – noch ${buffer.days_remaining} Tage bis Live-Betrieb`;
    } else {
        banner.style.display = 'none';
    }

    // Confidence value
    const lastEntry = buffer.log_recent?.slice(-1)[0];
    if (lastEntry) {
        document.getElementById('confValue').textContent =
            `${lastEntry.pv_confidence.toFixed(0)}%`;
        document.getElementById('bufferValue').textContent =
            lastEntry.new_buffer_pct;
    }

    // Render buffer history chart (line chart over time, same SVG style as forecast)
    renderBufferChart(buffer.log_recent);

    // Render log table
    renderBufferLog(buffer.log_recent);
}
```

### Atomic Write Pattern (Established Convention)

```python
# Source: PVForecaster._save() — use exactly this pattern
tmp_path = BUFFER_MODEL_PATH + ".tmp"
try:
    with open(tmp_path, "w") as f:
        json.dump(model, f, indent=2)
    os.rename(tmp_path, BUFFER_MODEL_PATH)
except Exception as e:
    log("error", f"DynamicBufferCalc: failed to save model: {e}")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static `battery_min_soc` in config | Dynamic SoC floor computed from forecast confidence | Phase 5 (new) | Battery can be lowered to 20% when solar is reliable, staying at configured min otherwise |
| PVForecaster.confidence = binary (data/no data) | Continuous 0-100% from coverage_hours | Phase 3 | Phase 5 formula can use analog confidence for proportional buffer reduction |
| `set_buffer_soc()` used only for bat-to-EV | Also used for dynamic buffer baseline | Phase 5 (new) | Requires coordination with bat-to-EV logic to avoid conflict |

**Deprecated/outdated:**
- Static `battery_min_soc` as the only buffer control: still the base value, but now also the fallback when confidence is low. Not removed, just augmented.

---

## Open Questions

1. **Coordination with bat-to-EV buffer logic**
   - What we know: `Controller.apply_battery_to_ev()` calls `set_buffer_soc()` with a dynamically computed value when bat-to-EV is active. `DynamicBufferCalc` also wants to call `set_buffer_soc()`.
   - What's unclear: Should DynamicBufferCalc skip its API call when bat-to-EV is active, or should they compose? The bat-to-EV value is usually higher than the dynamic buffer baseline.
   - Recommendation: Skip `set_buffer_soc()` call when `controller._bat_to_ev_active` is True. The dynamic buffer value is still computed and logged. When bat-to-EV deactivates, dynamic buffer immediately re-applies its value. This avoids value fighting.

2. **Confidence history for the 7-day accuracy component**
   - What we know: CONTEXT.md says confidence combines "historical forecast accuracy (last 7 days) + current weather conditions". Currently `PVForecaster.confidence` is based only on `coverage_hours` (data availability), not on historical accuracy of the forecast vs actual.
   - What's unclear: Phase 3 implemented `PVForecaster.update_correction()` which tracks the correction coefficient (actual/forecast ratio) as an EMA. This is related to accuracy but not the same as a 7-day accuracy metric.
   - Recommendation: For Phase 5, use `PVForecaster.confidence` (0.0-1.0 from coverage_hours) as the primary input. The "historical accuracy" component can be approximated by the correction coefficient: correction far from 1.0 indicates the forecast has been consistently wrong. A combined formula: `effective_confidence = pv_forecaster.confidence * (1 - abs(correction - 1.0) * 0.3)`. This reduces confidence when the forecast has been systematically off, without requiring a separate accuracy DB. Document this as an approximation subject to future refinement.

3. **Chart data for 7-day history — restart persistence**
   - What we know: `_log` is persisted to JSON. On restart, `_load()` reconstructs the log from JSON.
   - What's unclear: The current `_load()` stub does not actually reconstruct `BufferEvent` objects from the saved dict (marked with `pass` comment in example code).
   - Recommendation: In `_load()`, reconstruct log entries as plain dicts (not full `BufferEvent` objects) since they're only used for the chart/table. Store as `deque` of dicts after load. `step()` can convert `BufferEvent` to dict for append. This simplifies the restore path.

---

## Sources

### Primary (HIGH confidence)

- Direct source code analysis of `PVForecaster` (`rootfs/app/forecaster/pv.py`) — `confidence` property, `_correction`, `_coverage_hours`, `_save()` pattern
- Direct source code analysis of `StateStore` (`rootfs/app/state_store.py`) — update() signature, SSE broadcast, `_snapshot_to_json_dict()` pattern
- Direct source code analysis of `Controller` (`rootfs/app/controller.py`) — `set_buffer_soc()` usage, `_bat_to_ev_active` flag
- Direct source code analysis of `main.py` — main loop structure, component initialization, `store.update()` call pattern
- Direct source code analysis of `state.py` — `SystemState.price_spread`, `PlanHorizon`, data structures
- Direct source code analysis of `dashboard.html` + `app.js` — existing SSE handler pattern, CSS conventions, section structure
- Direct source code analysis of `decision_log.py` — `DecisionLog` pattern for in-memory bounded log with categories
- Direct source code analysis of `test_planner.py` — test conventions: `python -m unittest`, mock objects, self-contained tests

### Secondary (MEDIUM confidence)

- CONTEXT.md Phase 5 user decisions — locked formula parameters, dashboard spec, observation mode behavior
- STATE.md — existing concern "DynamicBufferCalc formula coefficients are design estimates — plan 2-4 week observation period"

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — stdlib only, no new dependencies, all patterns directly observed in codebase
- Architecture: HIGH — all integration points verified in source (set_buffer_soc, StateStore.update, SSE, main loop)
- Pitfalls: HIGH — lock contention and bat-to-EV conflict verified from actual code; timestamp persistence from pattern in PVForecaster
- Formula coefficients: MEDIUM — design estimates per STATE.md concern; observation mode exists precisely to calibrate these

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable codebase, no fast-moving dependencies)
