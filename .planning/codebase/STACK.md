# Technology Stack

**Analysis Date:** 2026-02-22

## Languages

**Primary:**
- Python 3.13 - All application logic, ML/RL components, API clients, and web server
- YAML - Configuration files for vehicles, drivers, and Home Assistant integration
- HTML/JavaScript - Web dashboard frontend (minimal, template-based)

**Secondary:**
- Bash - Docker entrypoint and container initialization

## Runtime

**Environment:**
- Docker container running Alpine Linux 3.21 (ghcr.io/home-assistant/aarch64-base-python:3.13-alpine3.21)
- Supports architectures: aarch64, amd64, armv7

**Package Manager:**
- pip3 - Python dependency installation
- apk - Alpine Linux package manager

## Frameworks

**Core:**
- Home Assistant Add-on Framework - Container integration with Home Assistant
  - YAML config schema for add-on configuration
  - Native integration with Home Assistant's options.json

**Web API:**
- Python http.server (BaseHTTPRequestHandler, HTTPServer) - HTTP API server
- Custom template engine (Jinja2-like) - Dashboard HTML rendering

**Machine Learning:**
- NumPy 1.x - Numerical arrays, percentile computation, RL Q-table operations
- Custom DQN (Deep Q-Network) - Experience replay, epsilon-greedy exploration, imitation learning

## Key Dependencies

**Critical:**
- `pyyaml` - YAML parsing for vehicles.yaml and drivers.yaml configuration
- `requests` - HTTP client for evcc REST API, InfluxDB queries, Telegram Bot API
- `numpy` - Array operations for price percentile calculations and RL Q-table
- `hyundai-kia-connect-api` - KIA/Hyundai vehicle SoC polling via cloud API
- `renault-api` - Renault/Dacia vehicle SoC polling via cloud API
- `aiohttp` - Async HTTP client (used by renault-api)

**Infrastructure:**
- `urllib3` - HTTP connection pooling, self-signed certificate handling for local InfluxDB

## Configuration

**Environment:**
- Home Assistant `/data/options.json` - Addon configuration (EVCC URL, InfluxDB credentials, price thresholds, etc.)
- `/config/vehicles.yaml` - Vehicle provider configurations (KIA, Renault, EVCC, custom APIs)
- `/config/drivers.yaml` - Driver profiles and Telegram chat IDs for notifications
- `/data/*.json` - Persistent state storage (RL model, comparison logs, manual SoC overrides)

**Secrets Management:**
- `.env` files are NOT used
- Configuration secrets passed via Home Assistant options schema with `password?` and `password` types
- Environment variables are **not** used directly (all config flows through Home Assistant's options.json)

**Build:**
- `Dockerfile` - Multi-architecture Alpine container definition
- `build.yaml` - Home Assistant add-on builder configuration specifying base images per architecture

## Platform Requirements

**Development:**
- Docker environment capable of building Alpine Linux images
- Python 3.13 with pip
- Home Assistant development environment (optional, for testing in actual HA instance)

**Production:**
- Home Assistant OS or equivalent Docker-enabled Linux host
- Network connectivity to:
  - EVCC instance (HTTP REST API)
  - InfluxDB instance (optional, for historical data storage)
  - Telegram Bot API (optional, for notifications)
  - KIA/Hyundai cloud API (if using KIA vehicles)
  - Renault cloud API (if using Renault/Dacia vehicles)

## Data Persistence

**Paths (within container):**
- `/data/options.json` - Home Assistant add-on options
- `/data/smartprice_state.json` - Manual SoC store
- `/data/smartprice_rl_model.json` - RL agent Q-table and epsilon state
- `/data/smartprice_rl_memory.json` - RL experience replay buffer
- `/data/smartprice_comparison.json` - Historical LP vs RL comparisons
- `/data/smartprice_manual_soc.json` - User-provided SoC overrides
- `/data/smartprice_device_control.db` - SQLite database tracking per-device RL/LP mode selection

**Persistence:**
- Docker volume mapping required: `/data` → Home Assistant persistent storage
- `/config` directory for user-editable YAML configs (vehicles.yaml, drivers.yaml)

---

*Stack analysis: 2026-02-22*
