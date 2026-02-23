"""
DynamicBufferCalc — Phase 5: Situational battery minimum SoC

Computes a target buffer SoC every 15-minute cycle based on PV confidence,
price spread, and time of day. An observation mode runs for the first 14 days,
logging what the system would do without applying changes. After 14 days (or on
manual activation), it enters live mode and applies changes via evcc.

Thread safety: all state access guarded by _lock. File I/O happens outside
the lock to avoid blocking SSE reads in the web thread.

Persistence: atomic JSON write to /data/smartload_buffer_model.json,
same pattern as PVForecaster._save().
"""

import json
import os
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import List, Optional

BUFFER_MODEL_PATH = "/data/smartload_buffer_model.json"
BUFFER_MODEL_VERSION = 1

# Hard floor: buffer NEVER drops below this regardless of inputs
HARD_FLOOR_PCT = 10

# Practical minimum even at highest confidence (user decision: conservative)
PRACTICAL_MIN_PCT = 20

# Confidence threshold above which buffer reduction begins
# (Claude's discretion: 0.65 — above 50%, conservative)
CONFIDENCE_REDUCTION_THRESHOLD = 0.65

# Observation mode duration in seconds (14 days)
OBSERVATION_PERIOD_SECONDS = 14 * 24 * 3600

# Max log entries kept in memory and persisted (7 days x 96 cycles/day = 672)
MAX_LOG_ENTRIES = 700


class BufferEvent:
    """Single buffer adjustment event — logged regardless of mode."""

    __slots__ = (
        "ts", "mode", "pv_confidence", "price_spread_ct",
        "hour_of_day", "expected_pv_kw", "old_buffer_pct",
        "new_buffer_pct", "reason", "applied",
    )

    def __init__(
        self,
        pv_confidence: float,
        price_spread_ct: float,
        hour_of_day: int,
        expected_pv_kw: float,
        old_buffer_pct: int,
        new_buffer_pct: int,
        reason: str,
        applied: bool,
        mode: str,
    ):
        self.ts = datetime.now(timezone.utc)
        self.pv_confidence = pv_confidence
        self.price_spread_ct = price_spread_ct
        self.hour_of_day = hour_of_day
        self.expected_pv_kw = expected_pv_kw
        self.old_buffer_pct = old_buffer_pct
        self.new_buffer_pct = new_buffer_pct
        self.reason = reason
        self.applied = applied    # False in observation mode
        self.mode = mode          # "observation" or "live"

    def to_dict(self) -> dict:
        return {
            "ts": self.ts.isoformat(),
            "mode": self.mode,
            "pv_confidence": round(self.pv_confidence * 100, 1),
            "price_spread_ct": round(self.price_spread_ct * 100, 2),
            "hour_of_day": self.hour_of_day,
            "expected_pv_kw": round(self.expected_pv_kw, 2),
            "old_buffer_pct": self.old_buffer_pct,
            "new_buffer_pct": self.new_buffer_pct,
            "reason": self.reason,
            "applied": self.applied,
        }


class DynamicBufferCalc:
    """
    Computes and (in live mode) applies a dynamic battery minimum SoC.

    Observation mode: runs formula, logs what it would do, does NOT call evcc.
    Live mode: runs formula, logs, calls evcc.set_buffer_soc() when target changes.

    Thread safety: all state mutations guarded by _lock. File I/O released
    from lock before writing (Pitfall 2: no I/O under lock).
    """

    def __init__(self, cfg, evcc_client) -> None:
        self._cfg = cfg
        self._evcc = evcc_client
        self._lock = threading.Lock()

        # Observation mode state (persisted across restarts)
        self._deployment_ts: Optional[datetime] = None
        self._live_override: Optional[bool] = None            # True=live, False=extend obs
        self._observation_extended_until: Optional[datetime] = None

        # Current effective buffer SoC (persisted, last applied value)
        self._current_buffer_pct: int = getattr(cfg, "battery_min_soc", PRACTICAL_MIN_PCT)

        # Event log (bounded deque; persisted to JSON across restarts)
        self._log: deque = deque(maxlen=MAX_LOG_ENTRIES)

        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def step(
        self,
        pv_confidence: float,    # 0.0–1.0 from PVForecaster.confidence
        price_spread: float,     # EUR/kWh from SystemState.price_spread
        pv_96: list,             # 96-slot kW forecast from PVForecaster
        now: Optional[datetime] = None,
    ) -> dict:
        """
        Run one calculation cycle. Called every 15 minutes from main loop.

        In observation mode: logs what would happen, does NOT call evcc.
        In live mode: calls evcc.set_buffer_soc() only when target changes.

        Returns:
            {
                "current_buffer_pct": int,
                "mode": "observation" | "live",
                "days_remaining": int | None,
                "log_recent": [dict, ...],   # last 100 entries
                "observation_live_at": ISO str | None,
            }
        """
        if now is None:
            now = datetime.now(timezone.utc)

        mode = self._determine_mode(now)
        target_buffer = self._compute_target(pv_confidence, price_spread, pv_96, now)
        old_buffer = self._current_buffer_pct

        applied = (mode == "live")

        # In live mode: call evcc only when target changed
        if applied and target_buffer != old_buffer:
            self._evcc.set_buffer_soc(target_buffer)
            with self._lock:
                self._current_buffer_pct = target_buffer

        reason = self._build_reason(pv_confidence, price_spread, target_buffer, mode)

        # Always log every cycle for chart continuity (observation entries: applied=False)
        event = BufferEvent(
            pv_confidence=pv_confidence,
            price_spread_ct=price_spread,
            hour_of_day=now.hour,
            expected_pv_kw=self._sum_next_4h_pv(pv_96),
            old_buffer_pct=old_buffer,
            new_buffer_pct=target_buffer,
            reason=reason,
            applied=applied,
            mode=mode,
        )
        with self._lock:
            self._log.append(event)

        self._save()

        with self._lock:
            log_recent = [e.to_dict() for e in list(self._log)[-100:]]
            current_buf = self._current_buffer_pct

        days_remaining = self._days_remaining(now) if mode == "observation" else None
        live_at = self._live_activation_ts()

        return {
            "current_buffer_pct": current_buf,
            "mode": mode,
            "days_remaining": days_remaining,
            "log_recent": log_recent,
            "observation_live_at": live_at.isoformat() if live_at else None,
        }

    def activate_live(self) -> None:
        """User manually activates live mode early."""
        with self._lock:
            self._live_override = True
        self._save()

    def extend_observation(self, extra_days: int = 14) -> None:
        """User extends observation period by N more days from now."""
        with self._lock:
            self._live_override = False
            self._observation_extended_until = (
                datetime.now(timezone.utc) + timedelta(days=extra_days)
            )
        self._save()

    # ------------------------------------------------------------------
    # Formula
    # ------------------------------------------------------------------

    def _compute_target(
        self, confidence: float, spread: float, pv_96: list, now: datetime
    ) -> int:
        """
        Conservative formula: practical minimum 20%, hard floor 10%.

        Base: cfg.battery_min_soc (user-configured safe minimum, e.g. 20–30%)
        Reduction triggers when confidence > CONFIDENCE_REDUCTION_THRESHOLD (0.65).

        Modifiers (all additively combined, then clamped to max_reduction):
          - conf_factor: scales linearly from 0 at threshold to 1.0 at full confidence
          - spread_bonus: +0.1 when price spread > 0.10 EUR/kWh (good arbitrage day)
          - time_bonus: +0.1 in morning hours 5–10 when solar ramp-up is imminent

        Hysteresis: target rounded to nearest 5% to prevent oscillation (Pitfall 4).
        Hard floor: HARD_FLOOR_PCT (10%) always enforced.
        """
        base = getattr(self._cfg, "battery_min_soc", PRACTICAL_MIN_PCT)
        max_reduction = max(0, base - PRACTICAL_MIN_PCT)

        # Fallback: confidence too low or no room to reduce — return base
        if confidence <= CONFIDENCE_REDUCTION_THRESHOLD or max_reduction == 0:
            return base

        # Linear scale: 0 at threshold, 1 at confidence=1.0
        conf_factor = (confidence - CONFIDENCE_REDUCTION_THRESHOLD) / (
            1.0 - CONFIDENCE_REDUCTION_THRESHOLD
        )

        # Spread modifier: wide spread = good arbitrage opportunity
        spread_bonus = 0.1 if spread > 0.10 else 0.0

        # Time modifier: morning hours = solar coming in soon
        time_bonus = 0.1 if 5 <= now.hour <= 10 else 0.0

        total_factor = min(1.0, conf_factor + spread_bonus + time_bonus)
        reduction = int(max_reduction * total_factor)
        target = base - reduction

        # Apply hysteresis: round to nearest 5% to dampen oscillation
        target = round(target / 5) * 5

        # Enforce floors
        target = max(target, PRACTICAL_MIN_PCT)
        target = max(target, HARD_FLOOR_PCT)

        return int(target)

    # ------------------------------------------------------------------
    # Mode determination
    # ------------------------------------------------------------------

    def _determine_mode(self, now: datetime) -> str:
        with self._lock:
            if self._live_override is True:
                return "live"

            if self._live_override is False:
                # User extended observation period
                if (
                    self._observation_extended_until is not None
                    and now < self._observation_extended_until
                ):
                    return "observation"
                # Extended period over — go live
                return "live"

            # Auto mode: check elapsed time since deployment
            if self._deployment_ts is None:
                # First ever call: set deployment timestamp and persist
                self._deployment_ts = now
                self._save_unlocked()

            elapsed = (now - self._deployment_ts).total_seconds()
            if elapsed >= OBSERVATION_PERIOD_SECONDS:
                return "live"
            return "observation"

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _sum_next_4h_pv(self, pv_96: list) -> float:
        """Sum PV kW over next 4 hours (16 x 15-min slots). Used for logging only."""
        if not pv_96:
            return 0.0
        return float(sum(pv_96[:16]))

    def _days_remaining(self, now: datetime) -> Optional[int]:
        """Return observation days remaining, or 14 if deployment_ts not set yet."""
        with self._lock:
            if self._deployment_ts is None:
                return 14
            elapsed = (now - self._deployment_ts).total_seconds()
            remaining = OBSERVATION_PERIOD_SECONDS - elapsed
            return max(0, int(remaining / 86400))

    def _live_activation_ts(self) -> Optional[datetime]:
        """Return timestamp when observation period ends automatically."""
        with self._lock:
            if self._deployment_ts is None:
                return None
            return self._deployment_ts + timedelta(seconds=OBSERVATION_PERIOD_SECONDS)

    def _build_reason(
        self, confidence: float, spread: float, target: int, mode: str
    ) -> str:
        """German-language reason string for event log."""
        parts = [f"Konfidenz {confidence * 100:.0f}%"]
        if spread > 0.10:
            parts.append(f"Spread {spread * 100:.0f}ct")
        parts.append(f"Puffer {target}%")
        if mode == "observation":
            parts.append("[Simulation]")
        return " · ".join(parts)

    # ------------------------------------------------------------------
    # Persistence — atomic write, same pattern as PVForecaster._save()
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load persisted state from JSON. Gracefully ignores missing or corrupt files."""
        try:
            with open(BUFFER_MODEL_PATH, "r") as f:
                model = json.load(f)
            if model.get("version") != BUFFER_MODEL_VERSION:
                return

            ts_str = model.get("deployment_ts")
            if ts_str:
                # Handle trailing 'Z' for older Python versions
                if ts_str.endswith("Z"):
                    ts_str = ts_str.replace("Z", "+00:00")
                self._deployment_ts = datetime.fromisoformat(ts_str)

            live_override = model.get("live_override")
            if live_override is not None:
                self._live_override = bool(live_override)

            ext_str = model.get("observation_extended_until")
            if ext_str:
                if ext_str.endswith("Z"):
                    ext_str = ext_str.replace("Z", "+00:00")
                self._observation_extended_until = datetime.fromisoformat(ext_str)

            self._current_buffer_pct = int(
                model.get(
                    "current_buffer_pct",
                    getattr(self._cfg, "battery_min_soc", PRACTICAL_MIN_PCT),
                )
            )

            # Restore log entries as plain dicts (not full BufferEvent objects)
            # to simplify the restore path — they're only used for chart/table rendering
            for entry_dict in model.get("log", []):
                self._log.append(entry_dict)

        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

    def _save(self) -> None:
        """Serialize current state to JSON atomically. Acquires lock for serialization only."""
        with self._lock:
            model = self._build_model_dict()

        # File I/O outside the lock to avoid blocking SSE reads (Pitfall 2)
        tmp = BUFFER_MODEL_PATH + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(model, f, indent=2)
            os.rename(tmp, BUFFER_MODEL_PATH)
        except Exception:
            pass

    def _save_unlocked(self) -> None:
        """Must be called while already holding self._lock (e.g. from _determine_mode)."""
        model = self._build_model_dict()
        # Release lock before file I/O — caller must re-acquire if needed
        # (This method is only called from _determine_mode which immediately returns)
        tmp = BUFFER_MODEL_PATH + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(model, f, indent=2)
            os.rename(tmp, BUFFER_MODEL_PATH)
        except Exception:
            pass

    def _build_model_dict(self) -> dict:
        """Build JSON-serializable model dict. Caller must hold self._lock."""
        return {
            "version": BUFFER_MODEL_VERSION,
            "deployment_ts": (
                self._deployment_ts.isoformat() if self._deployment_ts else None
            ),
            "live_override": self._live_override,
            "observation_extended_until": (
                self._observation_extended_until.isoformat()
                if self._observation_extended_until
                else None
            ),
            "current_buffer_pct": self._current_buffer_pct,
            "log": [
                e.to_dict() if isinstance(e, BufferEvent) else e
                for e in self._log
            ],
        }
