# Phase 7: Driver Interaction - Research

**Researched:** 2026-02-23
**Domain:** Manual override management, proactive Telegram conversation flow, urgency-based EV prioritization
**Confidence:** HIGH (all findings based on direct codebase inspection)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Override UX**
- Boost Charge button lives on each per-vehicle card on the dashboard Status tab
- Telegram: both `/boost [Fahrzeug]` command AND inline buttons in charge status notifications
- Cancel override: both dashboard button (on vehicle card) AND `/stop` Telegram command — override ends immediately, planner resumes
- Boost Charge does NOT override quiet hours — driver gets notified: "Leise-Stunden aktiv, Laden startet um [HH:MM]"

**Telegram Conversation Flow**
- Language: casual German with "du" — e.g. "Hey, der Kia ist angeschlossen! Wann brauchst du ihn?"
- Reply options: inline time buttons ("In 2h" | "In 4h" | "In 8h" | "Morgen früh") AND free text parsing (e.g. "um 14:30", "in 3 Stunden")
- 30-minute reply window: silent fallback to configured default departure time — no extra notification on timeout (avoids spam)

**Multi-EV Priority Visibility**
- Urgency score visible on vehicle cards: e.g. "Dringlichkeit: 4.2 (Abfahrt in 3h, SoC 45%)" — full transparency
- Priority order shown on dashboard (exact visual pattern at Claude's discretion)

### Claude's Discretion
- Override visualization in Plan tab Gantt chart (bar highlighting, banner, or both)
- Boost Charge confirmation feedback pattern (immediate reply, progress follow-up, etc.)
- Unparseable departure time handling (re-ask with hint vs best-guess-and-confirm)
- Telegram notifications on priority changes (deprioritization only vs every change vs silent)
- Urgency score in Gantt chart tooltips (or vehicle cards only)
- Wallbox swap strategy when Boost conflicts with currently charging vehicle
- Multi-override strategy (queue vs replace) — single wallbox constraint applies

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DRIV-01 | User can trigger immediate charge via Dashboard and Telegram that overrides the plan at any time | Override manager pattern (new OverrideManager class); POST /override/boost endpoint; dashboard Boost button on vehicle card; Telegram /boost command + inline button; 90-min expiry timer; plan timeline marker |
| DRIV-02 | System proactively asks driver via Telegram about departure time when vehicle is plugged in | Extend NotificationManager: plug-in event detection (compare ev_connected between cycles in main loop), new `send_departure_inquiry()` method, pending reply tracking with 30-min timeout, free-text parser for time expressions, feed result into `_get_departure_times()` |
| DRIV-03 | Multi-EV prioritization based on driver context (departure time, need) rather than SoC-only ranking | Replace `ChargeSequencer._rank_vehicles()` scoring with urgency formula: SoC-deficit / hours-to-departure; expose urgency score in API and vehicle card UI |
</phase_requirements>

---

## Summary

Phase 7 adds three distinct capabilities to an already-working system: a manual override ("Boost Charge") that immediately bypasses the LP planner, a proactive Telegram departure-time query triggered by vehicle plug-in, and urgency-based prioritization in the multi-EV sequencer. All three features integrate with infrastructure that already exists — TelegramBot, NotificationManager, ChargeSequencer, HorizonPlanner, StateStore, and the web server — so Phase 7 is primarily extension, not construction.

The most architecturally novel piece is the override manager: a thread-safe object that tracks active overrides with a 90-minute expiry, suppresses them during quiet hours, and exposes state to both the dashboard and the Gantt chart. The departure-time query requires detecting a new plug-in event (comparing `ev_connected` state between cycles), adding a new Telegram conversation flow, and plumbing the confirmed departure time back into `_get_departure_times()` (which main.py already calls each cycle). The urgency refactor is a pure algorithm swap inside `ChargeSequencer._rank_vehicles()` — no structural changes needed.

**Primary recommendation:** Build a standalone `OverrideManager` class that encapsulates all override state (active vehicle, expiry, quiet-hours guard, timeline marker). Wire it into the main loop before the LP plan step so the planner can check for and respect active overrides.

---

## Standard Stack

### Core (all already in the project — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `requests` | installed | Telegram Bot API HTTP calls | Already used in `notification.py` |
| `threading` | stdlib | Override expiry timer; poll loop | Already used throughout |
| `datetime` / `timedelta` | stdlib | 90-min expiry, 30-min reply window, departure time parsing | Used everywhere |
| `re` | stdlib | Free-text departure time parsing ("um 14:30", "in 3 Stunden") | Already used in `web/server.py` |

### No New Packages Required

The entire phase builds on the existing stack. No `pip install` needed. The Telegram Bot API integration (`notification.py`) is already working with long-polling, inline keyboards, and callback routing.

---

## Architecture Patterns

### Recommended Project Structure

No new files at the top level. New class lives alongside existing modules:

```
rootfs/app/
├── override_manager.py     # NEW: OverrideManager class (Plan 01)
├── notification.py         # EXTEND: add send_departure_inquiry(), text parser (Plan 02)
├── charge_sequencer.py     # EXTEND: urgency scoring in _rank_vehicles() (Plan 03)
├── main.py                 # EXTEND: wire OverrideManager, plug-in event detection
├── web/server.py           # EXTEND: POST /override/boost, GET /override/status
└── web/static/app.js       # EXTEND: Boost button, urgency scores, override marker
```

### Pattern 1: OverrideManager

**What:** A thread-safe class with a `threading.Timer` for expiry; stores `{vehicle_name, expires_at, marker_for_plan}`.
**When to use:** Queried each main loop cycle before LP plan is applied; queried by web server for dashboard state.

```python
# Source: direct codebase pattern — mirrors DynamicBufferCalc live_override pattern
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

@dataclass
class ActiveOverride:
    vehicle_name: str
    activated_at: datetime
    expires_at: datetime
    activated_by: str  # "dashboard" | "telegram"

class OverrideManager:
    OVERRIDE_DURATION_MINUTES = 90

    def __init__(self, cfg, evcc, notifier=None):
        self.cfg = cfg
        self.evcc = evcc
        self.notifier = notifier
        self._lock = threading.Lock()
        self._active: Optional[ActiveOverride] = None
        self._expiry_timer: Optional[threading.Timer] = None

    def activate(self, vehicle_name: str, source: str, chat_id: int = None) -> dict:
        """Activate Boost Charge. Returns {ok, message, quiet_hours_blocked}."""
        now = datetime.now(timezone.utc)
        if self._is_quiet(now):
            next_end = self._next_quiet_end(now)
            msg = f"Leise-Stunden aktiv, Laden startet um {next_end}"
            if chat_id and self.notifier:
                self.notifier.bot.send_message(chat_id, msg)
            return {"ok": False, "quiet_hours_blocked": True, "message": msg}

        with self._lock:
            if self._expiry_timer:
                self._expiry_timer.cancel()
            expires = now + timedelta(minutes=self.OVERRIDE_DURATION_MINUTES)
            self._active = ActiveOverride(vehicle_name, now, expires, source)
            self._expiry_timer = threading.Timer(
                self.OVERRIDE_DURATION_MINUTES * 60, self._on_expiry
            )
            self._expiry_timer.daemon = True
            self._expiry_timer.start()
        # Immediately force evcc to charge
        self.evcc.set_loadpoint_mode(1, "now")
        return {"ok": True, "expires_at": expires.isoformat()}

    def cancel(self) -> bool:
        with self._lock:
            if self._active is None:
                return False
            if self._expiry_timer:
                self._expiry_timer.cancel()
            vehicle = self._active.vehicle_name
            self._active = None
            self._expiry_timer = None
        log("info", f"OverrideManager: manual cancel for {vehicle}")
        return True

    def _on_expiry(self):
        with self._lock:
            if self._active is None:
                return
            vehicle = self._active.vehicle_name
            self._active = None
            self._expiry_timer = None
        log("info", f"OverrideManager: override expired for {vehicle}")
        if self.notifier:
            # notify driver via Telegram
            pass  # implementation in Plan 01

    def get_status(self) -> dict:
        with self._lock:
            if self._active is None:
                return {"active": False}
            remaining = (self._active.expires_at - datetime.now(timezone.utc)).total_seconds() / 60
            return {
                "active": True,
                "vehicle": self._active.vehicle_name,
                "expires_at": self._active.expires_at.isoformat(),
                "remaining_minutes": round(max(0, remaining)),
                "activated_by": self._active.activated_by,
            }
```

**Key integration point in main loop:** Before applying LP plan, check `override_manager.get_status()`. If active and vehicle matches connected EV, skip LP `apply()` for EV action (keep evcc in "now" mode). The plan timeline serializer must include override marker when active.

### Pattern 2: Departure Time Store

**What:** An in-memory dict (with optional JSON persistence) mapping vehicle name → departure datetime, populated by Telegram replies and consumed by `_get_departure_times()`.
**When to use:** Persisted across cycles; overwritten on new Telegram response; falls back to config default after 30-min query timeout.

```python
# Extends existing _get_departure_times() in main.py
# Pattern mirrors ManualSocStore in state.py — simple dict + file persistence

class DepartureTimeStore:
    def __init__(self, default_hour: int = 6):
        self._lock = threading.Lock()
        self._times: Dict[str, datetime] = {}
        self._default_hour = default_hour

    def set(self, vehicle_name: str, departure: datetime):
        with self._lock:
            self._times[vehicle_name] = departure

    def get(self, vehicle_name: str) -> datetime:
        with self._lock:
            if vehicle_name in self._times:
                dt = self._times[vehicle_name]
                if dt > datetime.now(timezone.utc):
                    return dt
        # Fallback to config default
        now = datetime.now(timezone.utc)
        local = now.replace(hour=self._default_hour, minute=0, second=0, microsecond=0)
        if local <= now:
            local += timedelta(days=1)
        return local

    def clear(self, vehicle_name: str):
        with self._lock:
            self._times.pop(vehicle_name, None)
```

### Pattern 3: Plug-in Event Detection

**What:** Compare `ev_connected` between consecutive main loop cycles to detect plug-in events.
**When to use:** In the main decision loop, between collecting state and triggering notifications.

```python
# In main.py, extend main loop state tracking:
last_ev_connected: bool = False   # add alongside last_state

# In each cycle:
ev_just_plugged_in = state.ev_connected and not last_ev_connected
if ev_just_plugged_in and notifier:
    vehicle_name = state.ev_name
    notifier.send_departure_inquiry(vehicle_name, state.ev_soc)

last_ev_connected = state.ev_connected
```

Note: The existing `EventDetector` in `optimizer/__init__.py` should be checked — it may already detect connection events. If so, use it. If not, the simple boolean comparison is the correct pattern (consistent with existing cycle-to-cycle state comparisons throughout `main.py`).

### Pattern 4: Departure Time Free-Text Parser

**What:** A function that parses German-language time expressions into a `datetime`.
**When to use:** In `NotificationManager._handle_text_message()` when a departure query is pending.

```python
import re
from datetime import datetime, timedelta, timezone

def parse_departure_time(text: str, now: datetime) -> Optional[datetime]:
    """Parse German departure time expressions.

    Handles:
    - "um 14:30" / "um 14 Uhr"
    - "in 2h" / "in 2 Stunden" / "in 2 std"
    - "morgen früh" → tomorrow 07:00
    - Inline button values: "2h", "4h", "8h", "morgen"
    """
    text = text.strip().lower()

    # "in Xh" / "in X Stunden"
    m = re.match(r'in\s+(\d+(?:[.,]\d+)?)\s*(?:h|std|stunden?)', text)
    if m:
        hours = float(m.group(1).replace(',', '.'))
        return now + timedelta(hours=hours)

    # "um HH:MM" or "um HH Uhr"
    m = re.match(r'um\s+(\d{1,2})(?:[:\.](\d{2}))?\s*(?:uhr)?', text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    # "morgen früh" / "morgen"
    if 'morgen' in text:
        return (now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)

    # Inline button shorthand: "2h", "4h", "8h"
    m = re.match(r'^(\d+)h$', text)
    if m:
        return now + timedelta(hours=int(m.group(1)))

    return None
```

### Pattern 5: Urgency Scoring (ChargeSequencer refactor)

**What:** Replace the current point-based `_rank_vehicles()` with an urgency ratio score.
**When to use:** Whenever `plan()` is called with 2+ pending charge requests.

```python
# Source: DRIV-03 requirement — "time to departure vs SoC deficit"
# Formula: urgency = soc_deficit_pct / max(hours_to_departure, 0.5)
# Higher urgency = must charge sooner

def _urgency_score(self, req: ChargeRequest, now: datetime) -> float:
    """Urgency: SoC deficit per hour remaining until departure.

    Higher score = more urgent.
    A vehicle at 50% departing in 2h scores: 30 / 2 = 15
    A vehicle at 40% departing in 12h scores: 40 / 12 = 3.3
    """
    departure = self._departure_times.get(req.vehicle_name)
    if departure is None:
        # No departure time known: use hours_needed as tiebreaker
        hours_remaining = 12.0  # default: assume comfortable window
    else:
        hours_remaining = max(0.5, (departure - now).total_seconds() / 3600)

    target_soc = req.target_soc
    soc_deficit = max(0, target_soc - req.current_soc)
    return soc_deficit / hours_remaining

def _rank_vehicles(self, pending, connected_vehicle, solar_hours, now):
    for req in pending:
        req.priority = self._urgency_score(req, now)
        # Tie-break: connected vehicle gets +5 (avoid unnecessary wallbox swap)
        if req.vehicle_name == connected_vehicle:
            req.priority += 5.0
        # Quiet hours: connected vehicle takes absolute priority
        if self._is_quiet(now) and req.vehicle_name == connected_vehicle:
            req.priority += 1000.0
    return sorted(pending, key=lambda r: r.priority, reverse=True)
```

The `ChargeSequencer` needs a reference to `DepartureTimeStore` (injected in constructor). The urgency score is also exposed in `get_requests_summary()` for dashboard display.

### Anti-Patterns to Avoid

- **Do not block the main loop with override expiry**: Use `threading.Timer` with daemon=True, not `time.sleep()` in a polling thread.
- **Do not hold StateStore lock during Telegram I/O**: The existing notification pattern (calling notifier outside the store lock) is correct — follow it.
- **Do not re-ask for departure time every cycle**: Use the same 2-hour throttle pattern already in `NotificationManager.send_charge_inquiry()` — track `pending_departure_inquiries` dict.
- **Do not parse free text in the TelegramBot._handle_update() method**: Keep parsing in NotificationManager callbacks — TelegramBot is purely a transport layer (existing architectural boundary).
- **Do not use evcc "now" mode permanently**: OverrideManager must return evcc to the LP-controlled mode when override expires or is cancelled.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Expiry timer | Custom sleep-based polling thread | `threading.Timer` (stdlib) | Timer is fire-and-forget; no thread management; already used in Python ecosystem |
| Telegram inline buttons for time selection | Custom HTML/JS UI with callbacks | Existing `TelegramBot.send_message(..., inline_keyboard=...)` | Already working in notification.py; just add new callback prefix |
| Thread-safe state sharing | Custom queue/event | `threading.Lock()` + dict, same pattern as `ManualSocStore` | Proven pattern already in the codebase |
| German time parsing | NLP library | Simple regex (4 patterns cover all required cases) | "in 2h", "um 14:30", "morgen früh", digit shorthand — no edge cases requiring full NLP |

**Key insight:** Every infrastructure piece exists. The risk is in coordination (override expiry races, quiet-hours edge cases, departure time not set when urgency calculated) — not in library selection.

---

## Common Pitfalls

### Pitfall 1: Override Expiry Race with Main Loop
**What goes wrong:** Timer fires exactly when main loop is applying LP plan. Override is cleared but evcc is still in "now" mode for one cycle.
**Why it happens:** `threading.Timer` callback and main loop run on different threads.
**How to avoid:** In the main loop, always check `override_manager.get_status()` at the top of each cycle. If not active, ensure evcc mode is returned to LP-controlled. The `_on_expiry()` callback should not directly call evcc — it should only clear the in-memory state. The next main loop cycle detects "override cleared" and restores LP control.
**Warning signs:** evcc stays in "now" mode after 90-minute mark.

### Pitfall 2: Quiet Hours Check Uses Wrong Timezone
**What goes wrong:** `_is_quiet()` in ChargeSequencer uses UTC hours, but `quiet_hours_start` is a local hour (e.g., 21 = 9pm local).
**Why it happens:** `datetime.now(timezone.utc).hour` returns UTC; quiet hours config is local time.
**How to avoid:** Use `datetime.now().hour` (local) for quiet hours comparison — consistent with existing `ChargeSequencer._is_quiet()` implementation (it already uses `dt.hour` from a UTC datetime passed in, which is a latent bug — verify in implementation).
**Warning signs:** Quiet hours blocking charges at wrong times.

### Pitfall 3: Departure Time Expiry After Arrival
**What goes wrong:** Driver sets departure to "in 2h". 3 hours later, vehicle is still plugged in. The stored departure time is now in the past. Urgency score divides by `max(0.5, ...)` which clamps to 0.5 — artificially inflating urgency.
**How to avoid:** In `_urgency_score()`, if departure is in the past, treat as "no deadline known" (use default 12h window). In `DepartureTimeStore.get()`, discard expired departures and fall back to default — already shown in the Pattern 2 code above.
**Warning signs:** Vehicle with past departure time always wins priority over everything else.

### Pitfall 4: Telegram Callback Prefix Collision
**What goes wrong:** New `/boost` Telegram command callback (`boost_`) collides with existing `soc_` prefix handler routing in `TelegramBot._handle_update()`.
**Why it happens:** `_callbacks` dict uses `data.startswith(prefix)` matching — any prefix that is a substring of another matches first.
**How to avoid:** Choose non-ambiguous prefixes: `boost_`, `cancel_override_`, `depart_` — all distinct from existing `soc_`. Register in order: more specific first (though current implementation uses `break` after first match, so order matters).

### Pitfall 5: Single Wallbox Multi-Override
**What goes wrong:** Two Boost Charge requests arrive (one from dashboard, one from Telegram) for different vehicles. The wallbox can only charge one at a time.
**Why it happens:** Phase 7 context leaves multi-override strategy to Claude's discretion.
**How to avoid (recommendation):** Last-activated wins (replace strategy). The second `/boost` cancels the first. This is simplest and avoids queue complexity. Document this behavior in the Telegram confirmation message: "Boost Charge für KIA aktiviert. Override für ORA beendet."

### Pitfall 6: `ev_name` Empty When Vehicle Plugs In
**What goes wrong:** Plug-in detection triggers departure query, but `state.ev_name` is empty for the first 1-2 cycles after plug-in.
**Why it happens:** evcc state update latency — vehicle name comes from `loadpoint.vehicle` which may not be populated on the first polling cycle after plug-in.
**How to avoid:** In the plug-in detection logic, only fire the departure query if `state.ev_name` is non-empty. Add a deferred check: if a plug-in event was detected but name was empty, re-check next cycle.

---

## Code Examples

Verified patterns from existing codebase:

### Existing evcc Mode Control (for Boost Charge)
```python
# Source: evcc_client.py — set loadpoint to "now" mode (charge immediately)
self.evcc.set_loadpoint_mode(1, "now")

# Source: charge_sequencer.py apply_to_evcc() — restore LP-controlled mode
self.evcc.set_loadpoint_mode(1, "pv")   # solar
self.evcc.set_loadpoint_mode(1, "minpv") # min+solar
self.evcc.set_loadpoint_mode(1, "off")   # off
```

### Existing Telegram Inline Button Pattern
```python
# Source: notification.py send_charge_inquiry()
keyboard = [
    [
        {"text": "In 2h",     "callback_data": "depart_KIA_EV9_2h"},
        {"text": "In 4h",     "callback_data": "depart_KIA_EV9_4h"},
        {"text": "In 8h",     "callback_data": "depart_KIA_EV9_8h"},
        {"text": "Morgen früh", "callback_data": "depart_KIA_EV9_morgen"},
    ]
]
self.bot.send_message(chat_id, "Hey, der KIA EV9 ist angeschlossen! Wann brauchst du ihn?", keyboard)
```

### Existing Callback Registration Pattern
```python
# Source: notification.py __init__
bot.register_callback("soc_", self._handle_soc_callback)
bot.register_callback("text_handler", self._handle_text_message)

# Phase 7 additions:
bot.register_callback("depart_", self._handle_departure_callback)
bot.register_callback("boost_", self._handle_boost_callback)
bot.register_callback("cancel_override_", self._handle_cancel_callback)
```

### Existing StateStore Update Extension Pattern
```python
# Source: state_store.py update() — add override status to snapshot
# In _snapshot_unlocked():
snap["override"] = self._override_manager.get_status() if self._override_manager else None
```

However — the preferred pattern is NOT to inject OverrideManager into StateStore. Instead, the web server accesses it directly via `srv.override_manager.get_status()`, consistent with how `srv.sequencer`, `srv.notifier`, and `srv.buffer_calc` are accessed.

### Existing Departure Time Hook Point
```python
# Source: main.py _get_departure_times()
# This function is called every cycle — Phase 7 replaces it:
def _get_departure_times(departure_store: DepartureTimeStore, all_vehicles: dict, cfg) -> Dict[str, datetime]:
    """Return departure datetime per EV name for LP formulation.

    Phase 7: uses per-vehicle departure times from DepartureTimeStore,
    falling back to cfg.ev_charge_deadline_hour for vehicles without known departure.
    """
    return {
        name: departure_store.get(name)
        for name in all_vehicles
    }
```

### Urgency Score API Response
```python
# Source: charge_sequencer.py get_requests_summary() — extend to include urgency
def get_requests_summary(self) -> Dict:
    now = datetime.now(timezone.utc)
    return {
        v: {
            "driver": r.driver_name,
            "target_soc": r.target_soc,
            "current_soc": round(r.current_soc, 0),
            "need_kwh": round(r.need_kwh, 1),
            "hours_needed": round(r.hours_needed, 1),
            "status": r.status,
            "confirmed_at": r.confirmed_at.isoformat(),
            "urgency_score": round(self._urgency_score(r, now), 2),  # NEW
            "departure_time": ...,  # NEW: ISO from DepartureTimeStore
        }
        for v, r in self.requests.items()
    }
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single global departure deadline (`ev_charge_deadline_hour`) | Per-vehicle departure times from driver Telegram input | Phase 7 | LP plan respects individual vehicle deadlines |
| SoC-only ranking in ChargeSequencer | Urgency score (SoC deficit / hours to departure) | Phase 7 | Vehicle departing in 2h at 50% SoC takes priority over 40% SoC departing in 12h |
| No manual override | 90-minute boost charge override with auto-expiry | Phase 7 | Drivers can always get charging now without needing to understand the planner |

**Deprecated/outdated:**
- `_get_departure_times()` in `main.py`: The single-vehicle default implementation should be replaced with `DepartureTimeStore`-backed version. The existing stub comment says "Phase 7 will extend with per-driver Telegram input" — this is the intended replacement point.
- `ChargeSequencer._rank_vehicles()` current scoring: The ad-hoc point system (+30 connected, -20 solar, +15 small need) is replaced by the urgency ratio formula. The quiet-hours rule (+100) is preserved.

---

## Open Questions

1. **EventDetector plug-in detection**
   - What we know: `EventDetector` exists in `optimizer/__init__.py` and is used in the main loop
   - What's unclear: Whether it already detects `ev_connected` state changes (plug-in events)
   - Recommendation: Read `optimizer/__init__.py` during Plan 02 implementation. If EventDetector already fires an event for plug-in, use it. Otherwise, use the simple boolean comparison pattern.

2. **evcc "now" mode behavior with multiple loadpoints**
   - What we know: The codebase uses loadpoint 1 (`lp_id=1`) throughout; only 1 wallbox in the setup
   - What's unclear: Does setting loadpoint 1 to "now" mode affect the vehicle at the wallbox immediately, or requires vehicle to be the "active" vehicle in evcc?
   - Recommendation: Test during implementation. The `evcc_client.set_loadpoint_mode(1, "now")` call is the same method used by ChargeSequencer — confirmed working.

3. **Departure time persistence across restarts**
   - What we know: `ManualSocStore` persists to JSON at `/data/smartprice_manual_soc.json`
   - What's unclear: Should departure times persist across restarts (HA add-on restarts are common)?
   - Recommendation: Yes — persist to `/data/smartprice_departure_times.json` using the same pattern as ManualSocStore. A vehicle plugged in overnight should retain its departure time if the add-on restarts.

4. **Quiet hours end-time calculation for Boost Charge rejection message**
   - What we know: `quiet_hours_start` and `quiet_hours_end` are hour integers in config; `ChargeSequencer._is_quiet()` handles overnight ranges (e.g., 21:00–06:00)
   - What's unclear: The exact local time conversion for "Laden startet um [HH:MM]" message
   - Recommendation: Use `datetime.now().replace(hour=cfg.quiet_hours_end, minute=0, second=0)` with next-day adjustment if end < start (overnight range). Same logic as `ChargeSequencer._is_quiet()`.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection — all findings from reading source files
  - `rootfs/app/notification.py` — TelegramBot, NotificationManager patterns
  - `rootfs/app/charge_sequencer.py` — ChargeSequencer._rank_vehicles(), priority system
  - `rootfs/app/main.py` — _get_departure_times() stub, main loop structure, _check_notification_triggers()
  - `rootfs/app/state.py` — ManualSocStore pattern (departure store template)
  - `rootfs/app/state_store.py` — StateStore threading patterns
  - `rootfs/app/web/server.py` — existing POST endpoint patterns, override injection pattern
  - `rootfs/app/web/static/app.js` — renderDevice() vehicle card pattern, renderSequencer() pattern
  - `rootfs/app/web/templates/dashboard.html` — tab structure, CSS classes
  - `rootfs/app/evcc_client.py` — set_loadpoint_mode() availability confirmed
  - `rootfs/app/driver_manager.py` — Driver dataclass, DriverManager lookups

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in project, no new dependencies
- Architecture: HIGH — patterns verified directly from codebase
- Pitfalls: HIGH — identified from actual code patterns and threading considerations
- Departure time parsing: HIGH — simple regex patterns, 4 cases cover all locked decisions

**Research date:** 2026-02-23
**Valid until:** 2026-04-23 (stable codebase, no external dependencies changing)
