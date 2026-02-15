"""Centralized logging for EVCC-Smartload."""

from datetime import datetime


def log(level: str, msg: str) -> None:
    """Thread-safe logging to stdout (captured by Home Assistant)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level.upper():5}] {msg}", flush=True)
