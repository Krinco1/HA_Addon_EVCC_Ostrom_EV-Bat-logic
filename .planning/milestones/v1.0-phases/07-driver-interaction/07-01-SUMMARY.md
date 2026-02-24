---
phase: 07-driver-interaction
plan: 01
subsystem: override-manager
tags: [boost-charge, driver-interaction, telegram, dashboard, thread-safety]
dependency_graph:
  requires: [06-02-SUMMARY.md, notification.py, web/server.py, main.py, evcc_client.py]
  provides: [OverrideManager class, /override/boost endpoint, /override/cancel endpoint, /override/status endpoint, Boost Charge dashboard button, Telegram /boost and /stop commands]
  affects: [main.py decision loop, web/server.py API, notification.py Telegram handlers, app.js vehicle cards, dashboard.html CSS]
tech_stack:
  added: [threading.Timer for 90-min expiry, threading.Lock for thread-safety, dataclasses.dataclass for ActiveOverride]
  patterns: [last-activated-wins override, late attribute injection (srv.override_manager), daemon timer threads, overnight quiet-hours range check]
key_files:
  created: [evcc-smartload/rootfs/app/override_manager.py]
  modified:
    - evcc-smartload/rootfs/app/main.py
    - evcc-smartload/rootfs/app/web/server.py
    - evcc-smartload/rootfs/app/notification.py
    - evcc-smartload/rootfs/app/web/static/app.js
    - evcc-smartload/rootfs/app/web/templates/dashboard.html
decisions:
  - "last-activated-wins: new Boost replaces any existing override without requiring explicit cancel"
  - "cancel() does NOT call evcc — main loop restores LP-controlled mode on next cycle"
  - "quiet hours guard returns German message; chat_id used for direct Telegram notification when blocked"
  - "override_manager injected into notifier as late attribute (same pattern as buffer_calc, sequencer)"
  - "Boost button ID uses vehicle name with spaces replaced by underscores for safe DOM ID"
  - "SSE payload does not yet include override field — fetchOverrideStatus() polls on demand"
metrics:
  duration_minutes: 4
  tasks_completed: 2
  files_created: 1
  files_modified: 5
  completed_date: "2026-02-23"
---

# Phase 7 Plan 01: Boost Charge Override System Summary

Implemented a thread-safe Boost Charge override that lets drivers bypass the LP planner for immediate EV charging, accessible from the dashboard vehicle card and Telegram bot, with 90-minute auto-expiry, quiet-hours guard, and cancel support.

## What Was Built

### override_manager.py (new)

`OverrideManager` class with:

- `ActiveOverride` dataclass: `vehicle_name`, `activated_at`, `expires_at`, `activated_by`
- `activate(vehicle_name, source, chat_id)`: quiet-hours check, last-activated-wins, sets evcc to "now" mode, starts 90-min daemon timer
- `cancel()`: clears active override and cancels timer; main loop restores LP mode on next cycle
- `get_status()`: thread-safe snapshot with remaining_minutes
- `_on_expiry()`: notifies all driver chat_ids via Telegram when boost expires
- `_is_quiet(now)`: overnight-aware quiet hours range check (mirrors ChargeSequencer._is_quiet())

### main.py changes

- Import and initialize `OverrideManager(cfg, evcc, notifier)` after notifier setup
- Inject `override_manager` into notifier and web server via late attribute assignment
- Main decision loop checks `override_manager.get_status()["active"]` before composing `final` Action
- When override active: EV action forced to 1 (charge) with no price limit; LP plan does not control EV

### web/server.py changes

- `self.override_manager = None` in `__init__`
- `GET /override/status` → `_api_override_status()`
- `POST /override/boost` → `_api_override_boost(body)` (vehicle required in JSON body)
- `POST /override/cancel` → `_api_override_cancel()`
- All endpoints return 503-equivalent dict if override_manager not available

### app.js changes

- `_overrideStatus` and `_overridePollInterval` globals
- `fetchOverrideStatus()`: polls `/override/status` and re-renders vehicle cards
- `activateBoost(vehicleName, btnId)`: POST to `/override/boost`, inline feedback on button
- `cancelBoost()`: POST to `/override/cancel`, refreshes cards
- `renderDevice()`: Boost Charge button on each non-battery vehicle card showing active state and remaining time
- `renderPlanGantt()`: orange override banner at top of current slot when boost active
- `applySSEUpdate()`: handles optional `override` field in SSE payload
- Initial `fetchOverrideStatus()` call on page load

### dashboard.html changes

- CSS classes: `.boost-btn`, `.boost-active`, `.boost-blocked`, `.boost-cancel`
- Consistent with dark-theme dashboard color palette

### notification.py changes

- `self.override_manager = None` late attribute
- Registers `boost_` callback prefix → `_handle_boost_callback(chat_id, data)`
- `_handle_text_message()` now routes `/boost` and `/stop` before numeric SoC handling
- `_handle_boost_callback()`: parses `boost_KIA_EV9` → `KIA EV9`, calls `override_manager.activate()`
- `_handle_boost_command()`: `/boost [Fahrzeug]`, auto-selects vehicle if driver has only one
- `_handle_stop_command()`: `/stop` → `override_manager.cancel()`
- Charge inquiry keyboard now includes `[{"text": "Jetzt laden!", "callback_data": "boost_{key}"}]` row

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

### Files Exist

- evcc-smartload/rootfs/app/override_manager.py — created
- evcc-smartload/rootfs/app/main.py — modified
- evcc-smartload/rootfs/app/web/server.py — modified
- evcc-smartload/rootfs/app/notification.py — modified
- evcc-smartload/rootfs/app/web/static/app.js — modified
- evcc-smartload/rootfs/app/web/templates/dashboard.html — modified

### Commits

- 7e4d836: feat(07-01): add OverrideManager and wire into main loop and API
- 7e47bf8: feat(07-01): add Boost Charge button, Telegram /boost and /stop commands

## Self-Check: PASSED
