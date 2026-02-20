"""Simple logging utility for EVCC-Smartload."""

import logging
import sys

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_logger = logging.getLogger("smartload")


def log(level: str, msg: str):
    getattr(_logger, level, _logger.info)(msg)
