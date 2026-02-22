# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-22)

**Core value:** The system makes the economically best energy decision at every moment using all available information — and the user understands why
**Current focus:** Phase 3 — Data Foundation

## Current Position

Phase: 3 of 8 (Data Foundation)
Plan: 3 of 3 in current phase (awaiting human-verify checkpoint)
Status: In progress — checkpoint reached
Last activity: 2026-02-22 — Completed plans 03-01, 03-02, 03-03 tasks 1-2; awaiting dashboard verification at checkpoint

Progress: [█████░░░░░] 38%

## Performance Metrics

**Velocity:**
- Total plans completed: 6
- Average duration: 3 min
- Total execution time: 0.3 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| Phase 1 | 2 | 12 min | 6 min |
| Phase 2 | 2 | 7 min | 3.5 min |
| Phase 3 | 3 (of 3) | 7 min | 2.3 min |

**Recent Trend:**
- Last 5 plans: 8 min, 4 min, 2 min, 5 min, 2 min
- Trend: improving

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Research]: scipy/HiGHS via apk (musl-safe), plotly via pip (pure Python), numpy micro-MLP — no PyTorch/TensorFlow (glibc incompatibility on Alpine)
- [Research]: RL agent changes from full action selection to delta corrections (±20 ct clip) — residual learning on planner output, not end-to-end
- [Research]: StateStore (RLock-guarded) replaces ad-hoc module-level globals — web server becomes strictly read-only
- [Research]: DynamicBufferCalc runs in observation mode first 2 weeks before going live — coefficients need empirical tuning
- [Research]: SeasonalLearner deployed at Phase 8 start (not end) — needs months of data accumulation, earlier is better
- [Research]: PV forecast comes from evcc solar tariff API (price signal), not kWh — planner must handle partial forecasts with confidence reduction
- [01-01]: RLock (not Lock) guards StateStore to prevent deadlock if nested calls occur
- [01-01]: SSE broadcast happens outside the RLock to avoid I/O while holding the state lock
- [01-01]: ThreadedHTTPServer with daemon_threads=True enables concurrent SSE + API requests without blocking
- [01-01]: Existing 60s polling preserved in app.js as fallback; SSE is an enhancement layer
- [01-02]: WebServer started before EvccClient/InfluxDB construction so error page is reachable even on critical config errors
- [01-02]: WebServer component attributes populated via late-binding after init rather than second server instance — avoids port conflict
- [01-02]: ConfigValidator uses hasattr() on all field accesses for forward compatibility with future Config shape changes
- [01-02]: Non-critical safe defaults applied before I/O objects are created so downstream components see corrected values
- [02-01]: _prev_connected dict is not lock-guarded because update_from_evcc() is exclusively called from DataCollector._collect_once() (single-threaded); dict never accessed from _poll_loop()
- [02-01]: trigger_refresh() is the correct integration point for connection events (not direct poll_vehicle()) — I/O must stay in _poll_loop(), worst-case 30s delay acceptable for RELI-01
- [02-01]: sequencer.update_soc() loop placed before sequencer.plan() inside existing 'if sequencer is not None:' block — no-op for vehicles not in sequencer.requests (safe by design)
- [02-02]: Price conversion heuristic price_ct > 1.0 distinguishes ct/kWh (e.g. 28.5) from EUR/kWh legacy values (e.g. 0.285); covers Tibber and aWATTar dynamic tariff formats
- [02-02]: getattr with default 1000 in main.py provides forward-compatible access to rl_bootstrap_max_records for options.json schema mismatches
- [02-02]: InfluxDB _enabled guard added to bootstrap to skip cleanly when InfluxDB not configured
- [03-01]: Single unified consumption profile (no weekday/weekend split) — simplicity first, seasonal split deferred to Phase 8
- [03-01]: SUPERVISOR_TOKEN auto-detection in load_config() — ha_url/ha_token auto-populated inside HA add-on without user config
- [03-01]: Hourly save interval (every 4 updates) reduces InfluxDB I/O by 4x; data loss limited to last hour's EMA on crash
- [03-01]: Tiered bootstrap weights 1.0/0.5 (7d@15min / 8-30d@1h) — recent patterns dominate, historical provides baseline
- [03-02]: Correction EMA alpha=0.1 per 15-min cycle: smoother reaction, avoids overcorrecting on transient clouds
- [03-02]: Correction bounds [0.3, 3.0]: wider than consumption [0.5, 1.5] because PV can legitimately be 3x forecast on unexpectedly sunny days
- [03-02]: Variable slot duration computed per slot via (end - start).total_seconds(): handles mixed 15-min and 1h evcc slot sources
- [03-02]: future_hours sums actual slot durations (not slot count) for accurate partial forecast detection
- [03-02]: Only _correction persisted to disk (not _slots): forecast data is ephemeral, re-fetched hourly
- [03-03]: Price zone classification uses current price_percentiles P30/P60 as proxy for all 96 slots — proper per-slot classification deferred to Phase 4 when planner generates slot-level decisions
- [03-03]: PV unit auto-detection in renderForecastChart: pvMax > 20 means Watts, else kW (same heuristic as state.py)
- [03-03]: apply_correction() only called when current_forecast[0] > 100W to avoid meaningless correction on cold-start defaults
- [03-03]: Forecast section added to SSE JSON payload via _snapshot_to_json_dict() — enables live chart updates without additional polling

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 2 - RESOLVED]: All Phase 2 RELI requirements addressed — RELI-01, RELI-02 in 02-01; RELI-05 in 02-02
- [Phase 5]: DynamicBufferCalc formula coefficients (spread_bonus 0.3, pv_reduction 2.0) are design estimates — plan 2-4 week observation period before enabling live buffer changes
- [Phase 8]: RL constraint audit required before promoting from shadow to advisory — 30-day minimum shadow period; SeasonalLearner needs months for statistically meaningful cells
- [Research gap]: PV forecast from evcc solar tariff is a price signal, not kWh generation — resolution needed in Phase 3 planning (Forecast.Solar API integration vs InfluxDB irradiance history)
- [Research gap RESOLVED by 03-02]: evcc partial forecasts now handled via coverage_hours / 24.0 confidence ratio — PVForecaster returns 96 zeros with confidence=0.0 on total failure; Plan 03 wires this into planner conservatism

## Session Continuity

Last session: 2026-02-22
Stopped at: 03-03-PLAN.md checkpoint:human-verify (Task 3) — both auto tasks complete, awaiting dashboard verification
Resume file: .planning/phases/03-data-foundation/03-03-PLAN.md (Task 3: verify dashboard forecast visualization)
