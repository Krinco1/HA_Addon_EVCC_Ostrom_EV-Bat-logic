# Architecture

**Analysis Date:** 2026-02-22

## Pattern Overview

**Overall:** Event-driven optimization loop with hybrid decision-making (Linear Programming + Reinforcement Learning shadow mode) and charge sequencing.

**Key Characteristics:**
- Main control loop cycles every 15 minutes (configurable)
- Dual-optimizer pattern: LP (production) vs RL (shadow learning)
- Per-device mode switching: battery and EV can independently use LP or RL
- Modular provider architecture for multi-vehicle support
- Optional Telegram notification layer for driver interactions
- Background threads for polling, web server, and async tasks

## Layers

**Data Collection Layer:**
- Purpose: Gather real-time system state and vehicle data
- Location: `evcc-smartload/rootfs/app/vehicle_monitor.py`, `evcc-smartload/rootfs/app/collector.py`
- Contains: Vehicle polling, InfluxDB historical data, evcc API integration
- Depends on: EvccClient, VehicleManager, InfluxDBClient
- Used by: SystemState builder, MainLoop

**State Management Layer:**
- Purpose: Maintain and transform system state snapshots
- Location: `evcc-smartload/rootfs/app/state.py`
- Contains: SystemState dataclass, Action dataclass, price percentile computation
- Depends on: Config, datetime/numpy utilities
- Used by: Optimizer, RL agent, Controller

**Energy Decision Layer (Optimization):**
- Purpose: Generate charging recommendations
- Location: `evcc-smartload/rootfs/app/optimizer/` and `evcc-smartload/rootfs/app/rl_agent.py`
- Contains: HolisticOptimizer (LP), DQNAgent (RL), EventDetector
- Depends on: SystemState, Config, tariff data
- Used by: Controller, Comparator, MainLoop
- Key classes:
  - `HolisticOptimizer`: Greedy percentile-threshold scheduling
  - `DQNAgent`: Q-table DQN with 35-action space (7 battery × 5 EV)
  - `EventDetector`: Identifies tariff/SoC events that require reward weighting

**Charge Sequencing Layer (v5):**
- Purpose: Coordinate multi-EV charging with quiet hours
- Location: `evcc-smartload/rootfs/app/charge_sequencer.py`
- Contains: ChargeSequencer, ChargeRequest, ChargeSlot, QuietHoursConfig
- Depends on: Config, EvccClient, tariff data
- Used by: MainLoop, WebServer, NotificationManager
- Behavior: Schedules one EV at a time, respects night quiet hours, prioritizes connected vehicles

**Control & Execution Layer:**
- Purpose: Apply decisions to evcc
- Location: `evcc-smartload/rootfs/app/controller.py`
- Contains: Controller (battery/EV mode translation), RLDeviceController (per-device mode tracking)
- Depends on: EvccClient, Action, Config
- Used by: MainLoop

**Evaluation Layer:**
- Purpose: Compare strategies and compute RL rewards
- Location: `evcc-smartload/rootfs/app/comparator.py`
- Contains: Comparator (cost tracking and reward calculation), per-device win tracking
- Depends on: Action, SystemState, Config
- Used by: MainLoop (learning), WebServer (dashboard)

**Vehicle Integration Layer:**
- Purpose: Abstract vehicle SoC fetching across multiple APIs
- Location: `evcc-smartload/rootfs/app/vehicles/`
- Contains:
  - `base.py`: VehicleData model
  - `manager.py`: VehicleManager factory pattern
  - `kia_provider.py`, `renault_provider.py`, `evcc_provider.py`, `custom_provider.py`: Implementations
- Depends on: HTTP clients (requests), API credentials from config
- Used by: VehicleMonitor

**Driver & Notification Layer (v5):**
- Purpose: Telegram notifications and driver preferences
- Location: `evcc-smartload/rootfs/app/driver_manager.py`, `evcc-smartload/rootfs/app/notification.py`
- Contains: DriverManager (YAML config), TelegramBot (polling), NotificationManager (router)
- Depends on: python-telegram-bot SDK, drivers.yaml config
- Used by: MainLoop (charge inquiry triggers), ChargeSequencer callbacks

**Web/API Layer:**
- Purpose: REST endpoints and real-time dashboard
- Location: `evcc-smartload/rootfs/app/web/`
- Contains:
  - `server.py`: HTTP handler with GET/POST endpoints
  - `template_engine.py`: Jinja2 rendering
  - `static/`: SVG charts, JS
  - `templates/`: dashboard.html and docs
- Depends on: WebServer, state from MainLoop, decision_log
- Used by: Browser clients, external integrations

**Infrastructure Layer:**
- Purpose: External integrations and persistence
- Location: `evcc-smartload/rootfs/app/evcc_client.py`, `evcc-smartload/rootfs/app/influxdb_client.py`, `evcc-smartload/rootfs/app/config.py`
- Contains: EvccClient (REST), InfluxDBClient (time-series), Config (YAML/JSON loader)
- Depends on: requests library, filesystem
- Used by: All layers

## Data Flow

**Main Decision Cycle (v5):**

1. **Collect** (DataCollector.get_current_state())
   - Fetch evcc state: battery SoC, grid power, grid tariff
   - Poll vehicle APIs on schedule (every 60 min default)
   - Update from evcc loadpoint: wallbox connection status
   - Return: SystemState with current_price, battery_soc, ev_connected, ev_soc

2. **Enrich** (main.py line 134-152)
   - Compute price_percentiles from 24-hour tariff window (P20, P30, P40, P60, P80)
   - Calculate price_spread = P80 - P20
   - Count hours_cheap_remaining (below P30)
   - Compute solar_forecast_total_kwh
   - Result: Extended SystemState ready for optimization

3. **Detect Events** (EventDetector.detect())
   - Check for tariff boundary crossings
   - Identify SoC thresholds crossed
   - Return: List of event strings for reward weighting

4. **Optimize in Parallel:**
   - **LP Branch** (HolisticOptimizer.optimize()):
     - Analyze demand: battery_need_kwh, ev_need_kwh
     - Assess urgency based on SoC, forecast, cheap hours
     - Select percentile tier (P20/P40/P60 threshold)
     - Return: Action with (battery_action, battery_limit_eur, ev_action, ev_limit_eur)

   - **RL Branch** (DQNAgent.select_action()):
     - Discretize SystemState to 31-d feature vector
     - Query Q-table for state bin
     - Epsilon-greedy exploration
     - Return: Action from same space as LP

5. **Device Mode Selection** (main.py line 169-175)
   - Get per-device mode from RLDeviceController
   - battery: "lp" or "rl"
   - ev: "lp" or "rl" (if connected)
   - Blend actions: final_action = (rl_action if mode=="rl" else lp_action)

6. **Execute & Adapt** (main.py line 177-198)
   - Controller.apply(final_action) → EvccClient.set_battery_grid_charge_limit(), set_smart_cost_limit()
   - ChargeSequencer.plan() → updates charge schedule
   - ChargeSequencer.apply_to_evcc() → selects wallbox target vehicle
   - Battery-to-EV optimization: discharge battery if profitable

7. **Learn & Evaluate** (main.py line 216-228)
   - Imitation learning: RL agent learns from LP (gradient toward LP decision)
   - Temporal difference learning: reward(t-1) + value(t) → update Q-table
   - Comparator tracks costs: LP cost vs RL cost
   - Determine RL readiness: if RL_wins / total > threshold → enable switching

8. **Notify & Log** (main.py line 200-212, 244-248)
   - Check ChargeSequencer recommendations for Telegram reminders
   - Send charge inquiries when price is cheap and vehicle needs energy
   - Log to DecisionLog (50 recent entries)
   - Write to InfluxDB for historical analysis

**State Management:**

- **Transient (in-memory per cycle):** SystemState, Action
- **Session (process lifetime):** DQNAgent Q-table, ReplayMemory, Comparator cost tracking, DecisionLog (circular buffer)
- **Persistent (filesystem):**
  - `/data/smartprice_rl_model.json` — Q-table snapshot (saved every 50 steps)
  - `/data/smartprice_rl_memory.json` — Replay buffer (for bootstrapping)
  - `/data/smartprice_comparison.json` — LP vs RL cost comparison history
  - `/data/smartprice_manual_soc.json` — Manual SoC overrides
  - Config loaded from `/data/options.json` (Home Assistant add-on)
  - Vehicles from `/config/vehicles.yaml`
  - Drivers from `/config/drivers.yaml` (optional)

## Key Abstractions

**Action (state.py):**
- Purpose: Unified action representation
- Structure: battery_action ∈ [0,6], ev_action ∈ [0,4], battery_limit_eur, ev_limit_eur
- Battery actions: 0=hold, 1=P20, 2=P40, 3=P60, 4=max, 5=PV-only, 6=discharge
- EV actions: 0=no_charge, 1=P30, 2=P60, 3=max, 4=PV-only
- Used by: LP, RL, Controller, Comparator

**SystemState (state.py):**
- Purpose: Complete read-only snapshot of energy system
- Contains: Battery (SoC, power), Grid (power, price), PV, Home, EV, Forecasts
- Extended (v5): price_percentiles dict, price_spread, hours_cheap_remaining, solar_forecast_total_kwh
- to_vector(): Normalizes to 31-d numpy array for RL agent
- Used by: Optimizer, RL agent, Controller, Web API

**VehicleData (vehicles/base.py):**
- Purpose: Abstract vehicle state
- Contains: name, capacity_kwh, soc, manual_soc, connected_to_wallbox, data_source ("api"/"evcc"/"manual")
- get_effective_soc(): Returns best available SoC (manual > API > default)
- is_data_stale(): Checks freshness threshold
- Implementations: KiaProvider, RenaultProvider, EvccProvider, CustomProvider

**ChargeRequest (charge_sequencer.py):**
- Purpose: Captures confirmed driver request
- Contains: vehicle_name, target_soc, current_soc, capacity_kwh, charge_power_kw, status
- Status flow: pending → scheduled → charging → done / expired
- Used by: Sequencer for ranking and scheduling

**DecisionEntry (decision_log.py):**
- Purpose: Log decisions with category and icon
- Categories: "observe", "plan", "action", "warning", "rl", "sequencer"
- Icons: 👁️ 🧠 ⚡ ⚠️ 🤖 🔄
- Used by: Web dashboard for decision tracing

## Entry Points

**main.py:**
- Location: `evcc-smartload/rootfs/app/main.py`
- Triggers: Container startup via Docker entrypoint
- Responsibilities:
  - Initialize all components (evcc, influx, optimizer, RL agent, sequencer, telegram)
  - Bootstrap RL from InfluxDB historical data if no model exists
  - Start background threads (vehicle polling, web server)
  - Run main decision loop (infinite while True with exception recovery)
  - Coordinate decision flow: collect → optimize → execute → learn → log

**WebServer.start():**
- Location: `evcc-smartload/rootfs/app/web/server.py:73()`
- Triggers: Called by main() at startup
- Responsibilities:
  - Start HTTPServer on port 8099
  - Handle GET endpoints: `/`, `/status`, `/vehicles`, `/rl-devices`, `/strategy`, `/sequencer`, `/drivers`, `/chart-data`
  - Handle POST endpoints: `/vehicles/manual-soc`, `/sequencer/request`, `/sequencer/cancel`
  - Serve static files (CSS, JS) and rendered dashboard.html

**Background Threads:**
- VehicleMonitor.start_polling() — Poll vehicle APIs every 60 minutes
- DataCollector.start_background_collection() — Collect evcc state every 60 seconds
- TelegramBot.start_polling() — Poll Telegram for driver responses (optional, if enabled)

## Error Handling

**Strategy:** Defensive with graceful degradation. All external API calls wrapped in try/except.

**Patterns:**

1. **Network failures:**
   - EvccClient methods return None on connection error
   - InfluxDBClient silently drops writes on failure (non-critical)
   - Vehicle API polls log warning but continue
   - Main loop catches all exceptions and sleeps 60s before retry

2. **Data staleness:**
   - VehicleData tracks last_update and last_poll timestamps
   - is_data_stale() method checks STALE_THRESHOLD_MINUTES (60 min)
   - Dashboard displays data age and warnings

3. **Configuration issues:**
   - Missing vehicles.yaml: Copied from example, logged
   - Missing drivers.yaml: Gracefully disables notifications, logged
   - Invalid provider config: Logs error, uses EvccProvider fallback

4. **RL agent failures:**
   - load() returns False if model file missing or corrupted
   - Main loop bootstrap_from_influxdb() fetches 168-hour historical data
   - Q-table state dimension mismatch detected on load → reset with warning
   - Fallback to LP if RL epsilon > rl_fallback_threshold (0.7)

## Cross-Cutting Concerns

**Logging:**
- Utility: `logging_util.py` wraps print statements with level prefix and timestamp
- Levels: "info", "warning", "error", "debug"
- No file logging (stdout to container logs only)

**Validation:**
- Configuration: load_config() applies type coercion and range checks
- Actions: Controller ensures battery_limit_eur and ev_limit_eur are non-negative
- Percentiles: compute_price_percentiles() handles edge cases (too few datapoints)

**Authentication:**
- evcc: Optional password via config → EvccClient._login() on first API call
- InfluxDB: Basic auth via config (username/password)
- Telegram: Bot token from drivers.yaml (no user-facing auth required)

**Time Handling:**
- All internal timestamps: UTC (datetime.timezone.utc)
- Dashboard displays: Local time via astimezone()
- Price tariffs: ISO8601 parsing with fallback
- Sleep precision: Main loop uses time.sleep() in seconds

**Persistence:**
- JSON format: RL model, memory, comparison log, manual SoC
- sqlite3: Device control history (created by RLDeviceController if needed)
- No database layer (direct file I/O)
- Saves triggered every 50 learning steps or manually via Web POST

---

*Architecture analysis: 2026-02-22*
