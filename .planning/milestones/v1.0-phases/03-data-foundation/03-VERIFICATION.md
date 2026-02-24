---
phase: 03-data-foundation
verified: 2026-02-22T19:00:00Z
status: human_needed
score: 14/14 must-haves verified
re_verification: false
human_verification:
  - test: "Open dashboard at http://[host]:8099 and inspect the 24h forecast chart section"
    expected: "Chart renders below status cards showing blue consumption line (#00d4ff) and yellow PV line (#ffdd00) with price zone background colors (green=cheap, red=expensive). Legend shows 'Verbrauch' and 'PV-Ertrag'. Metadata below chart shows forecaster maturity, PV quality label, and correction label."
    why_human: "SVG rendering correctness, color accuracy, and visual layout cannot be verified programmatically."
  - test: "Wait for SSE update or trigger a decision cycle, observe chart"
    expected: "Chart refreshes without page reload as new forecast data arrives via SSE."
    why_human: "Live SSE-driven chart updates require browser observation."
  - test: "Visit http://[host]:8099/forecast"
    expected: "JSON response with consumption_96 (96-element array or null if cold start), pv_96 (96-element array), pv_confidence, pv_correction_label, pv_quality_label, forecaster_ready, forecaster_data_days, ha_warnings, price_zones_96."
    why_human: "Requires live container running with evcc and InfluxDB connections."
  - test: "Inspect container logs after startup"
    expected: "On fresh install: 'Verbrauchsprognose nicht bereit (0/1 Tage Daten), verwende Standardwerte'. 'PV forecast: Xh coverage, correction=1.00' after hourly refresh. If ha_url configured: HA entity discovery log lines."
    why_human: "Runtime log output requires live container."
---

# Phase 03: Data Foundation Verification Report

**Phase Goal:** The planner has accurate house consumption forecasts and PV generation estimates to plan against, sourced from real historical data
**Verified:** 2026-02-22T19:00:00Z
**Status:** human_needed — all automated checks passed; 4 items require live container observation
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

All truths derive from the three PLAN frontmatter `must_haves` blocks (03-01, 03-02, 03-03).

#### Plan 01 Must-Haves (PLAN-04)

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | ConsumptionForecaster returns 96-slot list of estimated Watt values for the next 24h | VERIFIED | `get_forecast_24h()` returns `range(SLOTS_PER_DAY)` list starting from current slot, each value = avg * correction_factor or DEFAULT_WATTS (consumption.py:91-112) |
| 2  | InfluxDB home_power history is queried at 15-min resolution for the last 7 days | VERIFIED | `query_home_power_15min(days=7)` exists in influxdb_client.py:105; called in `_bootstrap_from_influxdb()` at consumption.py:263 |
| 3  | Forecaster model persists to /data/smartprice_consumption_model.json and survives restarts | VERIFIED | `MODEL_PATH = "/data/smartprice_consumption_model.json"`, atomic write via `os.rename(tmp_path, MODEL_PATH)` at consumption.py:344 |
| 4  | On schema version mismatch, model is cleared and rebuilt from InfluxDB source data | VERIFIED | `_load_or_init()` checks `model.get("version") != MODEL_VERSION`, calls `_bootstrap_from_influxdb()` on mismatch (consumption.py:212-218) |
| 5  | HA energy entity discovery warns about unconfigured energy entities via log and returns entity list | VERIFIED | `run_entity_discovery()` in ha_energy.py:42 logs German warning "HA Energy Dashboard: N Energie-Entities nicht konfiguriert: {entity_ids}" and returns `{"configured": [...], "unconfigured": [...], "warnings": [...]}` |
| 6  | Cold start with no data returns is_ready=False and get_forecast_24h returns DEFAULT_WATTS for all slots | VERIFIED | `is_ready` property returns `self._data_days >= 1` (False at cold start); `get_forecast_24h()` returns `float(DEFAULT_WATTS)` (1200) for slots with count=0 (consumption.py:107-111) |
| 7  | Immediate self-correction: when actual load deviates from forecast, correction_factor adjusts current-hour weighting | VERIFIED | `apply_correction()` sets `self._correction_factor = max(0.5, min(1.5, actual_watts / forecast_watts))` (consumption.py:153-171); called in main.py:241 every cycle when forecast[0] > 100W |

#### Plan 02 Must-Haves (PLAN-05)

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 8  | PVForecaster returns 96-slot list of kW values for the next 24h derived from evcc solar tariff API | VERIFIED | `get_forecast_24h()` returns 96-element list via evcc slot lookup with correction applied (pv.py:128-170); `refresh()` calls `self._evcc.get_tariff_solar()` (pv.py:98) |
| 9  | Partial forecasts (<24h data) reduce confidence proportionally (12h = 0.5) | VERIFIED | `confidence` property = `min(1.0, self._coverage_hours / 24.0)` (pv.py:222); 12h = 0.5 exactly |
| 10 | Total API failure results in 0 kWh generation assumption (conservative and safe) | VERIFIED | `if not rates:` branch sets `_coverage_hours=0`, `_slots=[]`; `get_forecast_24h()` returns `[0.0] * SLOTS_PER_DAY` when slots is empty (pv.py:100-105, 143) |
| 11 | Correction coefficient tracks actual vs forecast PV and persists across restarts | VERIFIED | `_correction` persisted to `/data/smartprice_pv_model.json` via atomic write (pv.py:403-425); `_load()` restores it on startup (pv.py:373-401) |
| 12 | Correction coefficient only updates during daytime (forecast > 50 W threshold) | VERIFIED | `if forecast_w <= DAYTIME_THRESHOLD_W: return` guard in `update_correction()` (pv.py:194); DAYTIME_THRESHOLD_W = 50 (pv.py:37) |
| 13 | Human-readable correction label available (e.g., 'Korrektur: +13%') | VERIFIED | `correction_label` property returns `f"Korrektur: {sign}{pct:.0f}%"` (pv.py:225-233) |
| 14 | Human-readable forecast quality label available (e.g., 'Basierend auf 18h Forecast-Daten') | VERIFIED | `quality_label` property returns `f"Basierend auf {hours}h Forecast-Daten"` or `"Kein PV-Forecast verfuegbar"` (pv.py:235-245) |

#### Plan 03 Must-Haves (PLAN-04 + PLAN-05 integration)

All 9 Plan 03 truths are covered by the artifact and key link verification below (see those sections).

**Score:** 14/14 must-have truths verified (automated)

---

### Required Artifacts

| Artifact | Min Lines | Actual Lines | Status | Key Evidence |
|----------|-----------|-------------|--------|--------------|
| `evcc-smartload/rootfs/app/forecaster/__init__.py` | — | 10 | VERIFIED | Exports `ConsumptionForecaster` and `PVForecaster` via `__all__` |
| `evcc-smartload/rootfs/app/forecaster/consumption.py` | 150 | 368 | VERIFIED | Contains `ConsumptionForecaster`, `MODEL_VERSION=1`, `os.rename`, `is_ready`, `apply_correction`, `get_forecast_24h` |
| `evcc-smartload/rootfs/app/forecaster/ha_energy.py` | 60 | 342 | VERIFIED | Contains `run_entity_discovery`, `energy/get_prefs`, `nicht konfiguriert`, `threading.Thread(daemon=True)` |
| `evcc-smartload/rootfs/app/forecaster/pv.py` | 120 | 425 | VERIFIED | Contains `PVForecaster`, `get_tariff_solar` call, `DAYTIME_THRESHOLD_W`, `confidence`, `correction_label`, `quality_label`, `os.rename`, `PV_MODEL_VERSION=1` |
| `evcc-smartload/rootfs/app/influxdb_client.py` | — | — | VERIFIED | `query_home_power_15min()` at line 105, `query_home_power_hourly()` at line 144 |
| `evcc-smartload/rootfs/app/config.py` | — | — | VERIFIED | `ha_url: str = ""`, `ha_token: str = ""` at lines 109-110; SUPERVISOR_TOKEN auto-detect at lines 201-208 |
| `evcc-smartload/rootfs/app/main.py` | — | — | VERIFIED | Imports `ConsumptionForecaster`, `PVForecaster`, `run_entity_discovery`; initializes at lines 100-101; calls `update()`, `refresh()`, `update_correction()` in decision loop |
| `evcc-smartload/rootfs/app/state_store.py` | — | — | VERIFIED | `consumption_forecast` field at line 48; `pv_forecast`, `pv_confidence`, `pv_correction_label`, `pv_quality_label`, `forecaster_ready`, `forecaster_data_days`, `ha_warnings` fields; "forecast" section in SSE JSON at line 225 |
| `evcc-smartload/rootfs/app/web/server.py` | — | — | VERIFIED | `/forecast` endpoint at line 199; `_compute_price_zones()` helper at line 568 |
| `evcc-smartload/rootfs/app/web/static/app.js` | — | — | VERIFIED | `renderForecastChart()` at line 913; `#00d4ff` and `#ffdd00` colors; `updateForecastMeta()` at 1046; `updateHaWarnings()` at 1075; `fetchJSON('/forecast')` at line 1256; `msg.forecast` SSE handling at line 1189 |
| `evcc-smartload/rootfs/app/web/templates/dashboard.html` | — | — | VERIFIED | `id="forecastChart"` at line 249; `id="forecasterMaturity"` at 245; `id="pvCorrectionLabel"` at 247; `id="pvQualityLabel"` at 246; `id="haWarningBanner"` at 194 |

---

### Key Link Verification

| From | To | Via | Status | Evidence |
|------|----|-----|--------|----------|
| `forecaster/consumption.py` | `influxdb_client.py` | `query_home_power_15min()` and `query_home_power_hourly()` in `_bootstrap_from_influxdb()` | WIRED | consumption.py:263 `self._influx.query_home_power_15min(days=7)`, line 287 `self._influx.query_home_power_hourly(days_start=8, days_end=30)` |
| `forecaster/ha_energy.py` | HA WebSocket API | `aiohttp ws_connect` for `energy/get_prefs` | WIRED | ha_energy.py:169 `session.ws_connect(ws_url)`, line 189 `ws.send_json({"id": 1, "type": "energy/get_prefs"})` |
| `forecaster/consumption.py` | `/data/smartprice_consumption_model.json` | JSON atomic write (write to .tmp then os.rename) | WIRED | consumption.py:341-344 `tmp_path = MODEL_PATH + ".tmp"`, `os.rename(tmp_path, MODEL_PATH)` |
| `forecaster/pv.py` | `evcc_client.py` | `evcc_client.get_tariff_solar()` in hourly refresh | WIRED | pv.py:98 `rates = self._evcc.get_tariff_solar()` |
| `forecaster/pv.py` | `/data/smartprice_pv_model.json` | JSON atomic write for correction coefficient persistence | WIRED | pv.py:419-423 `tmp_path = PV_MODEL_PATH + ".tmp"`, `os.rename(tmp_path, PV_MODEL_PATH)` |
| `main.py` | `forecaster/consumption.py` | `consumption_forecaster.update()` and `get_forecast_24h()` in decision loop | WIRED | main.py:237 `consumption_forecaster.update(state.home_power, ...)`, line 239 `consumption_forecaster.get_forecast_24h()` |
| `main.py` | `forecaster/pv.py` | `pv_forecaster.refresh()` hourly, `update_correction()` every cycle | WIRED | main.py:247 `pv_forecaster.refresh()`, line 253 `pv_forecaster.update_correction(pv_kw, ...)` |
| `state_store.py` | `web/server.py` | `snapshot()` includes forecast fields read by `/forecast` endpoint | WIRED | state_store.py:225-234 "forecast" section in `_snapshot_to_json_dict()`; server.py:202-208 reads `snap.get("consumption_forecast")` etc. |
| `web/static/app.js` | `web/server.py` | `fetch('/forecast')` and SSE `msg.forecast` updates | WIRED | app.js:1256 `fetchJSON('/forecast').then(...)`, line 1189 `if (msg.forecast) { renderForecastChart(msg.forecast); }` |
| `web/static/app.js` | `web/templates/dashboard.html` | SVG rendering into `#forecastChart` container | WIRED | app.js:914 `var container = $('forecastChart')`, dashboard.html:249 `id="forecastChart"` |

---

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|----------|
| PLAN-04 | 03-01-PLAN.md, 03-03-PLAN.md | Hausverbrauch wird aus HA-Datenbank/InfluxDB-Historie hochgerechnet und in Planung berücksichtigt | SATISFIED | ConsumptionForecaster bootstraps from InfluxDB with `query_home_power_15min` and `query_home_power_hourly`; wired into main loop every 15-min cycle; StateStore carries `consumption_forecast` and `forecaster_ready` to web layer |
| PLAN-05 | 03-02-PLAN.md, 03-03-PLAN.md | PV-Ertragsprognose wird via evcc Solar-Tariff API bezogen und in den 24-48h Plan integriert | SATISFIED | PVForecaster calls `evcc.get_tariff_solar()` hourly; 96-slot output with correction coefficient; confidence and labels available; wired into StateStore via `pv_forecast`, `pv_confidence`; exposed via `/forecast` endpoint and SSE broadcast |

No orphaned requirements detected. REQUIREMENTS.md traceability table marks PLAN-04 and PLAN-05 as "Phase 3 — Complete" (lines 86-87).

---

### Anti-Patterns Found

No anti-patterns detected across any of the 10 modified/created files. Specifically:
- No TODO/FIXME/PLACEHOLDER comments in forecaster modules or integration files
- No empty implementations (`return {}`, `return []` without logic)
- No stub handlers (all public methods have substantive implementation)
- The battery_phases_96 chart layer is intentionally stubbed with a `null` check (returns nothing when data absent) — this is documented as a Phase 4 hook, not a blocker

---

### Human Verification Required

The automated checks confirm all code is present, wired, and substantive. The following require a live container for final confirmation:

#### 1. Dashboard Forecast Chart Visual Correctness

**Test:** Open the dashboard at `http://[host]:8099` and scroll to the "24h Prognose" card.
**Expected:** Chart renders with a blue (#00d4ff) consumption forecast line and a yellow (#ffdd00) PV forecast line overlaid on a 960x250 SVG. Price zone rectangles show green tint for cheap hours, red tint for expensive hours. Legend below chart shows "Verbrauch" (blue square) and "PV-Ertrag" (yellow square). Three metadata lines appear below chart: forecaster maturity, PV quality label, PV correction label.
**Why human:** SVG rendering, color accuracy, and layout quality cannot be verified programmatically.

#### 2. SSE Live Chart Updates

**Test:** Keep the dashboard open and wait for the next decision cycle (up to 15 min), or trigger one manually.
**Expected:** The forecast chart updates in place without a page reload as the SSE pushes a new payload containing `msg.forecast`.
**Why human:** Real-time SSE behavior requires browser observation.

#### 3. /forecast Endpoint JSON Integrity

**Test:** Visit `http://[host]:8099/forecast` in a browser or curl.
**Expected:** JSON object with keys: `consumption_96` (96 floats or null on cold start), `pv_96` (96 floats, all 0.0 if no solar data), `pv_confidence` (0.0-1.0), `pv_correction_label` (e.g., "Korrektur: 0%"), `pv_quality_label`, `forecaster_ready` (bool), `forecaster_data_days` (int), `ha_warnings` (list), `price_zones_96` (96 strings).
**Why human:** Requires live container with active evcc and InfluxDB connections.

#### 4. Runtime Log Verification

**Test:** Inspect container logs immediately after startup.
**Expected:** If fresh install (no model file): "ConsumptionForecaster: no model file found, bootstrapping from InfluxDB" followed by "bootstrap complete". "PV forecast: Xh coverage, correction=1.00" logged after initial `pv_forecaster.refresh()`. If `consumption_forecaster.is_ready` is False: "Verbrauchsprognose nicht bereit (0/1 Tage Daten), verwende Standardwerte" on first decision cycle. If ha_url configured: HA entity discovery log output.
**Why human:** Runtime log output requires a live running container.

---

### Commits Verified

All commits documented in SUMMARY files confirmed present in git history:

| Commit | Description | Status |
|--------|-------------|--------|
| `3108c12` | feat(03-01): ConsumptionForecaster with tiered aggregation and persistent model | EXISTS |
| `d118975` | feat(03-01): HA energy entity discovery with WebSocket and REST fallback | EXISTS |
| `93eae1c` | feat(03-03): wire forecasters into main loop and extend StateStore | EXISTS |
| `1feaeb5` | feat(03-03): dashboard forecast chart, /forecast API endpoint, SSE integration | EXISTS |

---

### Summary

Phase 03 goal is achieved at the code level. All 14 automated must-have truths pass. The full pipeline is wired end-to-end:

- **InfluxDB -> ConsumptionForecaster**: `query_home_power_15min` and `query_home_power_hourly` called in bootstrap; EMA updates every 15-min cycle from `state.home_power`
- **evcc API -> PVForecaster**: `get_tariff_solar()` called hourly; Watt-to-kW unit detection; daytime-only correction coefficient
- **Both forecasters -> StateStore**: 8 new forecast fields in `update()` and `snapshot()`; "forecast" section in SSE JSON payload
- **StateStore -> /forecast API**: Full JSON response with all 96-slot arrays and metadata
- **/forecast + SSE -> Dashboard**: `renderForecastChart()` renders SVG on initial load and on every SSE update; `updateForecastMeta()` and `updateHaWarnings()` maintain dashboard state

The planner (Phase 4) will find `forecaster_ready`, `consumption_96`, and `pv_96` available in StateStore with no further wiring required.

---

_Verified: 2026-02-22T19:00:00Z_
_Verifier: Claude (gsd-verifier)_
