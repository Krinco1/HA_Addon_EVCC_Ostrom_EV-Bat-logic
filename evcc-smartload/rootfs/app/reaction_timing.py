"""
ReactionTimingTracker — Phase 8: Adaptive reaction timing learning

Classifies plan deviations as self-correcting or requiring intervention.
Maintains an EMA of the self-correction rate and uses it to decide whether
to trigger an immediate re-plan or wait for natural self-correction.

Definition:
    - Deviation: plan_action != actual_action at a given cycle.
    - Self-corrected: on the NEXT cycle after a deviation, plan_action
      and actual_action are aligned again — the system corrected itself
      without an external re-plan trigger.
    - Intervention required: the deviation persisted or widened.

EMA:
    - alpha = 0.05 (slow-moving; stable long-term threshold estimate)
    - Initial ema_self_correction_rate = 0.5 (neutral — no prior history)
    - wait_threshold = 0.6 (re-plan if fewer than 60% of deviations self-correct)

Decision rule:
    should_replan_immediately() returns True when ema < wait_threshold.
    This is conservative: re-plan unless the system has learned that
    most deviations self-correct.

Thread safety: all state mutations guarded by _lock. File I/O outside lock.

Persistence: atomic JSON write to /data/smartprice_reaction_timing.json.
Same pattern as DynamicBufferCalc and SeasonalLearner.
"""

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

REACTION_TIMING_PATH = "/data/smartprice_reaction_timing.json"
REACTION_TIMING_VERSION = 1

# EMA parameters
_EMA_ALPHA: float = 0.05
_INITIAL_EMA: float = 0.5
_WAIT_THRESHOLD: float = 0.6

# Max episodes retained in memory and persisted
_MAX_EPISODES = 100

# Known plan action strings (used for validation / display)
KNOWN_ACTIONS = frozenset(
    ["bat_charge", "bat_hold", "bat_discharge", "ev_charge", "ev_idle"]
)


@dataclass
class DeviationEpisode:
    """Record of a single plan vs actual deviation episode.

    Fields:
        timestamp:          UTC datetime the deviation was first observed.
        plan_action:        Expected action from LP plan (e.g. "bat_charge").
        actual_action:      Action actually applied by controller.
        self_corrected:     True if plan and actual aligned on the NEXT cycle
                            without an explicit re-plan trigger.
        resolved_in_cycles: 0 if still pending, 1 if resolved on next cycle.
    """
    timestamp: datetime
    plan_action: str
    actual_action: str
    self_corrected: bool = False
    resolved_in_cycles: int = 0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "plan_action": self.plan_action,
            "actual_action": self.actual_action,
            "self_corrected": self.self_corrected,
            "resolved_in_cycles": self.resolved_in_cycles,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DeviationEpisode":
        ts_str = d["timestamp"]
        if ts_str.endswith("Z"):
            ts_str = ts_str.replace("Z", "+00:00")
        return cls(
            timestamp=datetime.fromisoformat(ts_str),
            plan_action=d["plan_action"],
            actual_action=d["actual_action"],
            self_corrected=bool(d.get("self_corrected", False)),
            resolved_in_cycles=int(d.get("resolved_in_cycles", 0)),
        )


class ReactionTimingTracker:
    """Learns whether plan deviations tend to self-correct or require intervention.

    Usage:
        tracker = ReactionTimingTracker()
        tracker.update(plan_action="bat_charge", actual_action="bat_hold")
        if tracker.should_replan_immediately():
            plan = horizon_planner.plan(...)
        stats = tracker.get_stats()
    """

    def __init__(self) -> None:
        self._episodes: List[DeviationEpisode] = []
        self._ema_self_correction_rate: float = _INITIAL_EMA
        self._wait_threshold: float = _WAIT_THRESHOLD
        self._pending_episode: Optional[DeviationEpisode] = None
        self._lock = threading.Lock()
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, plan_action: str, actual_action: str) -> None:
        """Record one plan vs actual observation and update EMA.

        Logic:
        1. If there is a pending episode (unresolved deviation from last cycle):
           - Check if plan and actual now align.
           - If yes: mark pending episode self_corrected=True, resolved_in_cycles=1.
           - If no: mark self_corrected=False, resolved_in_cycles=0 (intervention).
           - Commit pending episode, update EMA.
           - Clear pending.
        2. If plan_action == actual_action: no deviation this cycle.
        3. If plan_action != actual_action: create a new pending episode.

        Args:
            plan_action:   Action from LP plan (e.g. "bat_charge").
            actual_action: Action applied by controller (e.g. "bat_hold").
        """
        model_snapshot = None

        with self._lock:
            # Step 1: resolve pending episode from previous cycle
            if self._pending_episode is not None:
                aligned = (plan_action == actual_action)
                self._pending_episode.self_corrected = aligned
                self._pending_episode.resolved_in_cycles = 1 if aligned else 0

                # Update EMA: self_corrected=1 means good (self-corrected)
                correction_value = 1.0 if aligned else 0.0
                self._ema_self_correction_rate = (
                    _EMA_ALPHA * correction_value
                    + (1 - _EMA_ALPHA) * self._ema_self_correction_rate
                )

                # Append episode to history (cap at _MAX_EPISODES)
                self._episodes.append(self._pending_episode)
                if len(self._episodes) > _MAX_EPISODES:
                    self._episodes = self._episodes[-_MAX_EPISODES:]

                self._pending_episode = None
                model_snapshot = self._build_model_dict()

            # Step 2: check for new deviation this cycle
            if plan_action != actual_action:
                self._pending_episode = DeviationEpisode(
                    timestamp=datetime.now(timezone.utc),
                    plan_action=plan_action,
                    actual_action=actual_action,
                )

        if model_snapshot is not None:
            self._write_model(model_snapshot)

    def should_replan_immediately(self) -> bool:
        """Return True if historical data says deviations usually do NOT self-correct.

        Returns True when ema_self_correction_rate < wait_threshold (0.6).
        This means: fewer than 60% of past deviations corrected themselves,
        so an immediate re-plan is warranted.

        On first startup (no data), returns False (wait — assume self-correction
        until proven otherwise to avoid thrashing).
        """
        with self._lock:
            return self._ema_self_correction_rate < self._wait_threshold

    def get_stats(self) -> dict:
        """Return current tracker statistics.

        Returns:
            {
                "ema_self_correction_rate": float,  # current EMA
                "wait_threshold": float,             # threshold for re-plan decision
                "total_episodes": int,               # episodes committed so far
                "should_replan": bool,               # current decision
            }
        """
        with self._lock:
            return {
                "ema_self_correction_rate": self._ema_self_correction_rate,
                "wait_threshold": self._wait_threshold,
                "total_episodes": len(self._episodes),
                "should_replan": self._ema_self_correction_rate < self._wait_threshold,
            }

    def save(self) -> None:
        """Persist current state to disk immediately."""
        with self._lock:
            model_snapshot = self._build_model_dict()
        self._write_model(model_snapshot)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _build_model_dict(self) -> dict:
        """Build JSON-serializable model dict. Caller must hold self._lock."""
        return {
            "version": REACTION_TIMING_VERSION,
            "ema_self_correction_rate": self._ema_self_correction_rate,
            "wait_threshold": self._wait_threshold,
            "episodes": [ep.to_dict() for ep in self._episodes[-_MAX_EPISODES:]],
        }

    def _write_model(self, model: dict) -> None:
        """Atomic write to REACTION_TIMING_PATH using tmp + os.replace pattern."""
        tmp = REACTION_TIMING_PATH + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(model, f, indent=2)
            os.replace(tmp, REACTION_TIMING_PATH)
        except Exception:
            pass

    def _load(self) -> None:
        """Load persisted state from JSON. Gracefully ignores missing or corrupt files."""
        try:
            with open(REACTION_TIMING_PATH, "r") as f:
                model = json.load(f)

            if model.get("version") != REACTION_TIMING_VERSION:
                return  # Unknown version — start fresh

            ema = model.get("ema_self_correction_rate")
            if ema is not None:
                self._ema_self_correction_rate = float(ema)

            threshold = model.get("wait_threshold")
            if threshold is not None:
                self._wait_threshold = float(threshold)

            episodes_raw = model.get("episodes", [])
            if isinstance(episodes_raw, list):
                for raw in episodes_raw:
                    try:
                        self._episodes.append(DeviationEpisode.from_dict(raw))
                    except Exception:
                        continue

        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
