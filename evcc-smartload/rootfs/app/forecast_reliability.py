"""
ForecastReliabilityTracker — Phase 8: Per-source rolling forecast MAE with confidence factors

Tracks rolling mean absolute error (MAE) for three forecast sources:
  - "pv"          : PV power forecast (in kW — caller must convert from W if needed)
  - "consumption" : Load/consumption forecast (in W)
  - "price"       : Electricity price forecast (in EUR/kWh)

Unit requirements:
    PV values MUST be in kW. The PVForecaster returns kW; state.pv_power is in W.
    Callers are responsible for converting: pv_kw = state.pv_power / 1000
    before calling update("pv", actual_kw, forecast_kw).

Sign convention (plan error, for reference):
    plan_error = actual_cost_eur - plan_cost_eur
    This module does NOT use plan_error; it uses abs(actual - forecast) per source.

Confidence formula:
    mae = mean(rolling absolute errors)
    confidence = max(0.0, 1.0 - min(mae / REFERENCE_SCALE[source], 1.0))
    Returns 1.0 (fully reliable) when fewer than 5 samples are recorded.

Thread safety: all state mutations guarded by _lock. File I/O happens outside
the lock to avoid blocking SSE reads in the web thread (same pattern as
DynamicBufferCalc and SeasonalLearner).

Persistence: atomic JSON write to /data/smartprice_forecast_reliability.json.
"""

import json
import os
import threading
from collections import deque
from typing import Dict, List

RELIABILITY_MODEL_PATH = "/data/smartprice_forecast_reliability.json"
RELIABILITY_MODEL_VERSION = 1

# Number of rolling error samples to retain per source (~12.5 hours at 15-min cycles)
WINDOW_SIZE = 50

# Minimum number of errors before trust declines from the default of 1.0
_MIN_SAMPLES_FOR_CONFIDENCE = 5

# Persist every N updates to limit unnecessary disk I/O
_PERSIST_INTERVAL = 10

# Reference scales for normalizing MAE to [0, 1].
# Each scale represents what we consider a "large" (confidence-destroying) error.
#
# PV: 5.0 kW  — caller must pass values in kW (NOT W).
# Consumption: 2000.0 W  — stays in W.
# Price: 0.10 EUR/kWh  — 10 ct/kWh is a large price error.
REFERENCE_SCALE: Dict[str, float] = {
    "pv": 5.0,             # kW  — caller converts state.pv_power (W) to kW
    "consumption": 2000.0, # W
    "price": 0.10,         # EUR/kWh
}

_KNOWN_SOURCES = frozenset(REFERENCE_SCALE.keys())


class ForecastReliabilityTracker:
    """
    Tracks rolling forecast MAE for PV, consumption, and price sources.

    Confidence interpretation:
        1.0 = perfect (or not enough data yet)
        0.0 = errors at or above the reference scale (very unreliable)

    Usage:
        tracker = ForecastReliabilityTracker()
        tracker.update("pv", actual_kw, forecast_kw)
        tracker.update("consumption", actual_w, forecast_w)
        tracker.update("price", actual_eur_kwh, forecast_eur_kwh)

        pv_conf = tracker.get_confidence("pv")    # float in [0.0, 1.0]
        all_conf = tracker.get_all_confidences()  # {"pv": ..., "consumption": ..., "price": ...}
    """

    def __init__(self) -> None:
        # One deque per source; bounded at WINDOW_SIZE
        self._windows: Dict[str, deque] = {
            source: deque(maxlen=WINDOW_SIZE) for source in _KNOWN_SOURCES
        }
        self._lock = threading.Lock()
        self._update_count = 0
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, source: str, actual: float, forecast: float) -> None:
        """
        Record one forecast error observation for the given source.

        Args:
            source:   One of "pv", "consumption", "price".
            actual:   Observed value (units must match REFERENCE_SCALE[source]).
            forecast: Forecasted value (same units as actual).

        Unit requirements:
            - "pv": both actual and forecast must be in kW.
              (caller: pv_kw = state.pv_power / 1000 before calling)
            - "consumption": both in W.
            - "price": both in EUR/kWh.

        Raises:
            ValueError: if source is not one of the known sources.

        Persists every _PERSIST_INTERVAL updates (file I/O outside lock).
        """
        if source not in _KNOWN_SOURCES:
            raise ValueError(
                f"Unknown source '{source}'. Must be one of: {sorted(_KNOWN_SOURCES)}"
            )

        abs_error = abs(actual - forecast)

        with self._lock:
            self._windows[source].append(abs_error)
            self._update_count += 1
            should_persist = (self._update_count % _PERSIST_INTERVAL == 0)
            model_snapshot = self._build_model_dict() if should_persist else None

        if model_snapshot is not None:
            self._write_model(model_snapshot)

    def get_confidence(self, source: str) -> float:
        """
        Return the confidence factor for the given source in [0.0, 1.0].

        Returns 1.0 (fully reliable) when fewer than _MIN_SAMPLES_FOR_CONFIDENCE
        errors have been recorded — assume reliable until proven otherwise.

        Args:
            source: One of "pv", "consumption", "price".

        Returns:
            float in [0.0, 1.0].

        Raises:
            ValueError: if source is not one of the known sources.
        """
        if source not in _KNOWN_SOURCES:
            raise ValueError(
                f"Unknown source '{source}'. Must be one of: {sorted(_KNOWN_SOURCES)}"
            )

        with self._lock:
            errors = list(self._windows[source])

        if len(errors) < _MIN_SAMPLES_FOR_CONFIDENCE:
            return 1.0  # Not enough data — assume reliable

        mae = sum(errors) / len(errors)
        scale = REFERENCE_SCALE[source]
        confidence = max(0.0, 1.0 - min(mae / scale, 1.0))
        return confidence

    def get_all_confidences(self) -> Dict[str, float]:
        """
        Return confidence factors for all three sources.

        Returns:
            {"pv": float, "consumption": float, "price": float}
            All values in [0.0, 1.0].
        """
        return {source: self.get_confidence(source) for source in sorted(_KNOWN_SOURCES)}

    def save(self) -> None:
        """Persist current state to disk immediately (bypasses _PERSIST_INTERVAL)."""
        with self._lock:
            model_snapshot = self._build_model_dict()
        self._write_model(model_snapshot)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _build_model_dict(self) -> dict:
        """Build JSON-serializable model dict. Caller must hold self._lock."""
        return {
            "version": RELIABILITY_MODEL_VERSION,
            "windows": {
                source: list(window)
                for source, window in self._windows.items()
            },
        }

    def _write_model(self, model: dict) -> None:
        """Atomic write to RELIABILITY_MODEL_PATH using tmp + os.replace pattern."""
        tmp = RELIABILITY_MODEL_PATH + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(model, f, indent=2)
            os.replace(tmp, RELIABILITY_MODEL_PATH)
        except Exception:
            pass

    def _load(self) -> None:
        """
        Load persisted state from JSON. Gracefully ignores missing or corrupt files.

        Version check: only version 1 is supported currently. Unknown versions
        fall back to empty state to allow safe schema evolution.

        Deques are restored with the persisted errors (up to WINDOW_SIZE entries).
        """
        try:
            with open(RELIABILITY_MODEL_PATH, "r") as f:
                model = json.load(f)

            if model.get("version") != RELIABILITY_MODEL_VERSION:
                return  # Unknown version — start fresh

            windows = model.get("windows", {})
            if isinstance(windows, dict):
                for source, errors in windows.items():
                    if source in _KNOWN_SOURCES and isinstance(errors, list):
                        # Extend deque with persisted errors; maxlen enforces window
                        for err in errors:
                            try:
                                self._windows[source].append(float(err))
                            except (TypeError, ValueError):
                                pass

        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
