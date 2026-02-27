---
phase: 11-evcc-mode-control-override-detection
verified: 2026-02-27T19:16:00Z
status: passed
score: 5/5 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 2/5
  gaps_closed:
    - "When an EV connects and current price is below threshold, SmartLoad sets evcc mode to 'now' within the next decision cycle"
    - "After SmartLoad sets a mode, a user manually changes it in evcc UI -- SmartLoad does not overwrite the manual change"
    - "After the override session ends, SmartLoad resumes mode control and the LP plan accounts for charge during override"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Override banner visual appearance -- trigger override and check dashboard"
    expected: "Yellow/orange banner visible in Status tab and Fahrzeuge tab showing manual mode name and time"
    why_human: "CSS styling and visual layout cannot be verified programmatically"
  - test: "SSE live banner toggle -- trigger override, observe banner appearing without page reload; end override, observe banner disappearing"
    expected: "Banner appears/disappears within 1 SSE cycle (typically 15 seconds)"
    why_human: "Real-time SSE behavior requires a running system"
  - test: "evcc unreachable banner -- make evcc unreachable for >30 minutes, check dashboard"
    expected: "Red banner shows 'evcc nicht erreichbar (seit HH:MM)'"
    why_human: "Requires live system with controllable network conditions"
---

# Phase 11: evcc Mode Control + Override Detection -- Verification Report

**Phase Goal:** SmartLoad actively controls the evcc charge mode (pv / minpv / now) according to the LP plan, and manual user changes in the evcc UI are detected and respected until the charging session ends -- without SmartLoad fighting the user

**Verified:** 2026-02-27T19:16:00Z
**Status:** passed
**Re-verification:** Yes -- after gap closure (previous: gaps_found, 2/5)

## Gap Closure Summary

The previous verification identified a single root cause blocking truths 1-3: `main.py` line 549 passed `collector._state` (a `SystemState` dataclass) to `EvccModeController.step()`, but the controller expected a raw evcc API dict. The fix applied:

1. **`vehicle_monitor.py`** (line 200): `DataCollector` now stores `self._evcc_raw: Optional[dict] = None`
2. **`vehicle_monitor.py`** (line 307): `_collect_once()` assigns `self._evcc_raw = evcc_state` (the raw dict from `evcc.get_state()`) under the lock, alongside `self._state = state`
3. **`main.py`** (line 549): Changed from `collector._state` to `collector._evcc_raw`, so the mode controller now receives the correct raw dict type

The data flow is now: `evcc.get_state()` -> raw dict -> `DataCollector._evcc_raw` -> `main.py` reads `collector._evcc_raw` -> `mode_controller.step(evcc_state=_evcc_raw)` -> `evcc_state.get("loadpoints", [])` works correctly.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | When an EV connects and current price is below threshold, SmartLoad sets evcc mode to "now" within the next decision cycle | VERIFIED | `evcc_mode_controller.py` lines 78-100: `decide_mode()` maps price percentiles to mode (price <= P30 -> "now", <= P60 -> "minpv", else "pv"). `step()` (line 202-203) calls `decide_mode()` then `_apply_mode()` which calls `evcc.set_loadpoint_mode(0, target_mode)` (line 227). `main.py` line 549 now correctly passes `collector._evcc_raw` (raw dict) as `evcc_state`. Line 138 `evcc_state.get("loadpoints", [])` works on a dict. 9 unit tests verify mode selection logic; all pass. Log output at line 230: "mode {current} -> {target}". |
| 2 | After SmartLoad sets a mode, user manually changes it in evcc UI -- SmartLoad does not overwrite | VERIFIED | `_check_override()` (lines 211-220): compares `current_evcc_mode` with `_last_set_mode`; returns True if they differ. `step()` line 193-199: sets `_override_active = True` and logs "Override erkannt -- SmartLoad pausiert EV-Modus-Steuerung (manuell: {mode})". Lines 189-190: when override active, returns early without calling `decide_mode()` or `_apply_mode()`. 3 override detection tests pass. Data path fix ensures this code is now reached in production. |
| 3 | After override session ends, SmartLoad resumes mode control and LP plan accounts for charge during override | VERIFIED | `step()` lines 166-187: override lifecycle check -- ends override on EV disconnect (`not state.ev_connected or not lp_connected`) or target SoC reached (`state.ev_soc >= cfg.ev_target_soc`). Logs "Override beendet ({reason}), SmartLoad ubernimmt". Resets `_override_active = False`, `_last_set_mode = None`. Next cycle enters normal mode selection path (lines 201-205). LP implicitly accounts for charge during override because it replans every cycle with current SoC from `state.ev_soc`. 5 lifecycle tests pass. |
| 4 | On startup, SmartLoad reads current evcc mode and adopts it as baseline -- no mode command sent on first cycle | VERIFIED | `step()` lines 159-163: `if not self._startup_complete` -> sets `_last_set_mode = current_evcc_mode`, sets `_startup_complete = True`, logs "Startup: evcc mode adopted as baseline: {mode}", returns early (no mode command sent). Unit test `test_startup_adopts_current_mode` verifies: `set_loadpoint_mode.assert_not_called()`. |
| 5 | Dashboard Status tab shows override banner when active, banner disappears when override ends | VERIFIED | `dashboard.html` lines 283-289: `#overrideBanner` in Status tab. Lines 452-458: `#overrideBannerFahrzeuge` in Fahrzeuge tab. CSS at lines 218-222. `app.js` lines 54-97: `updateModeControlBanner(mc)` toggles `display` based on `mc.override_active`. SSE handler at line 1689-1690 checks `msg.mode_control` and calls `updateModeControlBanner()`. Refresh cycle at line 131 fetches `/mode-control`. Server endpoint at lines 240-243 returns `mode_controller.get_status()`. StateStore serializes `mode_control_status` at line 308. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `evcc-smartload/rootfs/app/evcc_mode_controller.py` | Core controller class | VERIFIED | 255 lines. Complete: `decide_mode()`, `step()`, `_check_override()`, `_apply_mode()`, `get_status()`. All code paths substantive. |
| `evcc-smartload/rootfs/app/tests/test_evcc_mode_controller.py` | Test suite | VERIFIED | 397 lines, 29 tests across 7 classes. All 29 pass. Covers mode selection, apply mode, override detection, override lifecycle, startup, status reporting, evcc unreachable. |
| `evcc-smartload/rootfs/app/evcc_client.py` | get_loadpoint_mode, get_loadpoint_connected, set_loadpoint_mode | VERIFIED | Lines 46-64: get methods. Lines 189-199: set_loadpoint_mode sends POST to evcc API. |
| `evcc-smartload/rootfs/app/main.py` | EvccModeController integration | VERIFIED | Import (line 49), init (line 237), web injection (line 279), step call (line 564) with correct `evcc_state=collector._evcc_raw` (line 549/567), store.update with `mode_control_status=_mode_status` (line 639). |
| `evcc-smartload/rootfs/app/vehicle_monitor.py` | DataCollector stores raw evcc dict | VERIFIED | `_evcc_raw` field (line 200), assigned in `_collect_once()` under lock (line 307). |
| `evcc-smartload/rootfs/app/state_store.py` | mode_control_status in snapshot | VERIFIED | Field (line 64), update parameter (line 89), snapshot (line 173), JSON serialization (line 308). |
| `evcc-smartload/rootfs/app/web/server.py` | /mode-control endpoint | VERIFIED | Lines 240-243: GET /mode-control returns `mode_controller.get_status()`. |
| `evcc-smartload/rootfs/app/web/templates/dashboard.html` | Override + unreachable banners | VERIFIED | Override banners in Status tab (line 283) and Fahrzeuge tab (line 452). Unreachable banner (line 292). CSS styles (lines 218-222). |
| `evcc-smartload/rootfs/app/web/static/app.js` | SSE handler + banner update | VERIFIED | `evccModeName()` (line 42), `updateModeControlBanner()` (line 54), SSE handler (line 1689), refresh cycle (line 131). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| main.py | EvccModeController | import + init + step() | WIRED | Import (line 49), init (line 237), step call (line 564) with correct `evcc_state=collector._evcc_raw` (raw dict, not SystemState). |
| DataCollector._evcc_raw | mode_controller.step(evcc_state=) | collector._evcc_raw | WIRED | `vehicle_monitor.py` line 307: `self._evcc_raw = evcc_state` stores raw dict. `main.py` line 549: reads `collector._evcc_raw`. Line 567: passes to `evcc_state=_evcc_raw`. Line 138: `evcc_state.get("loadpoints", [])` operates on a dict. |
| EvccModeController | EvccClient | set_loadpoint_mode() | WIRED | `_apply_mode()` line 227 calls `self.evcc.set_loadpoint_mode(0, target_mode)`. |
| StateStore | SSE broadcast | mode_control_status | WIRED | `update()` line 114 stores `mode_control_status`. `_snapshot_to_json_dict()` line 308 includes it as `mode_control` key. SSE broadcasts to all clients. |
| Dashboard | SSE | updateModeControlBanner | WIRED | SSE onmessage handler checks `msg.mode_control` (line 1689) and calls `updateModeControlBanner(msg.mode_control)`. |
| Boost Charge | Mode Controller | precedence check | WIRED | main.py line 562: `if not _override_active:` skips mode controller when Boost is active. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| MODE-01 | 11-01, 11-02 | Price-based mode selection (now/minpv/pv) | SATISFIED | `decide_mode()` maps price percentiles to modes. 9 tests pass. Now reachable in production via fixed data path. |
| MODE-02 | 11-01, 11-02 | LP plan drives mode (current_ev_charge flag) | SATISFIED | `decide_mode()` checks `plan.current_ev_charge` (line 75). Returns "pv" when LP says don't charge. |
| MODE-03 | 11-01, 11-02 | Override detection (evcc mode differs from last set) | SATISFIED | `_check_override()` compares current vs last set mode. 3 tests pass. |
| MODE-04 | 11-01, 11-02 | Override lifecycle (EV disconnect or target SoC) | SATISFIED | `step()` lifecycle check (lines 166-190). 5 tests pass. |
| MODE-05 | 11-02 | Dashboard banners (override active + evcc unreachable) | SATISFIED | HTML banners, CSS, JS update function, SSE integration, /mode-control endpoint all verified. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | - | - | Previous blocker (wrong type at main.py:549) is fixed. No new anti-patterns found. |

### Human Verification Required

### 1. Override Banner Visual Appearance

**Test:** Manually set override_active=True in mode controller and check dashboard
**Expected:** Yellow/orange banner visible in both Status tab and Fahrzeuge tab with mode name
**Why human:** CSS styling and visual layout cannot be verified programmatically

### 2. SSE Live Banner Toggle

**Test:** Trigger an override, observe banner appearing without page reload; end override, observe banner disappearing
**Expected:** Banner appears/disappears within 1 SSE cycle (typically 15 seconds)
**Why human:** Real-time SSE behavior requires a running system

### 3. evcc Unreachable Banner

**Test:** Make evcc unreachable for >30 minutes, check dashboard
**Expected:** Red banner shows "evcc nicht erreichbar (seit HH:MM)"
**Why human:** Requires live system with controllable network conditions

---

_Verified: 2026-02-27T19:16:00Z_
_Verifier: Claude (gsd-verifier)_
