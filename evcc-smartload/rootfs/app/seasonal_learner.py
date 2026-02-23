"""
SeasonalLearner — Phase 8: Seasonal plan error pattern learning

Accumulates plan errors (actual_cost - plan_cost) in a 48-cell lookup table
indexed by (season, time_period, is_weekend). Used to derive correction factors
that shift the LP planner's expectations toward historically observed behavior.

Sign convention:
    plan_error = actual_cost_eur - plan_cost_eur
    Positive  → plan was optimistic; actual charging was more expensive than planned.
    Negative  → plan was pessimistic; actual charging was cheaper than planned.

Cells with fewer than min_samples (default 10) return None from get_correction_factor()
to prevent low-confidence corrections from distorting the optimizer.

Thread safety: all state mutations guarded by _lock. File I/O happens outside
the lock to avoid blocking SSE reads in the web thread (same pattern as
DynamicBufferCalc).

Persistence: atomic JSON write to /data/smartprice_seasonal_model.json.
"""

import json
import os
import threading
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

SEASONAL_MODEL_PATH = "/data/smartprice_seasonal_model.json"
SEASONAL_MODEL_VERSION = 1

# Meteorological season mapping: month → season index
#   0 = Winter  (DJF: December, January, February)
#   1 = Spring  (MAM: March, April, May)
#   2 = Summer  (JJA: June, July, August)
#   3 = Autumn  (SON: September, October, November)
#
# NOTE: Naive (month-1)//3 maps December to season 3 (incorrect).
#       Explicit mapping is required.
MONTH_TO_SEASON: Dict[int, int] = {
    12: 0, 1: 0, 2: 0,   # Winter  (DJF)
    3: 1, 4: 1, 5: 1,    # Spring  (MAM)
    6: 2, 7: 2, 8: 2,    # Summer  (JJA)
    9: 3, 10: 3, 11: 3,  # Autumn  (SON)
}

# Persist every N updates to limit unnecessary disk I/O
_PERSIST_INTERVAL = 10


def _cell_key(season: int, time_period: int, is_weekend: int) -> str:
    """Return the canonical string key for a (season, time_period, is_weekend) triple."""
    return f"s{season}_t{time_period}_w{is_weekend}"


def _classify_time_period(hour: int) -> int:
    """
    Map hour-of-day (0-23) to time_period index (0-5).

        0 = 00:00–03:59
        1 = 04:00–07:59
        2 = 08:00–11:59
        3 = 12:00–15:59
        4 = 16:00–19:59
        5 = 20:00–23:59
    """
    return hour // 4


def _classify_dt(dt: datetime) -> Tuple[int, int, int]:
    """Return (season, time_period, is_weekend) for a given datetime."""
    season = MONTH_TO_SEASON[dt.month]
    time_period = _classify_time_period(dt.hour)
    is_weekend = 1 if dt.weekday() >= 5 else 0   # 5=Saturday, 6=Sunday
    return season, time_period, is_weekend


class SeasonalLearner:
    """
    Accumulates plan errors in a 48-cell lookup table indexed by
    (season[0-3], time_period[0-5], is_weekend[0-1]) = 4 × 6 × 2 = 48 cells.

    Each cell stores a running average of plan_error (EUR):
        plan_error = actual_cost_eur - plan_cost_eur

    Positive mean_error → correction pushes costs upward (plan was too cheap).
    Negative mean_error → correction pushes costs downward (plan was too expensive).

    Usage:
        learner = SeasonalLearner()
        learner.update(dt=datetime.now(timezone.utc), plan_error_eur=0.03)
        correction = learner.get_correction_factor(dt=datetime.now(timezone.utc))
        if correction is not None:
            adjusted_cost = plan_cost + correction
    """

    def __init__(self) -> None:
        self._cells: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._update_count = 0
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, dt: datetime, plan_error_eur: float) -> None:
        """
        Record one plan error observation for the cell corresponding to dt.

        Args:
            dt: Datetime of the plan execution (used to derive season/period/weekend).
            plan_error_eur: actual_cost_eur - plan_cost_eur. Positive means plan was
                            optimistic (actual was more expensive than planned).

        Persists every _PERSIST_INTERVAL updates (file I/O outside lock).
        """
        season, time_period, is_weekend = _classify_dt(dt)
        key = _cell_key(season, time_period, is_weekend)

        with self._lock:
            cell = self._cells.get(key)
            if cell is None:
                cell = {"sum_error": 0.0, "count": 0, "mean_error": 0.0}
                self._cells[key] = cell

            cell["sum_error"] += plan_error_eur
            cell["count"] += 1
            cell["mean_error"] = cell["sum_error"] / cell["count"]

            self._update_count += 1
            should_persist = (self._update_count % _PERSIST_INTERVAL == 0)
            # Serialize under lock; write after release
            model_snapshot = self._build_model_dict() if should_persist else None

        if model_snapshot is not None:
            self._write_model(model_snapshot)

    def get_correction_factor(
        self, dt: datetime, min_samples: int = 10
    ) -> Optional[float]:
        """
        Return the mean plan error for the cell corresponding to dt.

        Returns None if the cell has fewer than min_samples observations (low confidence).
        Callers should treat None as "no correction available".

        Args:
            dt: Datetime to look up.
            min_samples: Minimum number of samples required to trust the cell.

        Returns:
            mean_error_eur or None.
        """
        season, time_period, is_weekend = _classify_dt(dt)
        key = _cell_key(season, time_period, is_weekend)

        with self._lock:
            cell = self._cells.get(key)
            if cell is None or cell["count"] < min_samples:
                return None
            return cell["mean_error"]

    def get_cell(self, dt: datetime) -> Dict:
        """
        Return the cell dict for the context described by dt.

        Always returns a dict (may be empty/zero-count if no observations yet).
        Useful for dashboard display.
        """
        season, time_period, is_weekend = _classify_dt(dt)
        key = _cell_key(season, time_period, is_weekend)

        with self._lock:
            cell = self._cells.get(key)
            if cell is None:
                return {"sum_error": 0.0, "count": 0, "mean_error": 0.0}
            return dict(cell)

    def get_sample_count(self, dt: datetime) -> int:
        """Return the sample_count for the cell corresponding to dt."""
        return self.get_cell(dt)["count"]

    def populated_cell_count(self) -> int:
        """Return the number of cells that have at least one observation."""
        with self._lock:
            return sum(1 for cell in self._cells.values() if cell["count"] > 0)

    def get_all_cells(self) -> Dict[str, Dict]:
        """
        Return a copy of all cells for dashboard display.

        Keys are canonical strings like "s0_t2_w1". Values are dicts with
        sum_error, count, and mean_error fields.
        """
        with self._lock:
            return {key: dict(cell) for key, cell in self._cells.items()}

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
            "version": SEASONAL_MODEL_VERSION,
            "cells": {key: dict(cell) for key, cell in self._cells.items()},
        }

    def _write_model(self, model: dict) -> None:
        """Atomic write to SEASONAL_MODEL_PATH using tmp + os.replace pattern."""
        tmp = SEASONAL_MODEL_PATH + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(model, f, indent=2)
            os.replace(tmp, SEASONAL_MODEL_PATH)
        except Exception:
            pass

    def _load(self) -> None:
        """
        Load persisted state from JSON. Gracefully ignores missing or corrupt files.

        Version check: only version 1 is supported currently. Unknown versions
        fall back to empty state to allow safe schema evolution.
        """
        try:
            with open(SEASONAL_MODEL_PATH, "r") as f:
                model = json.load(f)

            if model.get("version") != SEASONAL_MODEL_VERSION:
                return  # Unknown version — start fresh

            cells = model.get("cells", {})
            if isinstance(cells, dict):
                for key, cell in cells.items():
                    if (
                        isinstance(cell, dict)
                        and "sum_error" in cell
                        and "count" in cell
                        and "mean_error" in cell
                    ):
                        self._cells[key] = {
                            "sum_error": float(cell["sum_error"]),
                            "count": int(cell["count"]),
                            "mean_error": float(cell["mean_error"]),
                        }

        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
