"""
Driver Manager — v5.0 NEW

Loads driver ↔ vehicle mapping and Telegram config from /config/drivers.yaml.
Mirrors the pattern of vehicle_manager / vehicles.yaml.

File is optional: without it, notifications are disabled and everything
else works exactly as in v4.
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from config import DRIVERS_YAML_PATH, DRIVERS_EXAMPLE_PATH
from logging_util import log


@dataclass
class Driver:
    name: str
    vehicles: List[str]                  # evcc_name values from vehicles.yaml
    telegram_chat_id: Optional[int] = None


class DriverManager:
    """Parses drivers.yaml and provides driver ↔ vehicle lookups."""

    def __init__(self):
        self.drivers: List[Driver] = []
        self.telegram_bot_token: str = ""
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self):
        path = Path(DRIVERS_YAML_PATH)
        if not path.exists():
            example = Path(DRIVERS_EXAMPLE_PATH)
            if example.exists():
                shutil.copy2(example, path)
                log("info", f"Created {DRIVERS_YAML_PATH} from example")
            else:
                log("info", "No drivers.yaml found — notifications disabled")
                return

        try:
            import yaml
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}

            self.telegram_bot_token = data.get("telegram_bot_token", "")

            for d in data.get("drivers", []):
                driver = Driver(
                    name=d["name"],
                    vehicles=[v.strip() for v in d.get("vehicles", [])],
                    telegram_chat_id=d.get("telegram_chat_id"),
                )
                self.drivers.append(driver)

            if self.drivers:
                log("info", f"Loaded {len(self.drivers)} driver(s) from drivers.yaml")
                for d in self.drivers:
                    tg = "✓ Telegram" if d.telegram_chat_id else "✗ kein Telegram"
                    log("info", f"  → {d.name}: {d.vehicles} ({tg})")

            if self.telegram_bot_token:
                log("info", "Telegram Bot Token konfiguriert")
            else:
                log("info", "Kein Telegram Bot Token → notifications disabled")

        except Exception as e:
            log("error", f"Failed to load drivers.yaml: {e}")

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_driver(self, vehicle_name: str) -> Optional[Driver]:
        """Find driver for a vehicle (case-insensitive)."""
        vl = vehicle_name.lower()
        for d in self.drivers:
            if vl in [v.lower() for v in d.vehicles]:
                return d
        return None

    def get_driver_by_chat_id(self, chat_id: int) -> Optional[Driver]:
        for d in self.drivers:
            if d.telegram_chat_id == chat_id:
                return d
        return None

    def get_all_drivers(self) -> List[Driver]:
        return list(self.drivers)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    def to_api_list(self) -> list:
        """Return driver list for /drivers API (no sensitive data)."""
        return [
            {
                "name": d.name,
                "vehicles": d.vehicles,
                "telegram_configured": bool(d.telegram_chat_id),
            }
            for d in self.drivers
        ]

    def to_api_dict(self) -> dict:
        """Return driver info for /status API (no sensitive data)."""
        return {
            "drivers": [
                {
                    "name": d.name,
                    "vehicles": d.vehicles,
                    "has_telegram": bool(d.telegram_chat_id),
                }
                for d in self.drivers
            ],
            "telegram_enabled": self.telegram_enabled,
        }
