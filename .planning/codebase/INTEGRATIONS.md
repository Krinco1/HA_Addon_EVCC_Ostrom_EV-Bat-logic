# External Integrations

**Analysis Date:** 2026-02-22

## APIs & External Services

**Energy Management:**
- EVCC (Hybrid solar inverter manager) - Central system for battery/EV control and tariff data
  - SDK/Client: `EvccClient` in `rootfs/app/evcc_client.py`
  - Auth: Password-based (optional, via config.evcc_password)
  - Endpoints: REST API at config.evcc_url
  - Methods: GET /api/state, GET /api/tariff/grid, GET /api/tariff/solar, POST /api/smart*limit, POST /api/loadpoints/{id}/*, POST /api/battery*

**Vehicle Providers:**
- KIA/Hyundai/Genesis Cloud API - Battery SoC polling
  - SDK: `hyundai-kia-connect-api` (Python package)
  - Implementation: `KiaProvider` in `rootfs/app/vehicles/kia_provider.py`
  - Auth: Username, password, optional PIN (stored in /config/vehicles.yaml)
  - Scope: Supports KIA, Hyundai, Genesis brands; multiple regions (Europe, Canada, USA)

- Renault/Dacia Cloud API - Battery SoC polling
  - SDK: `renault-api` (Python package with aiohttp backend)
  - Implementation: `RenaultProvider` in `rootfs/app/vehicles/renault_provider.py`
  - Auth: Username, password (stored in /config/vehicles.yaml)
  - Scope: Async polling via Renault cloud services

- EVCC Native - Vehicle data from EVCC's built-in vehicle providers
  - SDK: Reuses `EvccClient`
  - Implementation: `EvccProvider` in `rootfs/app/vehicles/evcc_provider.py`
  - Auth: Same as EVCC REST API (password-based)
  - Data flow: Queries /api/state for vehicle loadpoint data

- Custom HTTP API - User-defined vehicle SoC endpoints
  - SDK: `requests` library
  - Implementation: `CustomProvider` in `rootfs/app/vehicles/custom_provider.py`
  - Auth: Custom via URL parameters or headers (user-defined)
  - Polling: Periodic HTTP GET to custom endpoint

**Messaging:**
- Telegram Bot API - Driver notifications and interactive charge requests
  - SDK: Direct HTTPS API calls via `requests` library
  - Implementation: `TelegramBot` in `rootfs/app/notification.py`
  - Auth: Bot token (stored in /config/drivers.yaml)
  - Methods: Long-polling via getUpdates, sendMessage with inline keyboards, answerCallbackQuery
  - Interaction: Drivers respond with inline buttons to approve charge requests

## Data Storage

**Databases:**
- InfluxDB 1.x (Optional) - Time-series metrics storage
  - Connection: HTTP (config.influxdb_host:port, with optional SSL)
  - Client: Custom HTTP client in `InfluxDBClient` (`rootfs/app/influxdb_client.py`)
  - Auth: Basic auth (config.influxdb_username, config.influxdb_password)
  - Database: Configurable (default: "smartload")
  - Metrics written: Smartprice measurements (battery_soc, battery_power, pv_power, home_power, grid_power, price_ct, percentiles)
  - Query usage: Historical data bootstrap for RL agent (168 hours of hourly aggregates)

**Local File Storage:**
- JSON files in `/data/` directory:
  - `smartprice_state.json` - Manual SoC store for all vehicles
  - `smartprice_rl_model.json` - RL agent Q-table and epsilon decay state
  - `smartprice_rl_memory.json` - Experience replay buffer (max 10,000 experiences)
  - `smartprice_comparison.json` - LP vs RL reward tracking per device
  - `smartprice_manual_soc.json` - User-provided battery/EV SoC overrides

- SQLite Database:
  - `smartprice_device_control.db` - Persistent device mode selection (RL or LP mode per device)
  - Implementation: `RLDeviceController` in `rootfs/app/comparator.py`

**Configuration Files:**
- YAML in `/config/`:
  - `vehicles.yaml` - Vehicle provider definitions (credentials, capacity, charge power)
  - `drivers.yaml` - Driver profiles with Telegram chat IDs and vehicle assignments

## Authentication & Identity

**Auth Provider:**
- No centralized identity service
- Per-service authentication:
  - EVCC: Optional password-based login (POST /api/auth/login)
  - KIA/Hyundai: Cloud account credentials (email/password + PIN)
  - Renault: Cloud account credentials (email/password)
  - Telegram: Bot token (long string, stored in drivers.yaml)
  - InfluxDB: Basic auth (username/password)

**Secrets:**
- All stored in Home Assistant protected config/options:
  - `evcc_password` (optional)
  - `influxdb_username`, `influxdb_password`
  - Telegram bot token (in drivers.yaml with restricted file permissions)
  - Vehicle provider credentials in vehicles.yaml

## Monitoring & Observability

**Metrics Export:**
- InfluxDB Write (optional): Custom measurements with price percentiles, SoC, power values
- Dashboard: SVG-rendered price charts and decision logs served via HTTP

**Error Tracking:**
- Not integrated - All errors logged to stdout via `logging_util.log()`
- Application errors: Logged with level, message, and traceback
- API failures: Logged with HTTP status codes and retry behavior

**Logs:**
- Stdout/stderr only (Docker container logs)
- Log levels: info, warning, error, debug
- Structured logging: `log("level", "message")` utility in `rootfs/app/logging_util.py`

**Decision Audit:**
- In-memory decision log: `DecisionLog` in `rootfs/app/decision_log.py` (max 100 entries)
- Fields: Timestamp, state snapshots, LP action, RL action, reward signals, percentile context
- API endpoint: GET /decisions → JSON list of recent decisions

## CI/CD & Deployment

**Hosting:**
- Home Assistant Add-on system (custom add-on repository)
- GitHub repository: https://github.com/Krinco1/HA_Addon_EVCC-Smartload
- Installation: Via Home Assistant Add-on Store UI with custom repository URL

**CI Pipeline:**
- Not detected - Manual testing and release workflow

**Build Process:**
- Docker multi-architecture builds (aarch64, amd64, armv7)
- Alpine Linux base with Python 3.13
- pip dependencies installed during build (break-system-packages flag used)
- No dependency lockfile (requirements.txt not used; hardcoded in Dockerfile)

## Environment Configuration

**Required env vars:**
- None - All configuration flows through Home Assistant options.json and YAML files

**Config sources (precedence):**
1. Home Assistant `/data/options.json` - Primary configuration
2. `/config/vehicles.yaml` - Vehicle provider definitions
3. `/config/drivers.yaml` - Driver and Telegram bot configuration
4. Built-in defaults in `config.py` - Fallback values

**Critical configuration required:**
- `evcc_url` - HTTP URL of EVCC instance (e.g., http://192.168.1.66:7070)
- `battery_capacity_kwh` - Home battery capacity for calculations
- `ev_max_price_ct` - Price threshold for EV charging (centc/kWh)
- `battery_max_price_ct` - Price threshold for battery charging
- Vehicle definitions in vehicles.yaml (at least one provider) for SoC polling

**Optional configuration:**
- `influxdb_*` - InfluxDB connection (if omitted, metrics not persisted)
- `evcc_password` - If EVCC requires authentication
- Telegram bot token in drivers.yaml (if notifications desired)
- RL parameters (learning_rate, epsilon_decay, etc.)

## Webhooks & Callbacks

**Incoming:**
- Telegram callback_query - Driver button presses on notifications (long-polling, not webhooks)
- HTTP POST endpoints for vehicle SoC (custom provider only)
- No incoming webhooks from external services

**Outgoing:**
- EVCC API calls:
  - POST /api/batterygridchargelimit/{price} - Set battery charge limit
  - POST /api/smartcostlimit/{price} - Set EV charge limit
  - POST /api/batterymode/{mode} - Control battery (hold/charge/discharge)
  - POST /api/loadpoints/{id}/mode/{mode} - Control EV charging
  - POST /api/loadpoints/{id}/targetsoc/{soc} - Set EV target SoC

- InfluxDB HTTP writes:
  - POST /write - Time-series metric storage

- Telegram API calls:
  - GET /getUpdates - Long-polling for messages/callbacks
  - POST /sendMessage - Send charge inquiries with inline keyboards
  - POST /answerCallbackQuery - Acknowledge button presses

**Polling Patterns:**
- EVCC tariff grid/solar: Every decision cycle (config.decision_interval_minutes, default 15 min)
- Vehicle SoC: Every config.vehicle_poll_interval_minutes (default 60 min)
- Telegram updates: Continuous long-polling with 30-second timeout
- InfluxDB history: Only on startup (for RL bootstrap)

---

*Integration audit: 2026-02-22*
