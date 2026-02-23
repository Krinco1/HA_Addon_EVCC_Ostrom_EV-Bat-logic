"""
OverrideManager — Phase 7 Driver Interaction

Thread-safe driver override for immediate EV charging.

Drivers can trigger "Boost Charge" from the dashboard or Telegram to bypass
the LP planner and charge immediately. The override auto-expires after
OVERRIDE_DURATION_MINUTES (90 min), and quiet hours block activation.

Design:
  - activate(vehicle_name, source, chat_id) → immediately sets evcc to 'now' mode
  - cancel()  → clears override; main loop restores LP-controlled mode next cycle
  - get_status() → returns current override state (for API and main loop)
  - _on_expiry() → timer callback; logs expiry, notifies driver via Telegram
  - _is_quiet(now) → reuses ChargeSequencer's quiet-hours logic
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from logging_util import log


OVERRIDE_DURATION_MINUTES = 90


@dataclass
class ActiveOverride:
    vehicle_name: str
    activated_at: datetime
    expires_at: datetime
    activated_by: str  # "dashboard" | "telegram"


class OverrideManager:
    """Thread-safe boost-charge override for the LP planner."""

    def __init__(self, cfg, evcc, notifier=None):
        self.cfg = cfg
        self.evcc = evcc
        self.notifier = notifier

        self._lock = threading.Lock()
        self._active: Optional[ActiveOverride] = None
        self._expiry_timer: Optional[threading.Timer] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def activate(self, vehicle_name: str, source: str, chat_id: int = None) -> dict:
        """Activate boost-charge override for vehicle_name.

        Returns dict with ok, and on quiet-hours block: quiet_hours_blocked=True.
        Last-activated-wins: a new Boost replaces an existing one for any vehicle.
        """
        now = datetime.now()

        # Quiet hours guard
        if self._is_quiet(now):
            end_hour = getattr(self.cfg, "quiet_hours_end", 6)
            end_str = f"{end_hour:02d}:00"
            msg = f"Leise-Stunden aktiv, Laden startet um {end_str}"
            log("info", f"OverrideManager: Boost blocked by quiet hours for {vehicle_name}")
            if chat_id and self.notifier:
                try:
                    self.notifier.bot.send_message(chat_id, f"Boost Charge blockiert: {msg}")
                except Exception as e:
                    log("warning", f"OverrideManager: could not send quiet-hours Telegram message: {e}")
            return {"ok": False, "quiet_hours_blocked": True, "message": msg}

        expires = now + timedelta(minutes=OVERRIDE_DURATION_MINUTES)

        with self._lock:
            # Cancel any existing timer (last-activated-wins)
            if self._active is not None:
                old = self._active.vehicle_name
                log("info", f"OverrideManager: replacing active override for {old} with {vehicle_name}")
            if self._expiry_timer is not None:
                self._expiry_timer.cancel()
                self._expiry_timer = None

            self._active = ActiveOverride(
                vehicle_name=vehicle_name,
                activated_at=now,
                expires_at=expires,
                activated_by=source,
            )

            timer = threading.Timer(
                OVERRIDE_DURATION_MINUTES * 60,
                self._on_expiry,
            )
            timer.daemon = True
            timer.start()
            self._expiry_timer = timer

        # Set evcc loadpoint to immediate charging
        try:
            self.evcc.set_loadpoint_mode(1, "now")
            log("info", f"OverrideManager: Boost activated for {vehicle_name} by {source}, expires {expires.isoformat()}")
        except Exception as e:
            log("warning", f"OverrideManager: evcc.set_loadpoint_mode failed: {e}")

        return {
            "ok": True,
            "vehicle": vehicle_name,
            "expires_at": expires.isoformat(),
            "remaining_minutes": OVERRIDE_DURATION_MINUTES,
        }

    def cancel(self) -> dict:
        """Cancel the active override, if any.

        Does NOT call evcc — the main loop detects override cleared and
        restores LP-controlled mode on its next cycle.
        """
        with self._lock:
            if self._active is None:
                return {"ok": False, "message": "Kein aktiver Override"}

            vehicle_name = self._active.vehicle_name
            self._active = None

            if self._expiry_timer is not None:
                self._expiry_timer.cancel()
                self._expiry_timer = None

        log("info", f"OverrideManager: override cancelled for {vehicle_name}")
        return {"ok": True, "cancelled": vehicle_name}

    def get_status(self) -> dict:
        """Return current override state.

        Returns:
          {"active": False}
          or
          {"active": True, "vehicle": ..., "expires_at": ...,
           "remaining_minutes": ..., "activated_by": ...}
        """
        with self._lock:
            if self._active is None:
                return {"active": False}

            now = datetime.now()
            remaining = max(0, (self._active.expires_at - now).total_seconds() / 60)
            return {
                "active": True,
                "vehicle": self._active.vehicle_name,
                "expires_at": self._active.expires_at.isoformat(),
                "remaining_minutes": round(remaining, 1),
                "activated_by": self._active.activated_by,
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_expiry(self):
        """Called by threading.Timer when the override duration elapses."""
        vehicle_name = None
        with self._lock:
            if self._active is not None:
                vehicle_name = self._active.vehicle_name
            self._active = None
            self._expiry_timer = None

        if vehicle_name:
            log("info", f"OverrideManager: Boost expired for {vehicle_name} — Planer übernimmt wieder")

            # Notify all drivers via Telegram
            if self.notifier:
                msg = f"Boost Charge für {vehicle_name} abgelaufen — Planer übernimmt wieder."
                try:
                    drivers = self.notifier.drivers.get_all_drivers()
                    for driver in drivers:
                        if driver.telegram_chat_id:
                            self.notifier.bot.send_message(driver.telegram_chat_id, msg)
                except Exception as e:
                    log("warning", f"OverrideManager: expiry notification failed: {e}")

    def _is_quiet(self, now: datetime) -> bool:
        """Return True if current local time falls within configured quiet hours.

        Handles overnight wrap (e.g. 22:00–06:00): quiet when hour >= start OR hour < end.
        Returns False if cfg has no quiet_hours_start attribute.
        """
        if not hasattr(self.cfg, "quiet_hours_start"):
            return False
        if not getattr(self.cfg, "quiet_hours_enabled", False):
            return False

        h = now.hour
        s = self.cfg.quiet_hours_start
        e = self.cfg.quiet_hours_end

        if s > e:
            # Overnight: quiet from s to midnight AND from midnight to e
            return h >= s or h < e
        else:
            return s <= h < e
