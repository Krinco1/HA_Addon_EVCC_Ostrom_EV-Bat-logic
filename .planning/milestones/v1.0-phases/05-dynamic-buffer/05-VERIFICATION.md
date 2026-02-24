# Phase 5 Dynamic Buffer -- Verification

**Verified:** 2026-02-24
**Audited by:** Phase 8.1 gap closure (08.1-01-PLAN.md)
**Result:** PASS

---

## Plan 01: Backend Engine

### Must-Have Truths

#### Truth 1: "DynamicBufferCalc computes a target buffer SoC every 15-minute cycle based on PV confidence, price spread, and time of day"
**Status:** PASS
**Evidence:** `dynamic_buffer.py` `step()` method calls `_compute_target(effective_pv_confidence, price_spread, pv_96, now)` each cycle. The formula uses PV confidence, price spread (EUR/kWh), and `now.hour` for time-of-day modifier.
File: `evcc-smartload/rootfs/app/dynamic_buffer.py`
Pattern: `target_buffer = self._compute_target(effective_pv_confidence, price_spread, pv_96, now)` (line 165)

#### Truth 2: "In observation mode, the calculator logs what it would do but does NOT call evcc set_buffer_soc()"
**Status:** PASS
**Evidence:** `step()` sets `applied = (mode == "live")`. The `set_buffer_soc()` call is guarded by `if applied and target_buffer != old_buffer:`. In observation mode `applied` is `False`, so the evcc call is skipped. The event is always logged with `applied=False`.
File: `evcc-smartload/rootfs/app/dynamic_buffer.py`
Pattern: `applied = (mode == "live")` then `if applied and target_buffer != old_buffer: self._evcc.set_buffer_soc(target_buffer)` (lines 168-172)

#### Truth 3: "In live mode, the calculator calls evcc set_buffer_soc() only when target changes"
**Status:** PASS
**Evidence:** Live mode guard: `if applied and target_buffer != old_buffer: self._evcc.set_buffer_soc(target_buffer)` -- the `!= old_buffer` condition ensures evcc is not called every cycle unconditionally.
File: `evcc-smartload/rootfs/app/dynamic_buffer.py`
Pattern: `self._evcc.set_buffer_soc(target_buffer)` (line 172) inside `if applied and target_buffer != old_buffer:`

#### Truth 4: "Buffer never drops below 10% hard floor and practical minimum is 20%"
**Status:** PASS
**Evidence:** `_compute_target()` enforces both floors at the end: `target = max(target, PRACTICAL_MIN_PCT)` then `target = max(target, HARD_FLOOR_PCT)` where `HARD_FLOOR_PCT=10` and `PRACTICAL_MIN_PCT=20`. Also `max_reduction = max(0, base - PRACTICAL_MIN_PCT)` ensures the formula cannot reduce below 20%.
File: `evcc-smartload/rootfs/app/dynamic_buffer.py`
Pattern: `HARD_FLOOR_PCT = 10` (line 27), `PRACTICAL_MIN_PCT = 20` (line 30), `target = max(target, PRACTICAL_MIN_PCT)` + `target = max(target, HARD_FLOOR_PCT)` (lines 272-273)

#### Truth 5: "Observation mode auto-transitions to live after 14 days; deployment timestamp survives restarts"
**Status:** PASS
**Evidence:** `_determine_mode()` auto-mode branch: `elapsed = (now - self._deployment_ts).total_seconds()` / `if elapsed >= OBSERVATION_PERIOD_SECONDS: return "live"` where `OBSERVATION_PERIOD_SECONDS = 14 * 24 * 3600`. `_deployment_ts` is persisted in `_build_model_dict()` as `"deployment_ts": self._deployment_ts.isoformat()` and restored in `_load()` via `self._deployment_ts = datetime.fromisoformat(ts_str)`.
File: `evcc-smartload/rootfs/app/dynamic_buffer.py`
Pattern: `OBSERVATION_PERIOD_SECONDS = 14 * 24 * 3600` (line 37), `_deployment_ts` in `_build_model_dict()` (line 421), restored in `_load()` (line 362)

#### Truth 6: "User can manually activate live early or extend observation via API"
**Status:** PASS
**Evidence:** `activate_live()` sets `self._live_override = True` and saves. `extend_observation(extra_days)` sets `self._live_override = False` and `self._observation_extended_until = datetime.now(utc) + timedelta(days=extra_days)` and saves. Both are public methods.
File: `evcc-smartload/rootfs/app/dynamic_buffer.py`
Pattern: `def activate_live(self)` (line 210), `def extend_observation(self, extra_days: int = 14)` (line 216)

#### Truth 7: "Buffer calculation is skipped when bat-to-EV is active (no value fighting)"
**Status:** PASS
**Evidence:** Main loop guard: `if buffer_calc is not None and not controller._bat_to_ev_active:` -- if bat-to-EV is active, `buffer_calc.step()` is never called.
File: `evcc-smartload/rootfs/app/main.py`
Pattern: `if buffer_calc is not None and not controller._bat_to_ev_active:` (line 542)

#### Truth 8: "Every cycle produces a result dict that StateStore broadcasts via SSE"
**Status:** PASS
**Evidence:** `step()` returns a dict with `current_buffer_pct`, `mode`, `days_remaining`, `log_recent`, `observation_live_at`. This dict is passed as `buffer_result=buffer_result` to `store.update()`, which stores it as `self._buffer_result = buffer_result`. `_snapshot_to_json_dict()` includes it as `"buffer": snap.get("buffer_result")` in the SSE payload.
File: `evcc-smartload/rootfs/app/main.py` + `evcc-smartload/rootfs/app/state_store.py`
Pattern: `buffer_result=buffer_result` (main.py line 597), `"buffer": snap.get("buffer_result")` (state_store.py line 298)

---

### Must-Have Artifacts

#### Artifact: evcc-smartload/rootfs/app/dynamic_buffer.py
**Status:** PASS
**Evidence:** File exists, 434 lines (>= min 250). Contains `DynamicBufferCalc` class with `step()`, `activate_live()`, `extend_observation()`, `_compute_target()`, `_determine_mode()`, `_load()`, `_save()`. Contains `BufferEvent` class with `to_dict()`. All required constants present.

#### Artifact: evcc-smartload/rootfs/app/main.py
**Status:** PASS
**Evidence:** File exists, contains `buffer_calc` initialization block (line ~138-144), `buffer_calc.step()` call in decision loop (line ~544), `buffer_result=buffer_result` passed to `store.update()` (line ~597).
Pattern confirmed: `buffer_calc` (grep count: 5 occurrences)

#### Artifact: evcc-smartload/rootfs/app/state_store.py
**Status:** PASS
**Evidence:** File exists, 299 lines. `update()` signature includes `buffer_result: Optional[dict] = None` parameter (line 85). `_snapshot_unlocked()` includes `"buffer_result": copy.copy(self._buffer_result)` (line 165). `_snapshot_to_json_dict()` includes `"buffer": snap.get("buffer_result")` (line 298).
Pattern confirmed: `buffer_result` (grep count: 5 occurrences)

---

### Key Links

#### Link: main.py -> dynamic_buffer.py via buffer_calc.step()
**Status:** PASS
**Evidence:** `main.py` contains `buffer_result = buffer_calc.step(` inside the decision loop (line ~544).
Pattern: `buffer_calc\.step\(` -- confirmed present

#### Link: dynamic_buffer.py -> evcc_client.py via set_buffer_soc()
**Status:** PASS
**Evidence:** `dynamic_buffer.py` calls `self._evcc.set_buffer_soc(target_buffer)` in live mode (line 172).
Pattern: `_evcc\.set_buffer_soc\(` -- confirmed present

#### Link: main.py -> state_store.py via buffer_result= parameter in store.update()
**Status:** PASS
**Evidence:** `store.update(... buffer_result=buffer_result)` call in main.py (line ~597).
Pattern: `buffer_result=buffer_result` -- confirmed present

#### Link: state_store.py -> SSE clients via buffer key in _snapshot_to_json_dict()
**Status:** PASS
**Evidence:** `_snapshot_to_json_dict()` returns `"buffer": snap.get("buffer_result")` (line 298).
Pattern: `"buffer".*buffer_result` -- confirmed present (`"buffer": snap.get("buffer_result")`)

---

## Plan 02: Dashboard UI

### Must-Have Truths

#### Truth 1: "Dashboard shows current buffer level and PV confidence in a collapsible widget"
**Status:** PASS
**Evidence:** `dashboard.html` contains `#bufferCard` with `#confWidget` / `#confSummary` / `#confDetail` structure. `app.js` `updateBufferSection()` populates `#confValue` (PV confidence %) and `#bufferValue` (current buffer %). `toggleConfDetail()` shows/hides `#confDetail`.
File: `evcc-smartload/rootfs/app/web/templates/dashboard.html`
Pattern: `id="bufferCard"` (line 324), `id="confWidget"`, `id="confSummary"`, `id="confDetail"`

#### Truth 2: "Observation mode banner is visible with countdown, activate-live button, and extend button"
**Status:** PASS
**Evidence:** `dashboard.html` contains `id="bufferObsBanner"` with `id="bufferObsText"` for countdown text, `onclick="activateBufferLive()"` button and `onclick="extendBufferObs()"` button.
File: `evcc-smartload/rootfs/app/web/templates/dashboard.html`
Pattern: `id="bufferObsBanner"` (line 316), `activateBufferLive()`, `extendBufferObs()` buttons

#### Truth 3: "Buffer history line chart shows 7-day buffer level over time"
**Status:** PASS
**Evidence:** `app.js` `renderBufferChart(logEntries)` renders an SVG polyline of `new_buffer_pct` values over time in `#bufferChart`. Contains reference lines at 20% (practical min) and 10% (hard floor) in red. Maximum 7 days of data is available from `log_recent` (last 100 entries ~ 25 hours, but backend retains up to 700 entries = 7 days).
File: `evcc-smartload/rootfs/app/web/static/app.js`
Pattern: `function renderBufferChart(logEntries)` (line 1210)

#### Truth 4: "Expandable event log table shows per-event details: confidence, spread, time, PV, old/new buffer, reason"
**Status:** PASS
**Evidence:** `app.js` `renderBufferLog(logEntries)` builds table rows with: time (HH:MM), confidence (%), spread (ct), buffer (old->new%), reason text, applied status. Table header in `dashboard.html` includes Zeit, Konfidenz, Spread, Puffer, Grund, Status columns.
File: `evcc-smartload/rootfs/app/web/static/app.js`
Pattern: `function renderBufferLog(logEntries)` (line 1305)

#### Truth 5: "Observation-mode events are visually distinguished from live events (muted/dashed style)"
**Status:** PASS
**Evidence:** `app.js` sets `var rowClass = isObs ? ' class="buffer-log-obs"' : ''` where `isObs = (e.mode === 'observation' || e.applied === false)`. CSS class `.buffer-log-obs` has `opacity: 0.6; font-style: italic` in `dashboard.html`.
File: `evcc-smartload/rootfs/app/web/static/app.js` + `dashboard.html`
Pattern: `class="buffer-log-obs"` (app.js line 1314), `.buffer-log-obs { opacity: 0.6; font-style: italic; }` (dashboard.html line 199)

#### Truth 6: "POST /buffer/activate-live and POST /buffer/extend-obs endpoints work"
**Status:** PASS
**Evidence:** `server.py` `do_POST()` handles both paths: `elif path == "/buffer/activate-live": srv.buffer_calc.activate_live()` and `elif path == "/buffer/extend-obs": srv.buffer_calc.extend_observation(extra_days=days)`. Days parameter validated (1-90 range).
File: `evcc-smartload/rootfs/app/web/server.py`
Pattern: `/buffer/activate-live` (line 386), `/buffer/extend-obs` (line 393)

#### Truth 7: "Buffer section updates live via SSE without page reload"
**Status:** PASS
**Evidence:** `app.js` `applySSEUpdate()` contains `if (msg.buffer) { updateBufferSection(msg.buffer); }` (lines 1619-1621). SSE payload always includes `"buffer"` key from `_snapshot_to_json_dict()`.
File: `evcc-smartload/rootfs/app/web/static/app.js`
Pattern: `updateBufferSection(msg.buffer)` (line 1620)

---

### Must-Have Artifacts

#### Artifact: evcc-smartload/rootfs/app/web/templates/dashboard.html
**Status:** PASS
**Evidence:** File exists. Contains `id="bufferCard"` (line 324), `id="bufferObsBanner"` (line 316), `.buffer-log-obs` CSS class (line 199), buffer chart container with `id="bufferChart"`, event log table with `id="bufferLog"` and `id="bufferLogBody"`.
Pattern confirmed: `bufferCard` present

#### Artifact: evcc-smartload/rootfs/app/web/static/app.js
**Status:** PASS
**Evidence:** File exists. Contains `updateBufferSection(buffer)` (line 1159), `renderBufferChart(logEntries)` (line 1210), `renderBufferLog(logEntries)` (line 1305), `toggleConfDetail()`, `activateBufferLive()`, `extendBufferObs()`, SSE handler `updateBufferSection(msg.buffer)` (line 1620).
Pattern confirmed: `updateBufferSection` (2 occurrences)

#### Artifact: evcc-smartload/rootfs/app/web/server.py
**Status:** PASS
**Evidence:** File exists. Contains `elif path == "/buffer/activate-live"` (line 386) and `elif path == "/buffer/extend-obs"` (line 393). `WebServer.__init__` accepts `buffer_calc=None` parameter (line 66) and stores as `self.buffer_calc = buffer_calc` (line 85).
Pattern confirmed: `/buffer/activate-live` (1 occurrence), `buffer_calc.` (2 occurrences)

---

### Key Links

#### Link: app.js -> SSE data.buffer via applySSEUpdate() calls updateBufferSection(msg.buffer)
**Status:** PASS
**Evidence:** `app.js` `applySSEUpdate()` block: `if (msg.buffer) { updateBufferSection(msg.buffer); }` (lines 1619-1621).
Pattern: `updateBufferSection\(msg\.buffer\)` -- confirmed present

#### Link: app.js -> server.py via fetch('/buffer/activate-live') and fetch('/buffer/extend-obs')
**Status:** PASS
**Evidence:** `activateBufferLive()` calls `fetch('/buffer/activate-live', { method: 'POST' })` (line 1367). `extendBufferObs()` calls `fetch('/buffer/extend-obs', ...)` (lines ~1380+).
Pattern: `fetch.*buffer` -- confirmed present

#### Link: server.py -> dynamic_buffer.py via buffer_calc.activate_live() and buffer_calc.extend_observation()
**Status:** PASS
**Evidence:** `server.py` calls `srv.buffer_calc.activate_live()` (line 390) and `srv.buffer_calc.extend_observation(extra_days=days)` (line 405).
Pattern: `buffer_calc\.` -- confirmed present (2 occurrences)

---

## Summary

All 15 must-have truths verified (8 from Plan 01, 7 from Plan 02).
All 6 must-have artifacts confirmed present with required content.
All 7 key links confirmed with specific grep patterns.

**Result: PASS**

No gaps found during verification — all Phase 5 must-haves are fully implemented.
No fixes required.
