# Phase 3: Data Foundation - Research

**Researched:** 2026-02-22
**Domain:** Consumption forecasting (InfluxDB + HA), PV forecast (evcc API), tiered history compression, dashboard visualization
**Confidence:** HIGH (core stack), MEDIUM (HA energy entity detection), HIGH (evcc solar tariff API format)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Consumption Forecast Model:**
- InfluxDB as primary data source; HA database as optional enrichment/verification source
- When both configured: HA verifies InfluxDB data AND fills gaps — full integration with validation
- HA Energy Dashboard entities as the consumption source — read entities configured in HA's energy dashboard
- Additionally detect and warn about energy entities NOT configured in the Energy Dashboard but probably should be
- Warning display: both Dashboard banner AND detailed log entry with entity IDs
- Immediate self-correction: when actual load deviates significantly from forecast, current hour gets weighted more heavily in the rolling average
- Tiered aggregation for history: recent data at full resolution, older data increasingly compressed (hour averages → day averages → week profiles). Claude decides specific compression scheme and time horizons
- Persistent storage: aggregated model saved to /data/, survives restarts. Must be versioned — on schema upgrade, historical compressions are rebuilt from source data if available
- Forecaster updates its model every decision cycle (every 15 min)

**PV Forecast Handling:**
- Use the solar forecast API already configured in evcc, accessible via the evcc API
- Hourly refresh from evcc API
- Actual PV generation data compared against forecast to compute a correction coefficient
- PV correction coefficient: shown on dashboard as subtle info below PV graph (e.g., "Korrektur: +13%")
- On partial forecast (<24h data): reduced confidence proportional to data coverage (e.g., 12h = 50% confidence), planner becomes more conservative
- On total API failure: planner operates without PV forecast, assumes 0 kWh generation — conservative and safe
- PV forecast quality displayed subtly below graph (e.g., "Basierend auf 18h Forecast-Daten")
- PV correction coefficient stored separately from consumption model (independently updatable)

**Dashboard Forecast Visualization:**
- 24h forecast graph: consumption and PV generation as two overlaid lines in the same graph
- Battery charge/discharge phases shown as colored areas behind the lines (green=charge, orange=discharge)
- Electricity price zones as background colors on the timeline (green=cheap, red=expensive)
- Graph style: Claude decides, matching existing dashboard design (dark theme, SVG-based)
- Live graph updates via SSE when new forecast data arrives — consistent with Phase 1 SSE infrastructure

**Cold Start Behavior:**
- Absolute fresh start (no data): collect 24h of data before forecaster becomes active — planner pauses during collection phase
- After 24h: hybrid mode — available data blended with defaults, default proportion decreases as more data accumulates
- Dashboard shows forecaster maturity as progress indicator (e.g., "Verbrauchsprognose: 5/14 Tage Daten, Genauigkeit steigt noch")

**Forecast Freshness:**
- Consumption forecaster updates every decision cycle (15 min)
- PV forecast refreshed hourly from evcc API
- Actual PV output continuously compared against forecast to derive correction coefficient

### Claude's Discretion

- Weekday vs weekend profile separation (or single profile)
- Forecast granularity (15-min slots vs hourly)
- HA integration method (REST API vs SQLite direct access)
- Specific tiered aggregation scheme (time horizons, compression format)
- Graph color scheme and styling (matching dashboard theme)
- Exact clustering/binning of aggregation tiers

### Deferred Ideas (OUT OF SCOPE)

- Grossverbraucher-Muster (Waschmaschine, Trockner) separat lernen und bewerten
- "Morgen viel Sonne, willst du waschen?" — Dashboard-Hinweis und Telegram Push
- Telegram notification attribute for non-EV messages
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PLAN-04 | Hausverbrauch wird aus HA-Datenbank/InfluxDB-Historie hochgerechnet und in Planung berücksichtigt | InfluxDB `home_power` query patterns documented; HA REST API `/api/history/period` and WebSocket `energy/get_prefs` for entity discovery; tiered aggregation scheme designed |
| PLAN-05 | PV-Ertragsprognose wird via evcc Solar-Tariff API bezogen und in den 24-48h Plan integriert | evcc `/api/tariff/solar` format confirmed (Watt values, `start`/`end`/`value` slots); partial forecast handling pattern defined; correction coefficient architecture documented |
</phase_requirements>

---

## Summary

This phase builds two forecast subsystems that feed into the Phase 4 planner: a `ConsumptionForecaster` drawing from InfluxDB (primary) and HA (verification/gap fill), and a `PVForecaster` reading the evcc solar tariff API. Both models are lightweight — no scipy/scikit-learn required — fitting the Alpine Linux environment established in Phase 1.

The consumption forecast uses hour-of-day rolling averages stored in a versioned JSON model file at `/data/`. InfluxDB already stores `home_power` readings every 60 seconds (written by `influxdb_client.py`), providing the required history. HA's WebSocket `energy/get_prefs` API reveals which entities feed the energy dashboard, enabling entity validation and unconfigured entity warnings. The tiered compression scheme collapses data progressively: last 7 days at 15-min resolution, last 8–30 days at hourly averages, beyond 30 days as day-of-week profiles.

The PV forecast consumes the existing `evcc.get_tariff_solar()` method which already parses `start/end/value` slots in Watts. Partial forecast detection counts slots and computes a coverage ratio. A correction coefficient (rolling ratio of actual vs forecast kWh) is persisted separately in `/data/`. The dashboard gains a new SVG-based 24h forecast chart rendered using the established pattern (pure SVG, no external JS charting library), updated via SSE.

**Primary recommendation:** Build `ConsumptionForecaster` and `PVForecaster` as standalone Python modules at `/app/forecaster/`, integrating into the main loop at the StateStore update step. No new dependencies required — all infrastructure (InfluxDB HTTP client, evcc REST client, SSE broadcast, `requests`, `aiohttp`) already in the container.

---

## Standard Stack

### Core

| Library/Component | Version | Purpose | Why Standard |
|---|---|---|---|
| `requests` | already installed | InfluxDB v1 HTTP query API, HA REST API | Matches existing `influxdb_client.py` pattern exactly |
| `aiohttp` | already installed | HA WebSocket client for `energy/get_prefs` | Already in Dockerfile; needed for async WS handshake |
| `json` (stdlib) | stdlib | Versioned model persistence at `/data/` | No serialization library needed for flat dicts |
| InfluxDB v1 HTTP API | v1 (existing) | Query `home_power` history with `GROUP BY time()` | Already used and working; `influxdb_client.py` has `requests.get(/query)` pattern |
| evcc `/api/tariff/solar` | existing | PV generation forecast in Watts per slot | Already parsed in `evcc_client.get_tariff_solar()` — confirmed working |
| HA REST API `/api/history/period` | — | Fetch `home_power` entity state history (up to 10 days) | Pure HTTP GET with Bearer token; no library needed beyond `requests` |
| HA WebSocket `/api/websocket` | — | `energy/get_prefs` to discover configured energy dashboard entities | Only needed for initial entity discovery; `aiohttp` handles it |

### Supporting

| Library | Version | Purpose | When to Use |
|---|---|---|---|
| SVG (inline string) | — | 24h forecast chart rendering | Same pattern as existing `renderChart()` in `app.js` — no Plotly/Chart.js needed |
| `threading.Lock` | stdlib | Protect forecast model from concurrent reads/writes | Same pattern as `ManualSocStore` |
| `datetime` (stdlib) | stdlib | Slot indexing, hour-of-day bucketing, age checks | Already heavily used |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|---|---|---|
| InfluxDB HTTP query API (existing) | `influxdb-python` package | Package not in Dockerfile; existing raw HTTP approach is sufficient and already tested |
| HA WebSocket for entity discovery | SQLite direct read of HA database | SQLite path unknown/unmapped; WS API is the documented interface. REST `/api/states` filtered by `device_class=energy` is a valid fallback if WS is unavailable |
| In-memory + JSON file for model | SQLite | Overkill for 96-slot array; JSON is human-readable and crash-safe with atomic write pattern |
| Pure SVG chart (existing style) | Plotly.js | Plotly adds 3MB JS payload; SVG matches dashboard style and needs no additional assets |

**Installation:** No new packages required. All dependencies already in the Alpine container.

---

## Architecture Patterns

### Recommended Project Structure

```
/app/
├── forecaster/
│   ├── __init__.py          # exports ConsumptionForecaster, PVForecaster
│   ├── consumption.py       # ConsumptionForecaster — hour-of-day rolling averages
│   ├── pv.py                # PVForecaster — evcc solar tariff + correction coefficient
│   └── ha_energy.py         # HA energy entity discovery (WebSocket + REST fallback)
├── influxdb_client.py       # (existing) — extend with query_home_power_history()
├── evcc_client.py           # (existing) — get_tariff_solar() already works
├── state.py                 # (existing) — extend SystemState.consumption_forecast list
├── state_store.py           # (existing) — extend snapshot() with forecast data
└── web/
    └── static/app.js        # (existing) — add renderForecastChart()
```

### Pattern 1: ConsumptionForecaster — Hour-of-Day Rolling Averages

**What:** Maintains a `96-slot` array (one per 15-min slot of day) of rolling average `home_power` in Watts. Slot index = `(hour * 60 + minute) // 15`. For first 2 weeks or fallback: use default `1200 W` (1.2 kW) for all slots.

**When to use:** Called once per decision cycle (every 15 min) to update the model with the latest observation, then queried by the planner for next-24h consumption estimates.

**Tiered aggregation scheme (Claude's discretion — recommended):**
- **Last 7 days:** Full 15-min resolution from InfluxDB `home_power` field. Weight = 1.0 per observation.
- **Days 8–30:** Hourly averages from InfluxDB. Each hour contributes 4 virtual observations (distributed evenly across 4 slots). Weight = 0.5 (older data matters less).
- **Beyond 30 days:** Day-of-week profiles (Mon–Sun × 24 hourly values). Weight = 0.25. These survive compression restarts.

On schema version mismatch: clear in-memory model, rebuild from InfluxDB source data, re-save.

```python
# Source: existing influxdb_client.py pattern adapted
MODEL_PATH = "/data/smartprice_consumption_model.json"
MODEL_VERSION = 1

class ConsumptionForecaster:
    SLOTS_PER_DAY = 96   # 24h * 4 slots/h
    DEFAULT_WATTS = 1200  # sensible cold-start default

    def __init__(self, influx_client, cfg):
        self._influx = influx_client
        self._cfg = cfg
        self._slot_sums = [0.0] * self.SLOTS_PER_DAY
        self._slot_counts = [0] * self.SLOTS_PER_DAY
        self._correction_factor = 1.0  # actual/forecast ratio (last hour)
        self._data_days = 0            # how many days of real data
        self._lock = threading.Lock()
        self._load_or_init()

    def get_forecast_24h(self) -> list:
        """Return list of 96 estimated Watt values for next 24h slots."""
        with self._lock:
            now_slot = self._current_slot()
            result = []
            for i in range(self.SLOTS_PER_DAY):
                slot_idx = (now_slot + i) % self.SLOTS_PER_DAY
                if self._slot_counts[slot_idx] > 0:
                    avg = self._slot_sums[slot_idx] / self._slot_counts[slot_idx]
                    result.append(avg * self._correction_factor)
                else:
                    result.append(self.DEFAULT_WATTS)
            return result

    def update(self, current_watts: float, timestamp: datetime):
        """Called every 15-min cycle with actual home_power reading."""
        slot = self._current_slot(timestamp)
        with self._lock:
            # Weighted exponential decay: new observation counts more
            alpha = 0.1  # EMA weight — lower = smoother, higher = more reactive
            if self._slot_counts[slot] == 0:
                self._slot_sums[slot] = current_watts
                self._slot_counts[slot] = 1
            else:
                old_avg = self._slot_sums[slot] / self._slot_counts[slot]
                new_avg = (1 - alpha) * old_avg + alpha * current_watts
                self._slot_sums[slot] = new_avg
                self._slot_counts[slot] = 1  # normalized after EMA

    def apply_correction(self, actual_watts: float, forecast_watts: float):
        """Immediate self-correction: weight current hour deviation more heavily."""
        if forecast_watts > 100 and actual_watts > 0:
            raw_ratio = actual_watts / forecast_watts
            # Clamp to ±50% correction
            self._correction_factor = max(0.5, min(1.5, raw_ratio))
```

### Pattern 2: PVForecaster — evcc Solar Tariff + Correction Coefficient

**What:** Fetches `evcc.get_tariff_solar()` hourly, converts Watt slots to kWh values for each 15-min period. Tracks actual PV output vs forecast to derive a correction coefficient. Handles partial forecasts by counting how many future hours have data.

**When to use:** Called once per hour in a background timer (separate from 15-min decision cycle). Correction coefficient updated every decision cycle using real-time `state.pv_power`.

```python
# Source: evcc_client.py get_tariff_solar() already returns [{start, end, value}] in Watts
PV_MODEL_PATH = "/data/smartprice_pv_model.json"

class PVForecaster:
    def __init__(self, evcc_client):
        self._evcc = evcc_client
        self._slots = []        # list of {slot_utc, watt_forecast, watt_actual}
        self._correction = 1.0  # rolling actual/forecast ratio
        self._coverage_hours = 0
        self._load()

    def refresh(self):
        """Called hourly. Fetch new solar tariff from evcc."""
        rates = self._evcc.get_tariff_solar()
        if not rates:
            self._coverage_hours = 0
            return  # total failure: planner uses 0 kWh
        now = datetime.now(timezone.utc)
        future = [r for r in rates if self._parse_start(r) > now]
        self._coverage_hours = len(future)  # each slot = 1h in evcc solar API
        # Store for planner: list of (datetime, kw_forecast)
        self._slots = self._parse_to_kw_slots(rates, now)
        self._save()

    def get_forecast_24h(self) -> list:
        """Return 96-slot list of kW values (15-min resolution) for next 24h."""
        # Interpolate hourly evcc data to 15-min slots
        ...

    @property
    def confidence(self) -> float:
        """0.0 to 1.0 based on how many hours of data we have (24h = 1.0)."""
        return min(1.0, self._coverage_hours / 24.0)

    @property
    def correction_label(self) -> str:
        """Human-readable label: 'Korrektur: +13%' or 'Korrektur: -8%'"""
        pct = (self._correction - 1.0) * 100
        sign = "+" if pct >= 0 else ""
        return f"Korrektur: {sign}{pct:.0f}%"
```

### Pattern 3: HA Energy Entity Discovery

**What:** On startup, connect to HA WebSocket, send `energy/get_prefs`, parse `energy_sources[type=grid].flow_from[].stat_energy_from` entity IDs. Then use REST `/api/states?filter=energy` to find any `device_class=energy` + `state_class=total_increasing` sensors NOT in the energy dashboard config.

**When to use:** Once on startup. Results stored in memory; warnings emitted at start and broadcasted via SSE to dashboard banner.

**Discovery method — recommended: HA REST API with fallback**

Option A (preferred): HA WebSocket `energy/get_prefs`
- Requires: `ha_url`, `ha_token` (new config fields)
- Returns: structured list of configured entity IDs
- Use `aiohttp` (already installed) for WebSocket handshake

Option B (fallback): HA REST API `GET /api/states`
- Filter states where `attributes.device_class == "energy"` and `attributes.state_class in ["total", "total_increasing"]`
- No WebSocket needed — simpler, but can't distinguish dashboard-configured vs unconfigured without the WS call

Decision: implement WebSocket first, fall back to REST-only if WebSocket fails. Both `ha_url` and `ha_token` added to `Config` as optional fields.

```python
# HA WebSocket energy entity discovery
async def fetch_ha_energy_prefs(ha_url: str, token: str) -> dict:
    ws_url = ha_url.replace("http", "ws") + "/api/websocket"
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            # 1. receive auth_required
            await ws.receive_json()
            # 2. send auth
            await ws.send_json({"type": "auth", "access_token": token})
            auth_result = await ws.receive_json()
            if auth_result.get("type") != "auth_ok":
                return {}
            # 3. request energy prefs
            await ws.send_json({"id": 1, "type": "energy/get_prefs"})
            result = await ws.receive_json()
            return result.get("result", {})
```

### Pattern 4: Dashboard Forecast Chart (SVG, matching existing style)

**What:** New SVG chart section showing 24h consumption forecast (blue line) and PV generation forecast (yellow line) as overlaid curves. Background colored areas: green bands for cheap price slots, orange bands for battery discharge planned periods.

**Extends** existing `renderChart()` pattern in `app.js`. New endpoint: `GET /forecast` returns `{consumption_96, pv_96, price_zones_96, battery_phases_96}`.

**SSE integration:** When `store.update()` is called in main loop and forecast data changed, include `forecast` key in SSE payload. `app.js` `EventSource.onmessage` handler calls `renderForecastChart()` with new data.

```javascript
// SVG dual-line pattern matching existing dashboard style
function renderForecastChart(data) {
    var slots = data.consumption_96 || [];
    var pv = data.pv_96 || [];
    // Background colored rects for price zones (cheap=green, expensive=red alpha)
    // Two SVG path lines: consumption (blue #00d4ff) and PV (yellow #ffdd00)
    // Colored bands for planned battery charge/discharge phases
    // Same SVG viewBox and margin constants as existing chart
}
```

**Color scheme (Claude's discretion — recommended to match dark theme):**
- Consumption line: `#00d4ff` (same as existing battery limit line color)
- PV line: `#ffdd00` (same as existing solar gradient)
- Cheap price background: `rgba(0, 255, 136, 0.08)` (green, very subtle)
- Expensive price background: `rgba(255, 68, 68, 0.06)` (red, very subtle)
- Battery charge phase: `rgba(0, 255, 136, 0.15)` (green)
- Battery discharge phase: `rgba(255, 170, 0, 0.15)` (orange)

### Anti-Patterns to Avoid

- **Loading full 30-day InfluxDB history on every 15-min cycle:** Only load new observations incrementally; full rebuild only on schema version change
- **Synchronous aiohttp WebSocket in main thread:** Run `asyncio.run()` in a dedicated thread or use `threading` to avoid blocking the main decision loop
- **Storing raw Watt readings for all history:** Compress older data into slot averages — raw data at 1-min resolution for 30 days = 43,200 rows; aggregated = 96 floats
- **Using a single global correction factor:** Correction factor is slot-aware in PV (hourly), not a single multiplier applied to all hours
- **Treating evcc solar tariff values as kWh:** The API returns **Watts** (instantaneous power), not kWh. Must multiply by slot duration to get energy. Existing `calc_solar_surplus_kwh()` in `state.py` already has this logic.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| HA WebSocket auth protocol | Custom WS frame parser | `aiohttp` ClientSession + `ws_connect()` | Protocol details (auth_required, auth_ok, id-based responses) already handled |
| InfluxDB time-bucketed query | Custom time aggregation | InfluxQL `GROUP BY time(15m)` + `MEAN(home_power)` | Already used in `get_history_hours()`; just extend the query |
| JSON atomic file write | Custom file locking | Write to `.tmp` file, then `os.rename()` (atomic on Linux) | Prevents corrupt model file on crash mid-write |
| EMA-based rolling average | Full sliding window storage | Exponential moving average (EMA) — one float per slot | EMA with alpha=0.1 is sufficient for stable hour-of-day pattern; no numpy array of N observations needed |
| SSE forecast broadcast | Polling-based refresh | Extend existing `store.update()` → `_broadcast()` with forecast payload | Phase 1 SSE infrastructure already handles this pattern |

**Key insight:** The existing InfluxDB infrastructure already writes `home_power` every 60 seconds to the `Smartprice` measurement. The ConsumptionForecaster reads this same measurement back. No new data pipeline required.

---

## Common Pitfalls

### Pitfall 1: evcc Solar Tariff Returns Watts, Not kWh

**What goes wrong:** Dividing by 1000 to get kW, then treating that as kWh per slot. Results in 4x overestimation for 15-min slots.
**Why it happens:** The API response `value` field is power in Watts, not energy. `calc_solar_surplus_kwh()` in `state.py` already handles the unit detection via median heuristic (`> 100 → multiply by 0.001`). The value IS in Watts when from Forecast.Solar/Open-Meteo templates, or may be in kW from custom sources.
**How to avoid:** Reuse the existing unit heuristic from `calc_solar_surplus_kwh()`. Convert: `kw = value * unit_factor`, then `kwh = kw * (slot_duration_minutes / 60)`.
**Warning signs:** PV forecast totals exceeding 100 kWh for a sunny day.

### Pitfall 2: InfluxDB history_hours Query Missing Slot Resolution

**What goes wrong:** Using `GROUP BY time(1h)` gives 24 points — not enough for 15-min slot forecasting without interpolation.
**Why it happens:** `get_history_hours()` currently uses `GROUP BY time(1h)`. For the forecaster, `GROUP BY time(15m)` is needed for recent data.
**How to avoid:** Add `query_home_power_15min(days: int)` to `InfluxDBClient` using `GROUP BY time(15m)` for the recent tier, and separate queries for hourly/daily tiers.

### Pitfall 3: HA WebSocket Blocking the Main Thread

**What goes wrong:** `asyncio.run()` blocks in the main thread while `energy/get_prefs` waits for HA response. Main loop pauses for 2-5 seconds on startup.
**Why it happens:** `aiohttp` WebSocket requires an event loop; the main loop is synchronous.
**How to avoid:** Run HA entity discovery once in a `threading.Thread(daemon=True)` at startup. Store result in a thread-safe object. If HA is unreachable, log a warning and skip entity validation (non-critical path).
**Warning signs:** `SyntaxError: 'await' outside async function` or `RuntimeError: This event loop is already running`.

### Pitfall 4: Model Schema Version Mismatch on Restart

**What goes wrong:** After a code update that changes the slot count (e.g., 96 vs 24), the loaded model file has wrong dimensions and causes `IndexError`.
**Why it happens:** JSON model file shape changes between versions.
**How to avoid:** Always check `model["version"] == MODEL_VERSION` on load. If mismatch, log "Schema upgrade detected, rebuilding model from InfluxDB" and clear the in-memory state. The rebuild runs on the next update cycle.

### Pitfall 5: Cold Start Planner Using Forecaster Before Ready

**What goes wrong:** Phase 4 planner calls `get_forecast_24h()` when only 2 hours of data exist, getting a 94-slot array of defaults with 2 slots of real data — not representative.
**Why it happens:** No readiness gate on the forecaster.
**How to avoid:** `ConsumptionForecaster.is_ready` property: returns `True` only after at least 24h of data (`_data_days >= 1`). Before that, planner uses hardcoded defaults and logs "Forecaster not ready, using defaults (X/1440 observations)".

### Pitfall 6: HA REST API History Limited to ~10 Days

**What goes wrong:** Querying `/api/history/period` for 30-day history returns only 10 days (recorder purge window).
**Why it happens:** HA's recorder default `purge_keep_days` is often 10. The REST endpoint only serves recorder (short-term) data, not long-term statistics.
**How to avoid:** HA REST API is used only as a verification/gap-fill source, not for bulk history. InfluxDB is the primary history source — it has no purge limit. Document clearly: HA history endpoint is supplementary only.

### Pitfall 7: PV Correction Coefficient Drifting During Night Hours

**What goes wrong:** At night, `actual_pv = 0` and `forecast_pv = 0`, so ratio is `0/0` or `0/epsilon`. Correction coefficient becomes 0.
**Why it happens:** Division by near-zero forecast when both actual and forecast are zero.
**How to avoid:** Only update correction coefficient when `forecast_pv > 50 W` (daytime threshold). Skip night-time comparison cycles entirely.

---

## Code Examples

Verified patterns from existing codebase:

### InfluxDB 15-min Query for home_power

```python
# Source: adapted from influxdb_client.py get_history_hours()
def query_home_power_15min(self, days: int = 7) -> list:
    """Return home_power at 15-min resolution for last N days.
    Returns list of {ts_epoch, watts} dicts."""
    if not self._enabled:
        return []
    query = (
        f"SELECT mean(home_power) "
        f"FROM Smartprice "
        f"WHERE time > now() - {days}d "
        f"GROUP BY time(15m) fill(none)"
    )
    resp = requests.get(
        f"{self._base_url}/query",
        params={"db": self.database, "q": query},
        auth=self._auth,
        verify=self._verify,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for series in data.get("results", [{}])[0].get("series", []):
        for row in series.get("values", []):
            # row = [timestamp_str, mean_value]
            if row[1] is not None:
                results.append({"time": row[0], "watts": float(row[1])})
    return results
```

### Slot Index from Datetime

```python
def _slot_index(ts: datetime) -> int:
    """15-min slot index in day: 0 = 00:00-00:15, 95 = 23:45-24:00"""
    return (ts.hour * 60 + ts.minute) // 15
```

### JSON Atomic Write (crash-safe)

```python
import os
def _save_model(model: dict, path: str):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(model, f, indent=2)
    os.rename(tmp, path)  # atomic on Linux/Alpine
```

### evcc Solar Tariff Coverage Check

```python
# Source: evcc_client.get_tariff_solar() already returns list[dict]
def _count_forecast_hours(rates: list, now: datetime) -> int:
    """Count how many future 1h slots have forecast data."""
    future = 0
    for r in rates:
        start_str = r.get("start", "")
        try:
            if start_str.endswith("Z"):
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            else:
                start = datetime.fromisoformat(start_str)
            if start > now:
                future += 1
        except Exception:
            continue
    return future  # 0 = total failure, 1-23 = partial, 24+ = full coverage
```

### HA WebSocket energy/get_prefs (async, run in thread)

```python
# aiohttp already in Dockerfile
import asyncio, aiohttp

async def _fetch_energy_prefs_async(ha_url: str, token: str) -> dict:
    ws_url = ha_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    ws_url += "/api/websocket"
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(ws_url) as ws:
            await ws.receive_json()  # auth_required
            await ws.send_json({"type": "auth", "access_token": token})
            msg = await ws.receive_json()
            if msg.get("type") != "auth_ok":
                return {}
            await ws.send_json({"id": 1, "type": "energy/get_prefs"})
            result = await ws.receive_json()
            return result.get("result", {})

def fetch_ha_energy_prefs(ha_url: str, token: str) -> dict:
    """Synchronous wrapper — call from a daemon thread."""
    try:
        return asyncio.run(_fetch_energy_prefs_async(ha_url, token))
    except Exception as e:
        log("warning", f"HA energy/get_prefs failed: {e}")
        return {}
```

### SSE Forecast Update in StateStore

```python
# Source: state_store.py update() pattern
def update(self, state, lp_action, rl_action, solar_forecast,
           consumption_forecast=None, pv_forecast=None):
    with self._lock:
        self._state = state
        self._lp_action = lp_action
        self._rl_action = rl_action
        self._solar_forecast = solar_forecast
        if consumption_forecast is not None:
            self._consumption_forecast = consumption_forecast
        if pv_forecast is not None:
            self._pv_forecast = pv_forecast
    self._broadcast()  # outside lock, as per Phase 1 decision
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| Fixed `home_power = 1.0 kW` default in slot calculations | Per-slot 15-min rolling average from InfluxDB history | Phase 3 | Planner gets accurate load shape instead of flat estimate |
| `solar_forecast_total_kwh` (scalar, from evcc) | 24h × 96-slot PV forecast with correction coefficient | Phase 3 | Planner can shift loads to PV surplus windows, not just total available energy |
| No forecaster readiness gate | Cold start: 24h data collection before activation | Phase 3 | Prevents bad forecasts in first day of operation |
| HA energy entities not checked | `energy/get_prefs` discovery + unconfigured entity warnings | Phase 3 | User notified of missing meters that affect accuracy |

**Deprecated/outdated:**
- `calc_solar_surplus_kwh()` in `state.py`: Still used for battery-to-EV calculations. The new `PVForecaster.get_forecast_24h()` supplements it for planning — do not replace it.
- `solar_forecast_total_kwh` in `SystemState`: Still updated by main loop for RL features. The planner (Phase 4) will use the richer 96-slot array from `PVForecaster`.

---

## Open Questions

1. **HA URL and Token configuration**
   - What we know: HA WebSocket discovery requires `ha_url` (e.g., `http://homeassistant.local:8123`) and a Long-Lived Access Token. These are not in the current `Config`.
   - What's unclear: Are these already available inside the HA add-on environment via supervisor API or env vars?
   - Recommendation: Inside HA add-ons, `http://supervisor/core` and `SUPERVISOR_TOKEN` env var are available automatically. Check for `os.environ.get("SUPERVISOR_TOKEN")` — if present, use supervisor API at `http://supervisor/core/api/websocket` with `SUPERVISOR_TOKEN`. Otherwise, require optional `ha_url`/`ha_token` config fields. This is a **low-risk question** — handle in planning.

2. **InfluxDB `home_power` field name consistency**
   - What we know: `influxdb_client.write_state()` writes `home_power` to measurement `Smartprice`. The field name is set in `write_state()`.
   - What's unclear: Whether all historical data uses exactly `home_power` as the field name (no typos from earlier versions).
   - Recommendation: Add a query at forecaster init to verify field exists and has recent data. Log warning if field is empty.

3. **Weekday vs weekend profile separation (Claude's discretion)**
   - What we know: German household consumption patterns differ ~15% between weekday and weekend.
   - Recommendation: **Implement single unified profile first.** Weekday/weekend split can be added in Phase 8 (seasonal learner). Rationale: doubles storage and complexity for marginal gain in first 14 days of data collection.

4. **evcc solar API slot duration**
   - What we know: evcc internally converts all tariff slots to 15-min resolution. The solar API returns `start`/`end`/`value` pairs; the duration varies by source (Forecast.Solar = 15min, Open-Meteo = hourly).
   - What's unclear: Does `/api/tariff/solar` always return consistent slot durations?
   - Recommendation: Always compute `slot_duration = (end - start).total_seconds() / 3600` per slot and use it for kWh calculation. Do not assume a fixed slot size.

---

## Sources

### Primary (HIGH confidence)

- Existing codebase: `influxdb_client.py`, `evcc_client.py`, `config.py`, `state.py`, `main.py` — confirmed field names, measurement structure, HTTP patterns
- `influxdb_client.py:get_history_hours()` — confirms InfluxDB v1 HTTP query API with `GROUP BY time(1h)` works
- `evcc_client.get_tariff_solar()` — confirmed returns `[{start, end, value}]` in Watts; `calc_solar_surplus_kwh()` confirms unit heuristic
- `state.py:calc_solar_surplus_kwh()` — confirmed Watt-to-kWh conversion pattern with slot duration calculation
- [InfluxDB v1 OSS Query API](https://docs.influxdata.com/influxdb/v1/tools/api/) — `GROUP BY time(interval)` + `MEAN()` syntax
- [InfluxQL Functions Reference](https://docs.influxdata.com/influxdb/v1/query_language/functions/) — `MEAN()` for time-window averaging
- Dockerfile — confirms `aiohttp` already installed; no new packages needed
- [HA REST API Developer Docs](https://developers.home-assistant.io/docs/api/rest/) — `/api/history/period` endpoint, 10-day limit for short-term data

### Secondary (MEDIUM confidence)

- [HA Core energy/websocket_api.py](https://github.com/home-assistant/core/blob/dev/homeassistant/components/energy/websocket_api.py) — confirms `energy/get_prefs` command exists, returns `energy_sources` with `flow_from[].stat_energy_from` entity IDs
- [Alpine Linux py3-websocket-client package](https://pkgs.alpinelinux.org/package/edge/community/x86/py3-websocket-client) — confirms `aiohttp` (via `py3-aiohttp`) available; existing Dockerfile already installs it
- [evcc Tariffs & Forecasts docs](https://docs.evcc.io/en/docs/tariffs) — solar tariff slot format (`start`, `end`, `value` in Watts)
- [HA WebSocket API general docs](https://developers.home-assistant.io/docs/api/websocket/) — auth protocol confirmed (auth_required → auth → auth_ok → commands)
- [Sandy's Blog: InfluxDB Flux hourly averages by weekday](https://blog.sandydrew.com/2024/05/influxdb-grafana-electricity-average-usage) — confirms 15-min aggregation patterns for power consumption data

### Tertiary (LOW confidence)

- [HA Community: Can I get Long Term Statistics from the REST API?](https://community.home-assistant.io/t/can-i-get-long-term-statistics-from-the-rest-api/761444) — REST API limited to recorder short-term data; WebSocket needed for long-term stats (but we use InfluxDB for history, so irrelevant)
- HA Supervisor `SUPERVISOR_TOKEN` env var pattern — known from general HA add-on development knowledge, not verified against current supervisor version

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in container; InfluxDB query pattern already working
- Architecture: HIGH — patterns derived directly from existing codebase
- HA entity discovery: MEDIUM — WebSocket API structure confirmed from source code review; supervisor token pattern LOW (unverified)
- evcc solar API format: HIGH — confirmed via existing `get_tariff_solar()` and `calc_solar_surplus_kwh()` in codebase
- Pitfalls: HIGH — most derived from direct codebase analysis (unit confusion already handled in existing code)
- Dashboard chart: HIGH — SVG pattern identical to existing `renderChart()`, no new dependencies

**Research date:** 2026-02-22
**Valid until:** 2026-05-22 (stable InfluxDB v1 API + evcc REST API; HA WebSocket may shift but energy/get_prefs has been stable since 2021.8)
