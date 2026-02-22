"""
PV generation forecaster — v1.0

Fetches per-slot PV generation estimates from the evcc solar tariff API
(GET /api/tariff/solar) and maintains a rolling correction coefficient
that tracks actual PV output vs forecast. Handles partial forecasts
(< 24h data) by reducing confidence proportionally.

Unit handling (Research Pitfall 1):
    evcc solar tariff returns Watts, not kWh. Values > 100 are in Watts
    (Forecast.Solar/Open-Meteo); values <= 100 are already in kW.
    Reuses the median heuristic from state.py:calc_solar_surplus_kwh().

Nighttime guard (Research Pitfall 7):
    Correction coefficient is only updated when forecast > DAYTIME_THRESHOLD_W.
    This prevents the coefficient from drifting to 0 at night when both
    actual and forecast are near zero.
"""

import json
import os
import threading
from datetime import datetime, timezone
from typing import List, Optional

from logging_util import log

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PV_MODEL_PATH = "/data/smartprice_pv_model.json"
PV_MODEL_VERSION = 1

# Only update correction coefficient when forecast exceeds this level.
# Avoids nighttime drift when both actual and forecast are near zero.
DAYTIME_THRESHOLD_W = 50  # Watts

# Correction coefficient bounds: PV can be 3x forecast (unexpectedly sunny)
# or 0.3x forecast (heavy cloud cover). Wider than consumption correction.
CORRECTION_MIN = 0.3
CORRECTION_MAX = 3.0

# EMA weight for correction coefficient updates (per decision cycle).
# 0.1 means the coefficient adjusts slowly, smoothing out transient clouds.
EMA_ALPHA = 0.1

# 15-min sub-slots per hour for output resolution
SLOTS_PER_HOUR = 4
SLOTS_PER_DAY = 96  # 24h x 4


class PVForecaster:
    """
    Provides 96-slot (15-min resolution) PV generation forecasts for the
    next 24 hours by reading the evcc solar tariff API.

    Lifecycle:
        - __init__: restores correction coefficient from persistent storage
        - refresh(): called hourly to fetch new forecast from evcc API
        - update_correction(): called every 15-min decision cycle with
          actual PV power reading from StateStore
        - get_forecast_24h(): called by planner each cycle for kW values

    Thread safety:
        All reads/writes to _slots, _correction, and _coverage_hours are
        guarded by _lock.
    """

    def __init__(self, evcc_client) -> None:
        self._evcc = evcc_client
        # Parsed forecast slots: list of {"start": datetime, "end": datetime, "kw": float}
        self._slots: List[dict] = []
        # Rolling actual/forecast ratio — persisted across restarts
        self._correction: float = 1.0
        # Number of future hours with forecast data (0 = total failure, 24 = full coverage)
        self._coverage_hours: int = 0
        # Thread safety for concurrent read/write
        self._lock = threading.Lock()
        # Timestamp of last successful API fetch (UTC)
        self._last_refresh: Optional[datetime] = None

        # Restore correction coefficient from previous run
        self._load()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def refresh(self) -> None:
        """
        Fetch a fresh solar tariff forecast from the evcc API.

        Called hourly (per user decision: PV forecast refreshed hourly).
        On total API failure: sets coverage_hours=0 so confidence=0.0 and
        get_forecast_24h() returns 96 zeros (conservative, safe assumption).
        """
        rates = self._evcc.get_tariff_solar()

        if not rates:
            log("warning", "PV forecast: evcc solar API returned no data")
            with self._lock:
                self._coverage_hours = 0
                self._slots = []
            return

        now = datetime.now(timezone.utc)
        parsed = self._parse_rates(rates, now)

        # Count future slots to determine coverage.
        # Research open question 4: do NOT assume fixed slot size — each slot
        # may represent a different duration (Forecast.Solar=15min, Open-Meteo=1h).
        future_hours = self._count_future_hours(rates, now)

        with self._lock:
            self._slots = parsed
            self._coverage_hours = future_hours
            self._last_refresh = now

        self._save()
        log(
            "info",
            f"PV forecast: {future_hours}h coverage, "
            f"correction={self._correction:.2f}, "
            f"{len(parsed)} slots parsed",
        )

    def get_forecast_24h(self) -> list:
        """
        Return a 96-element list of kW values for the next 24 hours,
        in 15-minute resolution, with correction coefficient applied.

        - Values beyond available forecast data are returned as 0.0 (conservative).
        - If no forecast data at all: returns list of 96 zeros.
        - Correction coefficient applied slot-by-slot (daytime values only matter
          for planning; zeros are correctly left at zero).
        """
        with self._lock:
            slots = list(self._slots)
            correction = self._correction

        if not slots:
            return [0.0] * SLOTS_PER_DAY

        now = datetime.now(timezone.utc)
        result = []

        for i in range(SLOTS_PER_DAY):
            # Each output slot is 15 minutes from now
            slot_start_offset_minutes = i * 15
            target_time = now.replace(second=0, microsecond=0)
            # Compute the target datetime for this output slot
            target_minutes = (
                target_time.hour * 60 + target_time.minute + slot_start_offset_minutes
            )
            target_dt = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            from datetime import timedelta
            target_dt = target_dt + timedelta(minutes=target_minutes)
            # Ensure timezone-aware
            if target_dt.tzinfo is None:
                target_dt = target_dt.replace(tzinfo=timezone.utc)

            # Find the evcc slot covering this output slot
            kw = self._lookup_kw(slots, target_dt)
            # Apply correction coefficient (correction is already bounded to [0.3, 3.0])
            result.append(kw * correction)

        return result

    def update_correction(self, actual_pv_kw: float, timestamp: datetime) -> None:
        """
        Update rolling correction coefficient using actual PV power reading.

        Called every 15-min decision cycle with state.pv_power converted to kW.

        DAYTIME GUARD (Research Pitfall 7): only update when forecast > threshold.
        This prevents the coefficient from drifting when both actual and
        forecast are near zero at night.
        """
        with self._lock:
            slots = list(self._slots)
            correction = self._correction

        # Look up forecast for the current timestamp
        if not slots:
            return

        forecast_kw = self._lookup_kw(slots, timestamp)
        forecast_w = forecast_kw * 1000.0

        # Skip update if below daytime threshold
        if forecast_w <= DAYTIME_THRESHOLD_W:
            return

        # Guard against division by near-zero
        if forecast_kw < 0.001:
            return

        ratio = actual_pv_kw / forecast_kw
        new_correction = EMA_ALPHA * ratio + (1.0 - EMA_ALPHA) * correction
        # Clamp to [0.3, 3.0]: PV can legitimately be much higher or lower
        new_correction = max(CORRECTION_MIN, min(CORRECTION_MAX, new_correction))

        with self._lock:
            self._correction = new_correction

    # -----------------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------------

    @property
    def confidence(self) -> float:
        """
        Forecast confidence as 0.0-1.0 based on data coverage.
        12h of data = 0.5 confidence (per user decision).
        0h of data (total API failure) = 0.0.
        24h or more = 1.0.
        """
        with self._lock:
            return min(1.0, self._coverage_hours / 24.0)

    @property
    def correction_label(self) -> str:
        """
        Human-readable correction label for dashboard display below PV graph.
        Examples: "Korrektur: +13%", "Korrektur: -8%", "Korrektur: 0%"
        """
        with self._lock:
            pct = (self._correction - 1.0) * 100.0
        sign = "+" if pct >= 0 else ""
        return f"Korrektur: {sign}{pct:.0f}%"

    @property
    def quality_label(self) -> str:
        """
        Human-readable forecast quality label for dashboard display.
        Examples: "Basierend auf 18h Forecast-Daten", "Kein PV-Forecast verfuegbar"
        """
        with self._lock:
            hours = self._coverage_hours
        if hours == 0:
            return "Kein PV-Forecast verfuegbar"
        return f"Basierend auf {hours}h Forecast-Daten"

    @property
    def coverage_hours(self) -> int:
        """Number of future hours with forecast data. 0 = total failure."""
        with self._lock:
            return self._coverage_hours

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _parse_rates(self, rates: list, now: datetime) -> list:
        """
        Parse raw evcc rate dicts into internal slot format.

        Returns list of {"start": datetime, "end": datetime, "kw": float}.

        Unit detection (Research Pitfall 1, reuses state.py heuristic):
            If median value > 100 -> treat as Watts, multiply by 0.001 to get kW.
            If median value <= 100 -> treat as kW already.
        """
        # Compute unit factor from median value
        values = []
        for rate in rates:
            try:
                val = float(rate.get("value", 0))
                if val > 0:
                    values.append(val)
            except (TypeError, ValueError):
                continue

        if not values:
            return []

        # Median heuristic from state.py:calc_solar_surplus_kwh()
        median_val = sorted(values)[len(values) // 2]
        unit_factor = 0.001 if median_val > 100 else 1.0

        parsed = []
        for rate in rates:
            try:
                start_str = rate.get("start", "")
                end_str = rate.get("end", "")
                val = float(rate.get("value", 0))

                if not start_str or not end_str:
                    continue

                start_dt = self._parse_iso(start_str)
                end_dt = self._parse_iso(end_str)

                if start_dt is None or end_dt is None:
                    continue

                # Slot duration in hours (Research open question 4: do NOT assume fixed)
                slot_duration_hours = (end_dt - start_dt).total_seconds() / 3600.0
                if slot_duration_hours <= 0:
                    continue

                kw = val * unit_factor
                # Store kW directly (power at this slot); caller handles interpolation
                parsed.append({"start": start_dt, "end": end_dt, "kw": kw})

            except Exception as e:
                log("debug", f"PV forecast: skipping malformed rate slot: {e}")
                continue

        # Sort by start time
        parsed.sort(key=lambda s: s["start"])
        return parsed

    def _count_future_hours(self, rates: list, now: datetime) -> int:
        """
        Count how many future hours have forecast data.

        Handles variable slot durations: sums actual hours of coverage
        rather than counting slots (a 15-min slot = 0.25 hours).
        Clamped to integer for label display.
        """
        total_hours = 0.0
        for rate in rates:
            try:
                start_str = rate.get("start", "")
                end_str = rate.get("end", "")
                if not start_str or not end_str:
                    continue
                start_dt = self._parse_iso(start_str)
                end_dt = self._parse_iso(end_str)
                if start_dt is None or end_dt is None:
                    continue
                # Only count future slots
                if start_dt > now:
                    duration_hours = (end_dt - start_dt).total_seconds() / 3600.0
                    total_hours += duration_hours
            except Exception:
                continue
        return int(total_hours)

    @staticmethod
    def _parse_iso(s: str) -> Optional[datetime]:
        """Parse ISO8601 timestamp string to timezone-aware datetime."""
        if not s:
            return None
        try:
            if s.endswith("Z"):
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            return datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _lookup_kw(slots: list, target_dt: datetime) -> float:
        """
        Find the kW value for a given datetime by searching the slot list.

        Returns 0.0 for times beyond the forecast horizon (conservative).
        Uses the evcc slot whose [start, end) range contains target_dt.
        """
        for slot in slots:
            if slot["start"] <= target_dt < slot["end"]:
                return slot["kw"]
        return 0.0

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _load(self) -> None:
        """
        Load correction coefficient from persistent storage.

        Only restores correction (forecast data is ephemeral — re-fetched hourly).
        On version mismatch or missing file: uses default correction = 1.0.
        """
        try:
            with open(PV_MODEL_PATH, "r") as f:
                model = json.load(f)

            if model.get("version") != PV_MODEL_VERSION:
                log(
                    "info",
                    f"PV model version mismatch (found {model.get('version')!r}, "
                    f"expected {PV_MODEL_VERSION}), resetting to defaults",
                )
                return

            self._correction = float(model.get("correction", 1.0))
            log(
                "info",
                f"PV forecast model loaded: correction={self._correction:.2f}",
            )

        except FileNotFoundError:
            log("debug", "PV forecast model not found, starting with correction=1.0")
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log("warning", f"PV forecast model load error: {e}, resetting to defaults")

    def _save(self) -> None:
        """
        Persist correction coefficient to storage using atomic write.

        Writes to a .tmp file first, then renames (atomic on Linux/Alpine),
        preventing corrupt model file on crash mid-write.
        """
        model = {
            "version": PV_MODEL_VERSION,
            "correction": self._correction,
            "last_refresh": (
                self._last_refresh.isoformat()
                if self._last_refresh
                else None
            ),
        }
        tmp_path = PV_MODEL_PATH + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(model, f, indent=2)
            os.rename(tmp_path, PV_MODEL_PATH)
        except Exception as e:
            log("error", f"PV forecast: failed to save model: {e}")
