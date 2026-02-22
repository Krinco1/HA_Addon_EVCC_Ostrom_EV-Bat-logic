# Codebase Structure

**Analysis Date:** 2026-02-22

## Directory Layout

```
smartload/
├── README.md                    # Installation instructions (German)
├── CHANGELOG.md                 # Version history
├── repository.yaml              # Home Assistant add-on registry metadata
├── .planning/
│   └── codebase/               # GSD codebase analysis documents
│
└── evcc-smartload/
    └── rootfs/
        └── app/
            ├── main.py                      # Entry point: main decision loop
            ├── version.py                   # Version string
            ├── config.py                    # Configuration loader & defaults
            ├── logging_util.py              # Logging wrapper
            │
            ├── state.py                     # SystemState, Action, percentile computation
            │
            ├── evcc_client.py               # evcc REST API client
            ├── influxdb_client.py           # InfluxDB v1.x HTTP writer
            │
            ├── vehicle_monitor.py           # Vehicle polling coordinator
            ├── collector.py                 # System state builder (evcc + vehicles)
            ├── vehicles/
            │   ├── __init__.py
            │   ├── base.py                  # VehicleData model
            │   ├── manager.py               # VehicleManager factory pattern
            │   ├── evcc_provider.py         # Via evcc wallbox SoC only
            │   ├── kia_provider.py          # KIA / Hyundai / Genesis API
            │   ├── renault_provider.py      # Renault / Dacia API
            │   └── custom_provider.py       # Custom HTTP endpoint
            │
            ├── optimizer/
            │   ├── __init__.py
            │   ├── holistic.py              # HolisticOptimizer (LP, percentile-based)
            │   ├── events.py                # Event models
            │   └── event_detector.py        # Tariff & SoC event detection
            │
            ├── rl_agent.py                  # DQNAgent (Q-table, 31-d state, 35 actions)
            ├── comparator.py                # LP vs RL comparison & reward calculation
            │
            ├── controller.py                # Apply actions to evcc API
            ├── charge_sequencer.py          # Multi-EV wallbox scheduling (v5)
            │
            ├── driver_manager.py            # Driver ↔ vehicle mappings (v5)
            ├── notification.py              # Telegram bot & NotificationManager (v5)
            ├── decision_log.py              # Decision history with categories
            │
            ├── web/
            │   ├── __init__.py
            │   ├── server.py                # HTTP server & REST API endpoints
            │   ├── template_engine.py       # Jinja2 template renderer
            │   ├── static/
            │   │   ├── style.css            # Dashboard styles
            │   │   ├── app.js               # Dashboard interactivity
            │   │   └── ...                  # Charts, icons
            │   └── templates/
            │       ├── dashboard.html       # Main UI
            │       └── docs.html            # In-app documentation
            │
            └── vehicles.yaml.example        # Template for vehicle config
            └── drivers.yaml.example         # Template for driver & Telegram config
```

## Directory Purposes

**evcc-smartload/rootfs/app/:**
- Purpose: Main Python application (Home Assistant add-on structure)
- Contains: All source code for optimization, control, and web interface
- Key files: main.py (entry), config.py (configuration), state.py (data model)

**optimizer/:**
- Purpose: Energy optimization algorithms
- Contains: HolisticOptimizer (Linear Programming), EventDetector
- Key files: `holistic.py` (greedy percentile-based scheduling)

**vehicles/:**
- Purpose: Multi-provider vehicle SoC abstraction
- Contains: VehicleManager, VehicleData model, 4 provider implementations
- Key files:
  - `manager.py` — Factory pattern for providers
  - `base.py` — VehicleData interface

**web/:**
- Purpose: REST API and real-time dashboard
- Contains: HTTP handler, templates, static assets
- Key files:
  - `server.py` — All GET/POST endpoints
  - `templates/dashboard.html` — Main UI
  - `static/` — CSS, JavaScript, charts

## Key File Locations

**Entry Points:**
- `evcc-smartload/rootfs/app/main.py` — Application startup, main decision loop (infinite)

**Configuration:**
- `evcc-smartload/rootfs/app/config.py` — Config defaults & loader (loads from /data/options.json)
- `evcc-smartload/rootfs/app/vehicles.yaml.example` — Vehicle provider template
- `evcc-smartload/rootfs/app/drivers.yaml.example` — Driver & Telegram template

**Core Logic:**
- `evcc-smartload/rootfs/app/state.py` — SystemState & Action models, percentile computation
- `evcc-smartload/rootfs/app/optimizer/holistic.py` — Linear Programming optimizer
- `evcc-smartload/rootfs/app/rl_agent.py` — Q-table DQN with 31-d state, 35 actions
- `evcc-smartload/rootfs/app/comparator.py` — LP vs RL comparison & reward function

**Integration:**
- `evcc-smartload/rootfs/app/evcc_client.py` — evcc REST API wrapper
- `evcc-smartload/rootfs/app/influxdb_client.py` — Time-series data persistence
- `evcc-smartload/rootfs/app/vehicle_monitor.py` — Vehicle polling scheduler

**v5 Features:**
- `evcc-smartload/rootfs/app/charge_sequencer.py` — Multi-EV scheduling
- `evcc-smartload/rootfs/app/driver_manager.py` — Driver config loader
- `evcc-smartload/rootfs/app/notification.py` — Telegram bot & notifications

**Testing & Visibility:**
- `evcc-smartload/rootfs/app/decision_log.py` — Decision history (for dashboard)
- `evcc-smartload/rootfs/app/web/server.py` — REST API (GET/POST endpoints)

## Naming Conventions

**Files:**
- `*_manager.py` — Factory/coordination classes (VehicleManager, DriverManager)
- `*_client.py` — External API wrappers (EvccClient, InfluxDBClient)
- `*_provider.py` — Pluggable implementations (KiaProvider, RenaultProvider)
- `*_monitor.py` — Background polling/tracking (VehicleMonitor)
- `*_sequencer.py` — Scheduling logic (ChargeSequencer)
- `*_agent.py` — Machine learning (RL_Agent)
- `*_log.py` — History/audit (DecisionLog)

**Directories:**
- `optimizer/` — Optimization algorithms
- `vehicles/` — Vehicle provider implementations
- `web/` — Web interface and REST API

**Python modules:**
- CamelCase for classes: SystemState, VehicleData, HolisticOptimizer, DQNAgent
- snake_case for functions: compute_price_percentiles(), optimize(), poll_vehicle()
- UPPER_CASE for constants/paths: STALE_THRESHOLD_MINUTES, RL_MODEL_PATH, OPTIONS_PATH

**Config keys (config.py):**
- snake_case: battery_capacity_kwh, ev_target_soc, decision_interval_minutes
- Grouped by category: battery_*, ev_*, rl_*, vehicle_*

## Where to Add New Code

**New Feature (e.g., battery discharge optimization):**
- Primary code: `evcc-smartload/rootfs/app/optimizer/holistic.py` (extend HolisticOptimizer.optimize())
- Control translation: `evcc-smartload/rootfs/app/controller.py` (extend Controller.apply())
- Config: `evcc-smartload/rootfs/app/config.py` (add @dataclass fields)
- Tests: Create `test_optimizer_discharge.py` in same directory (if testing added)

**New Vehicle Provider:**
- Implementation: `evcc-smartload/rootfs/app/vehicles/mycar_provider.py` (inherit from base)
- Registration: `evcc-smartload/rootfs/app/vehicles/manager.py` (_make_provider factory)
- Config template: Update `vehicles.yaml.example` with new provider type
- Example: See KiaProvider at `evcc-smartload/rootfs/app/vehicles/kia_provider.py` (API polling pattern)

**New API Endpoint:**
- Handler: `evcc-smartload/rootfs/app/web/server.py` (add to do_GET or do_POST)
- Data preparation: Extract logic to WebServer methods (e.g., _api_status())
- Path: Use REST pattern (e.g., `/devices/{id}/action`)

**New Background Service:**
- Module: `evcc-smartload/rootfs/app/myservice.py` with a start() method
- Initialization: main.py → instantiate and call .start()
- Threading: Use threading.Thread(target=..., daemon=True).start()
- Logging: Use logging_util.log() for all output

**Utilities:**
- Shared helpers: `evcc-smartload/rootfs/app/[module_name].py` (new file if > 200 lines)
- Keep close to callers: Avoid deep utility directories

## Special Directories

**/.planning/codebase/:**
- Purpose: GSD codebase analysis documents
- Generated: Yes (by `/gsd:map-codebase` command)
- Committed: Yes (tracked in git)
- Contains: ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, CONCERNS.md, INTEGRATIONS.md, STACK.md

**/data/ (runtime):**
- Purpose: Persistent application state (Home Assistant add-on mount)
- Generated: Yes (by application)
- Committed: No (local state, never tracked)
- Contains:
  - `/data/options.json` — Configuration from Home Assistant UI
  - `/data/smartprice_rl_model.json` — Q-table snapshot
  - `/data/smartprice_rl_memory.json` — Replay buffer
  - `/data/smartprice_comparison.json` — LP vs RL cost history
  - `/data/smartprice_manual_soc.json` — Manual SoC overrides
  - `/data/smartprice_device_control.db` — Device mode switching history (SQLite)

**/config/ (runtime):**
- Purpose: User configuration (Home Assistant /config mount)
- Generated: No (user-provided)
- Committed: No (user data)
- Contains:
  - `/config/vehicles.yaml` — Vehicle provider configurations
  - `/config/drivers.yaml` — Driver ↔ vehicle mappings and Telegram config

**web/static/:**
- Purpose: Static web assets
- Generated: No (authored)
- Committed: Yes
- Contains: CSS, JavaScript, SVG charts, images

**web/templates/:**
- Purpose: Jinja2 HTML templates
- Generated: No (authored)
- Committed: Yes
- Contains: dashboard.html (main UI), docs.html (in-app documentation)

## Import Patterns

**Layered imports (clean dependency graph):**

- **Infrastructure layer** (`evcc_client.py`, `influxdb_client.py`, `config.py`):
  - Imports: stdlib, third-party (requests, yaml, numpy)
  - No imports from: optimizer, vehicles, controller

- **Data layer** (`state.py`, `vehicles/base.py`):
  - Imports: infrastructure, stdlib
  - No imports from: optimization, control

- **Provider layer** (`vehicles/*_provider.py`):
  - Imports: base.py, logging_util.py, external APIs
  - No cross-imports between providers

- **Optimization layer** (`optimizer/`, `rl_agent.py`, `comparator.py`):
  - Imports: state.py, config.py, logging_util.py
  - No imports from: controller, web, vehicles

- **Control layer** (`controller.py`, `charge_sequencer.py`):
  - Imports: state.py, evcc_client.py, config.py
  - No imports from: optimizer (uses output only)

- **Coordination layer** (`main.py`, `vehicle_monitor.py`, `collector.py`):
  - Imports: All layers (final assembly point)

- **Web layer** (`web/server.py`):
  - Imports: state.py, web/template_engine.py, all analysis modules (read-only)
  - No imports from: controller

## File Path Examples for Common Tasks

**Add new price-aware decision in LP:**
- File: `evcc-smartload/rootfs/app/optimizer/holistic.py`
- Method: `HolisticOptimizer.optimize()`
- Pattern: Use state.price_percentiles.get(20, default) for P20 threshold

**Add new Telegram notification:**
- File: `evcc-smartload/rootfs/app/notification.py`
- Method: Add NotificationManager.send_X() function
- Template: See send_charge_inquiry() around line 100

**Add vehicle SoC display to dashboard:**
- Files:
  - Backend: `evcc-smartload/rootfs/app/web/server.py` → _api_vehicles() method
  - Frontend: `evcc-smartload/rootfs/app/web/templates/dashboard.html`
  - Styles: `evcc-smartload/rootfs/app/web/static/style.css`

**Save new state to InfluxDB:**
- File: `evcc-smartload/rootfs/app/influxdb_client.py`
- Method: Add parameter to write_state() or create write_X() method
- Pattern: Measurement name, fields dict, tags dict

**Add configuration option:**
1. `evcc-smartload/rootfs/app/config.py` — Add @dataclass field with default
2. `evcc-smartload/rootfs/app/main.py` — Use cfg.new_option
3. Load from `/data/options.json` automatically via load_config()

---

*Structure analysis: 2026-02-22*
