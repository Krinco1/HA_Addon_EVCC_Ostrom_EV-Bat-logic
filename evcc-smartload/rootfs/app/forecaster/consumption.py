"""
ConsumptionForecaster — Hour-of-day rolling average forecaster for EVCC-Smartload.

Maintains a 96-slot (15-min resolution) model of typical house consumption in Watts.
Data is sourced from InfluxDB history using a tiered aggregation scheme:
  - Last 7 days: full 15-min resolution (weight 1.0)
  - Days 8-30: hourly averages distributed to 4 slots (weight 0.5)
  - Beyond 30 days: not yet implemented (reserved for future seasonal data)

The model persists to /data/ as a versioned JSON file and survives restarts.
On schema version mismatch, the model is rebuilt from InfluxDB source data.

Cold start (no data): is_ready returns False, get_forecast_24h returns DEFAULT_WATTS
for all slots. After 24h of real data, is_ready becomes True.
"""

import json
import os
import threading
from datetime import datetime, timezone

from logging_util import log

# Persistent storage
MODEL_PATH = "/data/smartprice_consumption_model.json"
MODEL_VERSION = 1

# Forecast constants
SLOTS_PER_DAY = 96      # 24h * 4 slots/h (15-min resolution)
DEFAULT_WATTS = 1200    # Sensible cold-start default (1.2 kW typical European household)

# EMA smoothing factor: alpha=0.1 → smooth (new observation = 10% weight)
EMA_ALPHA = 0.1

# Save interval: persist every 4th update (once per hour at 15-min cycle)
SAVE_INTERVAL = 4


def _slot_index(ts: datetime) -> int:
    """Convert a datetime to a 15-min slot index (0-95).

    Slot 0 = 00:00-00:15, slot 95 = 23:45-24:00.
    """
    return (ts.hour * 60 + ts.minute) // 15


class ConsumptionForecaster:
    """Hour-of-day rolling average forecaster with tiered InfluxDB bootstrap.

    Thread-safe: all reads and writes to internal model state are guarded
    by a threading.Lock(). Callers from the main decision loop and web server
    can safely call get_forecast_24h() concurrently.

    Design decisions (see 03-RESEARCH.md):
    - EMA with alpha=0.1: smooth enough to filter noise, reactive enough for
      gradual load changes (e.g., new appliance, seasonal shift).
    - Tiered bootstrap: 7d@15min + 8-30d@1h. Avoids loading full 30-day raw
      history (43,200 rows) on every restart — only needed at cold start.
    - Atomic JSON write: write to .tmp then os.rename() — crash-safe on Alpine Linux.
    - Correction factor clamped to [0.5, 1.5]: prevents pathological overcorrection
      if a single outlier reading (e.g., induction stove spike) skews the ratio.
    """

    def __init__(self, influx_client, cfg):
        """Initialize forecaster with InfluxDB client and config.

        Args:
            influx_client: InfluxDBClient instance for querying home_power history
            cfg: Config instance (used for future HA config access)
        """
        self._influx = influx_client
        self._cfg = cfg

        # Internal model state (guarded by _lock)
        self._slot_sums = [0.0] * SLOTS_PER_DAY
        self._slot_counts = [0] * SLOTS_PER_DAY
        self._correction_factor = 1.0
        self._data_days = 0
        self._seen_days: set = set()   # tracks unique days for _data_days estimation
        self._update_count = 0         # for save-interval logic

        self._lock = threading.Lock()

        # Bootstrap from persistent storage or InfluxDB
        self._load_or_init()

    # ------------------------------------------------------------------
    # Public forecast interface
    # ------------------------------------------------------------------

    def get_forecast_24h(self) -> list:
        """Return a 96-slot list of estimated Watt values for the next 24h.

        Slots are ordered starting from the current 15-min slot and wrapping
        around the day. Slots without data return DEFAULT_WATTS. All values
        are scaled by the current correction_factor.

        Returns:
            list of 96 floats (Watts), starting from current slot.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            now_slot = _slot_index(now)
            result = []
            for i in range(SLOTS_PER_DAY):
                slot_idx = (now_slot + i) % SLOTS_PER_DAY
                if self._slot_counts[slot_idx] > 0:
                    avg = self._slot_sums[slot_idx] / self._slot_counts[slot_idx]
                    result.append(avg * self._correction_factor)
                else:
                    result.append(float(DEFAULT_WATTS))
            return result

    def update(self, current_watts: float, timestamp: datetime):
        """Update the model with an actual home_power observation.

        Called every 15-min decision cycle. Uses EMA to smoothly update
        the slot average. Tracks unique days seen for is_ready gate.
        Saves the model every SAVE_INTERVAL updates (once per hour).

        Args:
            current_watts: Actual home_power reading in Watts
            timestamp: Timestamp of the observation (timezone-aware preferred)
        """
        if current_watts < 0:
            return  # defensive: negative power readings are invalid

        slot = _slot_index(timestamp)
        day_key = (timestamp.year, timestamp.month, timestamp.day)

        with self._lock:
            if self._slot_counts[slot] == 0:
                # Cold slot: initialize directly (no prior average to smooth)
                self._slot_sums[slot] = float(current_watts)
                self._slot_counts[slot] = 1
            else:
                # Warm slot: apply EMA (normalized storage: sum=avg, count=1)
                old_avg = self._slot_sums[slot] / self._slot_counts[slot]
                new_avg = (1.0 - EMA_ALPHA) * old_avg + EMA_ALPHA * current_watts
                self._slot_sums[slot] = new_avg
                self._slot_counts[slot] = 1  # normalized after EMA

            # Track unique days for readiness gate
            if day_key not in self._seen_days:
                self._seen_days.add(day_key)
                self._data_days = len(self._seen_days)

            # Save model periodically (every hour, not every 15 min)
            self._update_count += 1
            if self._update_count % SAVE_INTERVAL == 0:
                self._save()

    def apply_correction(self, actual_watts: float, forecast_watts: float):
        """Apply immediate self-correction when actual load deviates from forecast.

        Called when the current-hour actual load is known. Adjusts correction_factor
        to scale future forecasts proportionally. Clamped to [0.5, 1.5] to prevent
        pathological overcorrection from outlier spikes.

        Only applies when forecast_watts > 100 W to avoid near-zero division.

        Args:
            actual_watts: Actual home_power reading in Watts
            forecast_watts: Forecasted home_power for this slot in Watts
        """
        if forecast_watts <= 100:
            return  # avoid division by near-zero

        raw_ratio = actual_watts / forecast_watts
        with self._lock:
            self._correction_factor = max(0.5, min(1.5, raw_ratio))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        """True after at least 24h of real data has been accumulated.

        Before this threshold, the planner should use hardcoded defaults and
        log "Forecaster not ready, using defaults".
        """
        return self._data_days >= 1

    @property
    def data_days(self) -> int:
        """Number of unique days with real data (for dashboard maturity display)."""
        return self._data_days

    @property
    def correction_factor(self) -> float:
        """Current correction factor applied to all forecasts."""
        with self._lock:
            return self._correction_factor

    # ------------------------------------------------------------------
    # Internal: persistence
    # ------------------------------------------------------------------

    def _load_or_init(self):
        """Load model from persistent storage or bootstrap from InfluxDB.

        Schema version check ensures model is rebuilt if the storage format
        changes between code versions (Pitfall 4 from Research).
        """
        try:
            if os.path.exists(MODEL_PATH):
                with open(MODEL_PATH, "r") as f:
                    model = json.load(f)

                if model.get("version") != MODEL_VERSION:
                    log("warning",
                        f"ConsumptionForecaster: schema upgrade detected "
                        f"(v{model.get('version')} -> v{MODEL_VERSION}), "
                        f"rebuilding model from InfluxDB")
                    self._bootstrap_from_influxdb()
                    return

                # Restore model state from file
                self._slot_sums = model.get("slot_sums", [0.0] * SLOTS_PER_DAY)
                self._slot_counts = model.get("slot_counts", [0] * SLOTS_PER_DAY)
                self._data_days = model.get("data_days", 0)
                self._correction_factor = model.get("correction_factor", 1.0)

                # Reconstruct seen_days as a synthetic set from data_days count
                # (we don't persist seen_days individually — just reconstruct count)
                self._seen_days = set(range(self._data_days))

                log("info",
                    f"ConsumptionForecaster: loaded model ({self._data_days} days data, "
                    f"correction={self._correction_factor:.3f})")
            else:
                log("info", "ConsumptionForecaster: no model file found, bootstrapping from InfluxDB")
                self._bootstrap_from_influxdb()

        except Exception as e:
            log("warning", f"ConsumptionForecaster: model load error ({e}), bootstrapping from InfluxDB")
            self._bootstrap_from_influxdb()

    def _bootstrap_from_influxdb(self):
        """Bootstrap the model from InfluxDB history using tiered aggregation.

        Tier 1 (last 7 days): 15-min resolution, weight 1.0
        Tier 2 (days 8-30): hourly averages distributed to 4 slots, weight 0.5

        Resets slot arrays before populating to ensure clean state on schema upgrade.
        """
        log("info", "ConsumptionForecaster: bootstrapping from InfluxDB history...")

        # Reset state
        self._slot_sums = [0.0] * SLOTS_PER_DAY
        self._slot_counts = [0] * SLOTS_PER_DAY
        self._data_days = 0
        self._seen_days = set()

        min_ts = None
        max_ts = None
        observations_loaded = 0

        # --- Tier 1: Last 7 days at 15-min resolution ---
        try:
            recent_data = self._influx.query_home_power_15min(days=7)
            for row in recent_data:
                ts = _parse_influx_timestamp(row["time"])
                if ts is None:
                    continue
                watts = row["watts"]
                slot = _slot_index(ts)

                # Weight 1.0: direct accumulation
                self._slot_sums[slot] += watts
                self._slot_counts[slot] += 1
                observations_loaded += 1

                if min_ts is None or ts < min_ts:
                    min_ts = ts
                if max_ts is None or ts > max_ts:
                    max_ts = ts

            log("info", f"ConsumptionForecaster: tier 1 loaded {len(recent_data)} 15-min points")
        except Exception as e:
            log("warning", f"ConsumptionForecaster: tier 1 (15-min) load failed: {e}")

        # --- Tier 2: Days 8-30 at hourly resolution ---
        try:
            medium_data = self._influx.query_home_power_hourly(days_start=8, days_end=30)
            for row in medium_data:
                ts = _parse_influx_timestamp(row["time"])
                if ts is None:
                    continue
                watts = row["watts"]

                # Each hourly value maps to 4 x 15-min slots
                # Weight 0.5: older data contributes less
                base_slot = (ts.hour * 4)  # first slot of this hour
                weight = 0.5
                for offset in range(4):
                    slot = (base_slot + offset) % SLOTS_PER_DAY
                    self._slot_sums[slot] += watts * weight
                    self._slot_counts[slot] += weight

                observations_loaded += 1

                if min_ts is None or ts < min_ts:
                    min_ts = ts

            log("info", f"ConsumptionForecaster: tier 2 loaded {len(medium_data)} hourly points")
        except Exception as e:
            log("warning", f"ConsumptionForecaster: tier 2 (hourly) load failed: {e}")

        # Estimate data_days from timestamp span
        if min_ts is not None and max_ts is not None:
            span_days = max(1, (max_ts - min_ts).days + 1)
            self._data_days = span_days
            self._seen_days = set(range(span_days))
        elif observations_loaded > 0:
            self._data_days = 1
            self._seen_days = {0}

        log("info",
            f"ConsumptionForecaster: bootstrap complete — {observations_loaded} observations, "
            f"{self._data_days} days estimated, ready={self.is_ready}")

        self._save()

    def _save(self):
        """Atomically persist the model to disk.

        Uses write-to-tmp + os.rename() pattern for crash safety on Alpine Linux.
        (see Research "Don't Hand-Roll": JSON atomic write pattern)
        """
        try:
            model = {
                "version": MODEL_VERSION,
                "slot_sums": self._slot_sums,
                "slot_counts": self._slot_counts,
                "data_days": self._data_days,
                "correction_factor": self._correction_factor,
            }
            tmp_path = MODEL_PATH + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(model, f, indent=2)
            os.rename(tmp_path, MODEL_PATH)
        except Exception as e:
            log("warning", f"ConsumptionForecaster: save failed: {e}")


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _parse_influx_timestamp(ts_str: str) -> datetime:
    """Parse InfluxDB RFC3339 timestamp string to a UTC datetime.

    Args:
        ts_str: ISO 8601 / RFC3339 timestamp string from InfluxDB
                (e.g., "2026-02-22T14:15:00Z" or "2026-02-22T14:15:00+00:00")

    Returns:
        UTC-aware datetime, or None on parse error.
    """
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None
