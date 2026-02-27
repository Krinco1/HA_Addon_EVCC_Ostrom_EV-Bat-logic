---
phase: 12-lp-gated-battery-arbitrage
verified: 2026-02-27T22:00:00Z
status: passed
score: 5/5 must-haves verified
re_verification: false
human_verification:
  - test: "Connect EV, set mode to 'now', verify banner appears with savings"
    expected: "Dashboard shows 'Batterie speist EV (spare X ct/kWh, Y kWh verfuegbar)' banner in green"
    why_human: "Requires live evcc instance with connected EV and real battery state"
  - test: "Verify arbitrage deactivates when cheaper grid window approaches"
    expected: "Logs show 'Lookahead-Guard blockiert Entladung' and banner disappears"
    why_human: "Requires real tariff data with price variation over 6h window"
  - test: "Drain battery to floor SoC and confirm discharge stops"
    expected: "Battery-to-EV stops at max(floor_soc, dynamic_buffer) without breaching"
    why_human: "Requires physical battery reaching floor level during EV charge"
---

# Phase 12: LP-Gated Battery Arbitrage Verification Report

**Phase Goal:** The house battery co-discharges to supplement EV fast charging when the stored energy is cheaper than the current grid price, the LP plan authorizes discharge, and the battery will recover before it is needed again -- never draining the battery at the wrong moment

**Verified:** 2026-02-27T22:00:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | When EV fast-charging ("now" mode), battery energy cheaper than grid (85% RT efficiency), LP authorizes, battery co-discharges -- dashboard shows "Batterie speist EV (spare X ct/kWh)" | VERIFIED | `battery_arbitrage.py` gates 2+3+4 enforce all conditions; `app.js:102-116` renders banner with savings; test `test_activates_when_all_gates_pass` passes |
| 2 | When LP shows cheaper grid within 6h, discharge does not activate -- lookahead guard prevents premature discharge | VERIFIED | `battery_arbitrage.py:86-96` scans 24 x 15min slots for price < 80% current; test `test_blocks_when_cheaper_price_in_6h` confirms blocking |
| 3 | Discharge stops when SoC at or below max(battery_to_ev_floor_soc, dynamic_buffer_min_soc) -- reserve floor never breached | VERIFIED | `battery_arbitrage.py:64-73` computes `effective_floor = max(cfg.battery_to_ev_floor_soc, dynamic_buffer_pct)` and blocks when available < 0.5 kWh; tests `test_respects_battery_to_ev_floor_soc` and `test_respects_dynamic_buffer` confirm |
| 4 | Battery-to-EV and LP-planned grid discharge never activate simultaneously -- mutual exclusion enforced and logged | VERIFIED | `battery_arbitrage.py:56-61` checks slot0.bat_discharge_kw > 0.1 with slot0.ev_charge_kw < 0.1; logs "Mutual Exclusion"; test `test_blocks_when_lp_discharges_to_grid` confirms |
| 5 | DynamicBufferCalc and arbitrage read same buffer SoC floor -- no silent overwrites, reflected in same decision cycle | VERIFIED | `battery_arbitrage.py:65-67` reads `buffer_calc._current_buffer_pct` under `buffer_calc._lock`; same field written by `dynamic_buffer.py:173-174` under same lock; test `test_uses_dynamic_buffer_when_higher` verifies |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `evcc-smartload/rootfs/app/battery_arbitrage.py` | Core 7-gate arbitrage logic | VERIFIED | 122 lines, all 7 gates implemented, returns status dict for SSE/dashboard |
| `evcc-smartload/rootfs/app/tests/test_battery_arbitrage.py` | 13 tests covering all gates and edge cases | VERIFIED | 377 lines, 13 test methods across 5 test classes (Activation, Lookahead, Floor, MutualExclusion, BufferSync, EdgeCases) |
| `evcc-smartload/rootfs/app/main.py` | Import + call run_battery_arbitrage, old _run_bat_to_ev removed | VERIFIED | Line 50: import; Lines 580-584: call with all args including buffer_calc; Line 645: passes arbitrage_status to store.update(); Line 847: comment confirms old function moved |
| `evcc-smartload/rootfs/app/state_store.py` | arbitrage_status field in store, snapshot, and SSE payload | VERIFIED | Line 67: `_arbitrage_status` field; Line 120: set in `update()`; Line 181: included in snapshot; Line 318: serialized as `"arbitrage"` in SSE JSON |
| `evcc-smartload/rootfs/app/web/static/app.js` | `updateArbitrageBanner` function + SSE handler | VERIFIED | Lines 102-116: renders banner with savings text; Line 163: initial load path; Lines 1714-1715: SSE handler |
| `evcc-smartload/rootfs/app/web/templates/dashboard.html` | Arbitrage banner CSS + HTML element | VERIFIED | Line 225: `.arbitrage-banner` CSS (green theme); Line 300: `<div id="arbitrageBanner">` |
| `evcc-smartload/rootfs/app/controller.py` | `apply_battery_to_ev` method (pre-existing, called by arbitrage) | VERIFIED | Lines 118-166: full implementation with dynamic discharge limits, evcc API calls, state tracking |
| `evcc-smartload/rootfs/app/dynamic_buffer.py` | `DynamicBufferCalc` with `_current_buffer_pct` and `_lock` | VERIFIED | Line 104: `_lock = threading.Lock()`; Line 112: `_current_buffer_pct`; Lines 173-174: updated under lock |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `main.py` | `battery_arbitrage.py` | `from battery_arbitrage import run_battery_arbitrage` (line 50) | WIRED | Called at line 580 with all required args |
| `battery_arbitrage.py` | `controller.py` | `controller.apply_battery_to_ev()` calls | WIRED | Called on every gate pass/fail path (lines 30, 39, 45, 51, 59, 72, 82, 92, 104-112) |
| `battery_arbitrage.py` | `dynamic_buffer.py` | `buffer_calc._current_buffer_pct` under `buffer_calc._lock` (lines 65-67) | WIRED | Reads the same field and lock that DynamicBufferCalc writes |
| `main.py` | `state_store.py` | `arbitrage_status=_arb_status` in `store.update()` (line 645) | WIRED | Result dict from arbitrage flows to SSE broadcast |
| `state_store.py` | `app.js` | SSE JSON `"arbitrage"` key (state_store.py:318) -> `msg.arbitrage` (app.js:1714) | WIRED | SSE handler calls `updateArbitrageBanner(msg.arbitrage)` |
| `app.js` | `dashboard.html` | `$('arbitrageBanner')` (app.js:103) -> `id="arbitrageBanner"` (dashboard.html:300) | WIRED | Banner element exists with matching CSS class |
| `controller.py` | `evcc_client.py` | `self.evcc.set_battery_discharge_control(True)` (controller.py:151) | WIRED | evcc_client.py:176 implements the API call to evcc |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| ARB-01 | Phase 12 | LP-authorized profitable discharge (gates 2+4) | SATISFIED | Gates 2 (LP authorization, line 49) and 4 (profitability with RT efficiency, lines 76-83) both implemented and tested |
| ARB-02 | Phase 12 | 6h lookahead guard (gate 5) | SATISFIED | Gate 5 (lines 86-96) scans 24 slots x 15min, blocks when future < 80% current price; tested |
| ARB-03 | Phase 12 | Buffer floor enforcement (gate 6) | SATISFIED | Gate 6 (lines 64-73) uses `max(floor_soc, dynamic_buffer)`, blocks when available < 0.5 kWh; tested |
| ARB-04 | Phase 12 | Mutual exclusion + buffer sync | SATISFIED | Gate 7 (lines 56-61) enforces mutual exclusion with logging; buffer sync via shared `_current_buffer_pct` under lock (lines 65-67); both tested |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | - | - | No TODO/FIXME/placeholder/stub patterns found in any Phase 12 artifact |

### Notes

**Minor observation (not a blocker):** The `/status` API endpoint (`_api_status()` in server.py) does not include arbitrage data in its response. On initial page load, `refresh()` in app.js checks `status.arbitrage` (line 163) but this field will be `undefined` from the `/status` response. The arbitrage banner only appears after the first SSE update (typically within one decision cycle, ~60 seconds). This is consistent with the Phase 11 mode control pattern and is acceptable behavior.

**Planning artifacts:** The phase directory contains only `.gitkeep` -- no PLAN.md or SUMMARY.md files were created. The ROADMAP.md claims "2/2 plans complete" but these plan files do not exist on disk. This is a documentation gap but does not affect the implementation verification.

### Human Verification Required

### 1. Live Battery-to-EV Discharge Activation

**Test:** Connect EV to wallbox, ensure mode is "now" (fast charging), battery SoC well above floor, current grid price higher than battery cost by >3 ct/kWh
**Expected:** Dashboard shows green "Batterie speist EV (spare X ct/kWh, Y kWh verfuegbar)" banner; logs show activation message
**Why human:** Requires physical EV connected to wallbox with real evcc instance and battery state

### 2. Lookahead Guard Blocks Discharge

**Test:** While battery-to-EV would otherwise activate, ensure LP plan shows significantly cheaper grid prices within next 6 hours
**Expected:** Logs show "Lookahead-Guard blockiert Entladung -- guenstigere Preise um HH:MM"; banner does not appear
**Why human:** Requires real tariff data with meaningful price variation

### 3. Floor SoC Protection

**Test:** Allow battery-to-EV to run while battery SoC approaches the floor (max of configured floor and dynamic buffer)
**Expected:** Discharge stops at floor level; banner disappears; logs confirm deactivation
**Why human:** Requires physical battery draining to near-floor during EV charging

---

_Verified: 2026-02-27T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
