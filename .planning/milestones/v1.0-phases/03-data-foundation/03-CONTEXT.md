# Phase 3: Data Foundation - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Provide the planner with accurate house consumption forecasts and PV generation estimates sourced from real historical data. Replace fixed defaults with data-driven inputs. Includes dashboard visualization of forecast data.

</domain>

<decisions>
## Implementation Decisions

### Consumption Forecast Model
- InfluxDB as primary data source (better adapted for this project), HA database as optional enrichment/verification source
- When both are configured: HA verifies InfluxDB data AND fills gaps — full integration of both sources with validation processes to ensure data consistency
- HA Energy Dashboard entities as the consumption source — read the entities configured in HA's energy dashboard
- Additionally detect and warn about energy entities that are NOT configured in the Energy Dashboard but probably should be (could significantly affect numbers)
- Warning display: both Dashboard banner AND detailed log entry with entity IDs
- Immediate self-correction: when actual load deviates significantly from forecast, current hour gets weighted more heavily in the rolling average — fast reaction to changes
- Tiered aggregation for history: recent data at full resolution, older data increasingly compressed (hour averages → day averages → week profiles). Claude decides the specific compression scheme and time horizons
- Persistent storage: aggregated model saved to /data/, survives restarts. Must be versioned — on schema upgrade, historical compressions are rebuilt from source data if available
- Forecaster updates its model every decision cycle (every 15 min)

### PV Forecast Handling
- Use the solar forecast API already configured in evcc, accessible via the evcc API
- Hourly refresh from evcc API
- Actual PV generation data compared against forecast to compute a correction coefficient that improves forecast reliability over time
- PV correction coefficient: shown on dashboard as subtle info below PV graph (e.g., "Korrektur: +13%")
- On partial forecast (<24h data): reduced confidence proportional to data coverage (e.g., 12h = 50% confidence), planner becomes more conservative
- On total API failure: planner operates without PV forecast, assumes 0 kWh generation — conservative and safe
- PV forecast quality displayed subtly below graph (e.g., "Basierend auf 18h Forecast-Daten")
- PV correction coefficient stored separately from consumption model (independently updatable)

### Dashboard Forecast Visualization
- 24h forecast graph: consumption and PV generation as two overlaid lines in the same graph — surplus/deficit directly visible
- Battery charge/discharge phases shown as colored areas behind the lines (green=charge, orange=discharge) — visualizes the planner's decisions
- Electricity price zones as background colors on the timeline (green=cheap, red=expensive) — shows why the planner decided as it did
- Graph style: Claude decides, matching existing dashboard design
- Live graph updates via SSE when new forecast data arrives — consistent with Phase 1 SSE infrastructure

### Cold Start Behavior
- Absolute fresh start (no data): collect 24h of data before forecaster becomes active — planner pauses during this collection phase (no optimization, standard charging behavior only)
- After 24h: hybrid mode — available data blended with defaults, default proportion decreases as more data accumulates
- Dashboard shows forecaster maturity as progress indicator (e.g., "Verbrauchsprognose: 5/14 Tage Daten, Genauigkeit steigt noch")

### Forecast Freshness
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

</decisions>

<specifics>
## Specific Ideas

- Tiered history compression concept: "Eine Art aussagefaehiger Aggregations-Hash — historische Daten werden umso weiter sie zurueckliegen in noch verwertbare Informationen komprimiert." Could use binary blobs, bitmaps, or base64-encoded compressed data for efficient storage.
- HA Energy Dashboard entity detection: system should not just read configured entities but also identify unconfigured energy entities that might be missing from the dashboard and could significantly affect forecast accuracy.
- PV correction coefficient: actual vs. forecast comparison builds reliability metric over time — the longer it runs, the more precise the PV forecast becomes.

</specifics>

<deferred>
## Deferred Ideas

- Grossverbraucher-Muster (Waschmaschine, Trockner) separat lernen und bewerten — analogous to EV consumption patterns
- "Morgen viel Sonne, willst du waschen?" — Dashboard-Hinweis und Telegram Push when conditions are favorable for large loads
- Telegram notification attribute for non-EV messages (separate from EV-specific alerts)

</deferred>

---

*Phase: 03-data-foundation*
*Context gathered: 2026-02-22*
