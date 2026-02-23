"""
Departure Time Store — Phase 7 Plan 02

Thread-safe store mapping vehicle_name -> departure datetime with JSON file
persistence. Companion function parse_departure_time() handles German-language
departure time expressions for both inline button responses and free text.

Persistence path: /data/smartprice_departure_times.json
(mirrors ManualSocStore pattern from state.py)
"""

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from logging_util import log


# =============================================================================
# German departure time parser
# =============================================================================

def parse_departure_time(text: str, now: datetime) -> Optional[datetime]:
    """Parse a German-language departure time expression.

    Handles:
      - "in 2h" / "in 2 Stunden" / "in 3 std"         -> now + N hours
      - "in 2,5 Stunden" / "in 2.5h"                   -> now + 2.5 hours
      - "um 14:30" / "um 14 Uhr"                        -> today at 14:30 (tomorrow if passed)
      - "morgen frueh" / "morgen früh" / "morgen"       -> tomorrow at 07:00
      - Inline shorthand: "2h", "4h", "8h", "morgen"   -> same as above

    Returns None for unparseable input.
    All datetimes returned are timezone-aware (UTC).
    """
    if not text:
        return None

    t = text.strip().lower()

    # --- 1. "morgen frueh" / "morgen früh" / "morgen" ---
    # Accepts: "morgen", "morgen frueh", "morgen früh", "morgen fruh"
    if re.match(r"^morgen(\s+(frueh|fr[uü]h))?$", t):
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=7, minute=0, second=0, microsecond=0)

    # --- 2. "in Nh" / "in N Stunden" / "in N std" (including decimals) ---
    # Accepts: "in 2h", "in 2 h", "in 2 stunden", "in 2 std", "in 2,5 stunden", "in 2.5h"
    m = re.match(
        r"^in\s+(\d+(?:[.,]\d+)?)\s*(?:h|stunden?|std)$",
        t,
    )
    if m:
        hours_str = m.group(1).replace(",", ".")
        try:
            hours = float(hours_str)
            return now + timedelta(hours=hours)
        except ValueError:
            pass

    # --- 3. Bare shorthand: "2h", "4h", "8h", "12h" etc. ---
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s*h$", t)
    if m:
        hours_str = m.group(1).replace(",", ".")
        try:
            hours = float(hours_str)
            return now + timedelta(hours=hours)
        except ValueError:
            pass

    # --- 4. "um 14:30" / "um 14:30 Uhr" / "um 14 Uhr" ---
    # Also accepts bare "14:30" without "um" prefix
    m = re.match(
        r"^(?:um\s+)?(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?$",
        t,
    )
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate

    return None


# =============================================================================
# DepartureTimeStore
# =============================================================================

class DepartureTimeStore:
    """Thread-safe per-vehicle departure time store with JSON persistence.

    Stores ISO-format departure strings so they survive JSON serialization and
    add-on restarts. Falls back to config default_hour when no (or expired)
    departure is stored.

    Pending inquiry tracking: mark_inquiry_sent() + is_inquiry_pending() provide
    30-minute timeout logic so the main loop never spams the driver.
    """

    def __init__(
        self,
        default_hour: int = 6,
        persist_path: str = "/data/smartprice_departure_times.json",
    ):
        self._lock = threading.Lock()
        self._times: Dict[str, str] = {}          # vehicle_name -> ISO datetime string
        self._default_hour = default_hour
        self._persist_path = persist_path
        self._pending_inquiries: Dict[str, datetime] = {}  # vehicle -> sent_at (UTC)
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, vehicle_name: str, departure: datetime) -> None:
        """Store a confirmed departure datetime for vehicle_name.

        Converts to UTC if naive, then persists to JSON.
        Also removes any pending-inquiry record (driver has responded).
        """
        with self._lock:
            if departure.tzinfo is None:
                departure = departure.replace(tzinfo=timezone.utc)
            self._times[vehicle_name] = departure.isoformat()
            self._pending_inquiries.pop(vehicle_name, None)
            self._save()
        log("info", f"DepartureStore: {vehicle_name} -> {departure.strftime('%Y-%m-%d %H:%M UTC')}")

    def get(self, vehicle_name: str) -> datetime:
        """Return the stored departure time for vehicle_name if still in the future.

        Falls back to the next occurrence of default_hour (today or tomorrow)
        when no stored departure exists or it has already passed.
        """
        now = datetime.now(timezone.utc)
        with self._lock:
            iso = self._times.get(vehicle_name)
            if iso:
                try:
                    stored = datetime.fromisoformat(iso)
                    if stored.tzinfo is None:
                        stored = stored.replace(tzinfo=timezone.utc)
                    if stored > now:
                        return stored
                except (ValueError, TypeError):
                    pass
            # Fallback: next occurrence of default_hour
            return self._next_default(now)

    def clear(self, vehicle_name: str) -> None:
        """Remove stored departure time for vehicle_name and persist."""
        with self._lock:
            self._times.pop(vehicle_name, None)
            self._pending_inquiries.pop(vehicle_name, None)
            self._save()
        log("info", f"DepartureStore: cleared departure for {vehicle_name}")

    def mark_inquiry_sent(self, vehicle_name: str) -> None:
        """Record that a departure inquiry was just sent for vehicle_name."""
        with self._lock:
            self._pending_inquiries[vehicle_name] = datetime.now(timezone.utc)

    def is_inquiry_pending(self, vehicle_name: str) -> bool:
        """Return True if an inquiry was sent within the last 30 minutes.

        If the inquiry is older than 30 minutes, removes it (timeout) and
        returns False so the next plug-in cycle can ask again.
        """
        with self._lock:
            sent_at = self._pending_inquiries.get(vehicle_name)
            if sent_at is None:
                return False
            age = (datetime.now(timezone.utc) - sent_at).total_seconds()
            if age > 1800:  # 30 minutes
                del self._pending_inquiries[vehicle_name]
                return False
            return True

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load departure times from JSON file on startup."""
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._times = {str(k): str(v) for k, v in data.items()}
            log("info", f"DepartureStore: loaded {len(self._times)} entries from {self._persist_path}")
        except FileNotFoundError:
            self._times = {}
        except (json.JSONDecodeError, Exception) as e:
            log("warning", f"DepartureStore: could not load {self._persist_path}: {e} — starting empty")
            self._times = {}

    def _save(self) -> None:
        """Write departure times to JSON file. Non-critical — errors are logged."""
        try:
            dir_path = os.path.dirname(self._persist_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(self._times, f, indent=2)
        except Exception as e:
            log("warning", f"DepartureStore: could not save to {self._persist_path}: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_default(self, now: datetime) -> datetime:
        """Compute next occurrence of default_hour (today or tomorrow)."""
        candidate = now.replace(
            hour=self._default_hour, minute=0, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
