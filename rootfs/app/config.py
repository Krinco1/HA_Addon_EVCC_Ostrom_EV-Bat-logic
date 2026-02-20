"""
Configuration management for EVCC-Smartload.

Loads configuration from Home Assistant's options.json and provides typed defaults.
Vehicle providers are loaded from a separate /config/vehicles.yaml file.
Driver / Telegram config from /config/drivers.yaml.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from logging_util import log

OPTIONS_PATH = "/data/options.json"
VEHICLES_YAML_PATH = "/config/vehicles.yaml"
VEHICLES_EXAMPLE_PATH = "/app/vehicles.yaml.example"
DRIVERS_YAML_PATH = "/config/drivers.yaml"
DRIVERS_EXAMPLE_PATH = "/app/drivers.yaml.example"

# Persistent data paths
STATE_PATH = "/data/smartprice_state.json"
RL_MODEL_PATH = "/data/smartprice_rl_model.json"
RL_MEMORY_PATH = "/data/smartprice_rl_memory.json"
COMPARISON_LOG_PATH = "/data/smartprice_comparison.json"
MANUAL_SOC_PATH = "/data/smartprice_manual_soc.json"
DEVICE_CONTROL_DB_PATH = "/data/smartprice_device_control.db"


@dataclass
class Config:
    """All configuration options with sensible defaults."""

    # --- evcc connection ---
    evcc_url: str = "http://192.168.1.66:7070"
    evcc_password: str = ""

    # --- InfluxDB ---
    influxdb_host: str = "192.168.1.67"
    influxdb_port: int = 8086
    influxdb_database: str = "smartprice"
    influxdb_username: str = "smartprice"
    influxdb_password: str = "smartprice"

    # --- Home battery ---
    battery_capacity_kwh: float = 33.1
    battery_charge_power_kw: float = 4.3
    battery_max_price_ct: float = 25.0
    battery_min_soc: int = 10
    battery_max_soc: int = 90
    battery_price_corridor_ct: float = 0.8

    # --- Battery efficiency (for battery-to-EV calculation) ---
    battery_charge_efficiency: float = 0.92
    battery_discharge_efficiency: float = 0.92
    battery_to_ev_min_profit_ct: float = 3.0
    battery_to_ev_dynamic_limit: bool = True
    battery_to_ev_floor_soc: int = 20

    # --- EV charging ---
    ev_max_price_ct: float = 30.0
    ev_target_soc: int = 80
    ev_default_energy_kwh: float = 30.0
    ev_price_corridor_ct: float = 1.0
    ev_charge_deadline_hour: int = 6

    # --- Feed-in ---
    feed_in_tariff_ct: float = 7.0

    # --- Scheduling ---
    decision_interval_minutes: int = 15
    data_collect_interval_sec: int = 60

    # --- Reinforcement Learning ---
    rl_enabled: bool = True
    rl_learning_rate: float = 0.001
    rl_discount_factor: float = 0.95
    rl_epsilon_start: float = 0.3
    rl_epsilon_min: float = 0.05
    rl_epsilon_decay: float = 0.995
    rl_batch_size: int = 32
    rl_memory_size: int = 10000
    rl_ready_threshold: float = 0.8
    rl_ready_min_comparisons: int = 200
    rl_auto_switch: bool = True
    rl_fallback_threshold: float = 0.7

    # --- Vehicle providers (loaded from vehicles.yaml) ---
    vehicle_poll_interval_minutes: int = 60
    vehicle_providers: List[Dict] = field(default_factory=list)

    # --- v5: Quiet Hours (no EV plug-switching during night) ---
    quiet_hours_enabled: bool = True
    quiet_hours_start: int = 21   # 21:00
    quiet_hours_end: int = 6      # 06:00

    # --- v5: Charge Sequencer ---
    sequencer_enabled: bool = True
    sequencer_default_charge_power_kw: float = 11.0

    # --- Web server ---
    api_port: int = 8099


def _load_vehicle_providers() -> List[Dict]:
    """Load vehicle provider configs from /config/vehicles.yaml."""
    path = Path(VEHICLES_YAML_PATH)
    if not path.exists():
        example = Path(VEHICLES_EXAMPLE_PATH)
        if example.exists():
            import shutil
            shutil.copy2(example, path)
            log("info", f"Created {VEHICLES_YAML_PATH} from example template")
        else:
            log("info", f"No {VEHICLES_YAML_PATH} found — no direct vehicle APIs configured")
            return []

    try:
        import yaml
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        raw_vehicles = data.get("vehicles", []) or []

        providers = []
        for v in raw_vehicles:
            mapped = dict(v)
            if "name" in mapped and "evcc_name" not in mapped:
                mapped["evcc_name"] = mapped["name"]
            if "template" in mapped and "type" not in mapped:
                mapped["type"] = mapped["template"]
            elif "type" in mapped and mapped["type"] == "template" and "template" in mapped:
                mapped["type"] = mapped["template"]
            if "capacity" in mapped and "capacity_kwh" not in mapped:
                mapped["capacity_kwh"] = mapped["capacity"]
            providers.append(mapped)

        if providers:
            log("info", f"Loaded {len(providers)} vehicle(s) from {VEHICLES_YAML_PATH}")
            for p in providers:
                name = p.get("evcc_name", p.get("name", "?"))
                ptype = p.get("type", "unknown")
                cap = p.get("capacity_kwh", p.get("capacity", "?"))
                log("info", f"  → {name} ({ptype}, {cap} kWh)")
        return providers
    except Exception as e:
        log("error", f"Failed to load {VEHICLES_YAML_PATH}: {e}")
        return []


def load_config() -> Config:
    """Load configuration from Home Assistant options.json, falling back to defaults."""
    try:
        with open(OPTIONS_PATH, "r") as f:
            raw = json.load(f)
        log("debug", f"Loaded options: {list(raw.keys())}")

        cfg = Config()
        for k, v in raw.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

        cfg.vehicle_providers = _load_vehicle_providers()
        return cfg
    except Exception as e:
        log("warning", f"Could not load config: {e}, using defaults")
        cfg = Config()
        cfg.vehicle_providers = _load_vehicle_providers()
        return cfg
