---
phase: 07-driver-interaction
plan: 03
subsystem: charge-sequencer
tags: [urgency-scoring, vehicle-ranking, dashboard-ui, departure-time]
dependency_graph:
  requires: ["07-02"]
  provides: ["urgency-based-ranking", "sequencer-urgency-api", "urgency-dashboard"]
  affects: ["charge_sequencer.py", "main.py", "app.js"]
tech_stack:
  added: []
  patterns: ["urgency = SoC-deficit / hours-to-departure", "late-attribute-injection", "list-vs-dict API fix"]
key_files:
  created: []
  modified:
    - evcc-smartload/rootfs/app/charge_sequencer.py
    - evcc-smartload/rootfs/app/main.py
    - evcc-smartload/rootfs/app/web/static/app.js
decisions:
  - "get_requests_summary() return type changed from dict to list (each entry has 'vehicle' key) — fixes pre-existing JS array/dict mismatch"
  - "Past departure times treated as no-deadline (12h default) per Research Pitfall 3"
  - "0.5h floor on hours_remaining prevents inflating urgency for imminent departures"
  - "Connected vehicle tie-break +5.0 (not enough to override large urgency difference)"
  - "Quiet hours absolute priority +1000.0 (always beats urgency scoring)"
  - "urgency color: red >= 10, amber >= 3, blue < 3"
metrics:
  duration: "3 min"
  completed: "2026-02-23"
  tasks_completed: 2
  files_modified: 3
---

# Phase 7 Plan 03: Urgency-Based Vehicle Ranking Summary

**One-liner:** Urgency scoring (SoC deficit / hours to departure) replaces old point system in ChargeSequencer, with transparent urgency info on dashboard vehicle cards.

## What Was Built

### Task 1 — ChargeSequencer urgency scoring

Added `_urgency_score(req, now) -> float` computing `soc_deficit / hours_remaining` where:
- `hours_remaining = max(0.5, time_until_departure)` from `departure_store.get(vehicle_name)`
- Past departures fall back to 12h default (avoids artificially inflating urgency)
- No `departure_store`: uses 12h default window

Added `_urgency_reason(req, now) -> str` returning German text:
- With user-set departure: `"Abfahrt in 3h, SoC 45%"`
- With config default: `"Standard-Abfahrt 6:00, SoC 45%"`
- Without departure_store: `"SoC 45%, Bedarf 35%"`

Refactored `_rank_vehicles()` — urgency replaces old point system:
- `req.priority = _urgency_score(req, now)`
- Connected vehicle tie-break: `+5.0` (avoids unnecessary wallbox swaps)
- Quiet hours absolute priority: `+1000.0` (connected vehicle always wins at night)
- Log ranking result for observability

Updated `get_requests_summary()`:
- Now returns `List[Dict]` instead of `Dict[str, Dict]` — fixes pre-existing JS/Python mismatch where JS treated the response as an array
- Each entry includes `vehicle` key, `urgency_score`, `urgency_reason`, `departure_time`
- Sorted by `urgency_score` descending

`main.py`: added `sequencer.departure_store = departure_store` (late-assignment pattern, after both objects are created).

### Task 2 — Dashboard vehicle cards

Updated `renderSequencer()` in `app.js`:
- `showUrgency = requests.length >= 2` guard — urgency hidden for single-vehicle case
- Priority badge `P1`/`P2`/... on card header (green for #1, grey for others)
- Urgency row shows: `Dringlichkeit: 15.0 (Abfahrt in 2h, SoC 50%)` with color coding
  - Red: score >= 10 (very urgent)
  - Amber: score >= 3 (moderate urgency)
  - Blue: score < 3 (low urgency)
- Shows `Voll geladen` when urgency_score == 0
- Shows `Abfahrt: HH:MM` when `departure_time` known
- All cards remain sorted by urgency_score (server provides pre-sorted list)

## Verification Results

Success criteria satisfied:

- EV departing in 2h at 50% SoC: urgency = 15.0 (30/2)
- EV departing in 12h at 40% SoC: urgency ~3.3–4.1 (depends on exact time calc)
- EV1 (15.0) > EV2 (4.1) — correct priority order
- Dashboard shows "Dringlichkeit: 15.0 (Abfahrt in 2h, SoC 50%)" — verified by grep (5 patterns)
- Connected vehicle tie-break: +5.0 prevents unnecessary wallbox swap
- Quiet hours: connected vehicle gets +1000.0 — always wins at night
- Past departure times: treated as 12h default (no urgency inflation)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed get_requests_summary() return type mismatch**
- **Found during:** Task 1
- **Issue:** `get_requests_summary()` returned `Dict[str, Dict]` but JS treated it as `Array` using `.length` — the requests section was never rendered
- **Fix:** Changed return type to `List[Dict]`, each entry includes `vehicle` key. Sorted by `urgency_score` descending (server-side ordering simplifies JS).
- **Files modified:** `evcc-smartload/rootfs/app/charge_sequencer.py`
- **Commit:** 3095088

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 3095088 | feat(07-03): urgency-based vehicle ranking in ChargeSequencer |
| Task 2 | 17d4211 | feat(07-03): urgency score display on dashboard vehicle cards |

## Self-Check: PASSED

- [x] `charge_sequencer.py` modified with `_urgency_score`, `_urgency_reason`, updated `_rank_vehicles`, updated `get_requests_summary`
- [x] `main.py` injects `departure_store` into `sequencer`
- [x] `app.js` shows urgency info with `Dringlichkeit` label, priority badges, departure time
- [x] Commits 3095088 and 17d4211 exist
- [x] All 7 verification criteria from plan satisfied
