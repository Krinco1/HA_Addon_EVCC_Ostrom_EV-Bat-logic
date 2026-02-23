---
phase: 07-driver-interaction
plan: 02
subsystem: departure-time-queries
tags: [departure-time, driver-interaction, telegram, persistence, thread-safety, german-nlp]
dependency_graph:
  requires: [07-01-SUMMARY.md, notification.py, main.py, web/server.py, driver_manager.py]
  provides: [DepartureTimeStore class, parse_departure_time() function, departure Telegram inquiry flow, /departure-times API endpoint]
  affects: [main.py decision loop, _get_departure_times() HorizonPlanner input, notification.py Telegram handlers, web/server.py API]
tech_stack:
  added: [departure_store.py (new), threading.Lock for thread-safety, JSON file persistence at /data/smartprice_departure_times.json]
  patterns: [late attribute injection (notifier.departure_store, web.departure_store), pending-inquiry timeout pattern (30-min TTL), German regex parser for time expressions, deferred ev_name guard for plug-in detection]
key_files:
  created:
    - evcc-smartload/rootfs/app/departure_store.py
  modified:
    - evcc-smartload/rootfs/app/main.py
    - evcc-smartload/rootfs/app/notification.py
    - evcc-smartload/rootfs/app/web/server.py
decisions:
  - "morgen frueh (with 'ue') accepted by regex in addition to morgen frueh with actual umlaut — handles German ASCII substitution"
  - "parse_departure_time() supports German comma decimals (2,5 Stunden -> 2.5h) via str.replace(',', '.')"
  - "plug-in detection defers last_ev_connected update until ev_name is known or EV disconnects — avoids false-negative on next cycle when evcc is slow to resolve vehicle"
  - "departure_store injected as late attribute into notifier and web server (same pattern as override_manager, buffer_calc)"
  - "_get_departure_times() signature extended to accept departure_store and state; backward-compatible None fallback preserved"
  - "is_inquiry_pending() side-effects: auto-removes stale entries (>30 min) — no separate cleanup job needed"
  - "_handle_departure_callback() uses rsplit('_', 1) to split on last underscore — correctly handles vehicle names containing underscores (e.g. KIA_EV9)"
metrics:
  duration_minutes: 4
  tasks_completed: 2
  files_created: 1
  files_modified: 3
  completed_date: "2026-02-23"
---

# Phase 7 Plan 02: Departure Time Queries Summary

Proactive Telegram departure-time inquiry system: detects EV plug-in events, sends German-language inline-button message asking the driver when they need the vehicle, parses button or free-text replies, stores the confirmed departure time with JSON persistence, and feeds it into the HorizonPlanner each cycle via DepartureTimeStore.

## What Was Built

### departure_store.py (new)

`parse_departure_time(text, now)` — standalone German time parser:

- `"in 2h"` / `"in 2 Stunden"` / `"in 3 std"` → now + N hours
- `"in 2,5 Stunden"` → 2.5 hours (German comma decimal support)
- `"um 14:30"` / `"um 14 Uhr"` → today at HH:MM (tomorrow if time passed)
- `"morgen"` / `"morgen frueh"` / `"morgen früh"` → tomorrow at 07:00
- Bare shorthands: `"2h"`, `"4h"`, `"8h"` → now + N hours
- Returns None for unparseable input

`DepartureTimeStore` class:

- `set(vehicle_name, departure)`: store ISO string, remove pending-inquiry entry, persist to JSON
- `get(vehicle_name)`: return stored future departure, or next occurrence of `default_hour` as fallback
- `clear(vehicle_name)`: remove departure + pending entry, persist
- `mark_inquiry_sent(vehicle_name)`: record UTC timestamp in `_pending_inquiries`
- `is_inquiry_pending(vehicle_name)`: check 30-min TTL; auto-removes expired entries
- `_load()` / `_save()`: JSON persistence at `/data/smartprice_departure_times.json`, handles missing/corrupt file gracefully

### main.py changes

- Import `DepartureTimeStore`
- Initialize `departure_store = DepartureTimeStore(default_hour=cfg.ev_charge_deadline_hour)` with try/except fallback to None
- Inject into notifier (`notifier.departure_store = departure_store`) and web server (`web.departure_store = departure_store`) as late attributes
- State variables `last_ev_connected = False` and `last_ev_name = ""` before main loop
- Plug-in detection block after `collector.get_current_state()`:
  - `ev_just_plugged_in = state.ev_connected and not last_ev_connected`
  - Guard: only trigger if `state.ev_name` is known (deferred name guard)
  - 30-min spam guard: `departure_store.is_inquiry_pending()` before sending
  - `last_ev_connected` updated only when `ev_name` resolved or EV disconnected
- `_get_departure_times(departure_store, cfg, state)` updated signature:
  - Returns `{vehicle_name: departure_store.get(vehicle_name)}` for connected vehicle
  - Falls back to `{"_default": cfg.ev_charge_deadline_hour}` when departure_store is None

### notification.py changes

- `self.departure_store = None` late attribute in `__init__`
- `self._pending_departure_vehicle: Optional[str] = None` for free-text reply tracking
- Registers `depart_` callback prefix → `_handle_departure_callback()`
- `send_departure_inquiry(vehicle_name, current_soc)`:
  - 4-button inline keyboard: `depart_{safe_name}_2h`, `_4h`, `_8h`, `_morgen`
  - German casual "du" tone message
  - Sends to vehicle's driver or all drivers with Telegram if no specific driver found
  - Sets `_pending_departure_vehicle` for free-text matching
- `_handle_departure_callback(chat_id, data)`:
  - Parses `depart_KIA_EV9_4h` → vehicle "KIA EV9", time "4h" via `rsplit("_", 1)`
  - Calls `parse_departure_time()`, stores via `departure_store.set()`
  - German confirmation reply with local time
- `_handle_text_message()`: departure check at TOP before SoC handling:
  - If pending departure + `is_inquiry_pending()`: try `parse_departure_time()`
  - If parsed: store, clear pending, send confirmation
  - If not parsed: send hint message, keep pending (allow retry)

### web/server.py changes

- `self.departure_store = None` in `__init__`
- `GET /departure-times` → `_api_departure_times()`: returns `{vehicle_name: departure_iso}` for connected vehicle; guards with None check

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed "morgen frueh" regex not matching ASCII umlaut substitute**

- **Found during:** Task 1 extended verification
- **Issue:** Regex `fr[uü]h` matches `fruh` and `früh` but not `frueh` (German ASCII substitution for ü)
- **Fix:** Changed to `frueh|fr[uü]h` to accept all three variants
- **Files modified:** `evcc-smartload/rootfs/app/departure_store.py`
- **Commit:** 8f083e7

## Self-Check

### Files Exist

- evcc-smartload/rootfs/app/departure_store.py — created
- evcc-smartload/rootfs/app/main.py — modified
- evcc-smartload/rootfs/app/notification.py — modified
- evcc-smartload/rootfs/app/web/server.py — modified

### Commits

- 8f083e7: feat(07-02): add DepartureTimeStore with JSON persistence and German departure time parser
- 74815cf: feat(07-02): plug-in detection, Telegram departure inquiry, and _get_departure_times() integration

## Self-Check: PASSED
