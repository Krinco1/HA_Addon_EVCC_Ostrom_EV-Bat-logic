"""
Configuration management for EVCC-Smartload.

Loads configuration from Home Assistant's options.json and provides typed defaults.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List

from logging_util import log

OPTIONS_PATH = "/data/options.json"

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

    # --- Vehicle providers ---
    vehicle_poll_interval_minutes: int = 15
    vehicle_providers: List[Dict] = field(default_factory=list)

    # --- Web server ---
    api_port: int = 8099


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

        # Parse vehicle_providers if given as JSON string
        if isinstance(cfg.vehicle_providers, str):
            try:
                cfg.vehicle_providers = json.loads(cfg.vehicle_providers)
            except (json.JSONDecodeError, TypeError):
                cfg.vehicle_providers = []

        return cfg
    except Exception as e:
        log("warning", f"Could not load config: {e}, using defaults")
        return Config()
