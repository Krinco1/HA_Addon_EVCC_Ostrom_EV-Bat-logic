"""
EvccModeController — Phase 11: evcc Mode Control + Override Detection

Controls the evcc charge mode (pv / minpv / now) based on the LP plan,
detects manual user overrides in the evcc UI, and respects them until
the charging session ends.

Design:
  - decide_mode() maps LP plan + price percentiles to evcc mode
  - step() is called each decision cycle from main.py
  - Override detected by comparing last SmartLoad-set mode with current evcc mode
  - Override persists until EV disconnect or target SoC reached
  - On startup: adopts current evcc mode as baseline, no command sent
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from config import Config
from evcc_client import EvccClient
from logging_util import log
from state import PlanHorizon, SystemState


# Threshold in minutes for "evcc unreachable" dashboard warning
_UNREACHABLE_WARN_MINUTES = 30


class EvccModeController:
    """Controls evcc loadpoint mode and detects manual overrides."""

    def __init__(self, evcc: EvccClient, cfg: Config):
        self.evcc = evcc
        self.cfg = cfg

        self._last_set_mode: Optional[str] = None
        self._override_active: bool = False
        self._override_mode: Optional[str] = None
        self._override_since: Optional[datetime] = None
        self._evcc_unreachable_since: Optional[datetime] = None
        self._startup_complete: bool = False
        self._current_mode: Optional[str] = None

    # ------------------------------------------------------------------
    # Mode selection logic (MODE-01, MODE-02)
    # ------------------------------------------------------------------

    def decide_mode(
        self,
        state: SystemState,
        plan: Optional[PlanHorizon],
        departure_urgent: bool = False,
    ) -> str:
        """Determine the target evcc mode from LP plan and price context.

        Returns one of: "now", "minpv", "pv".
        """
        # No EV connected → PV surplus only
        if not state.ev_connected:
            return "pv"

        # EV fully charged → PV surplus only
        if state.ev_soc >= self.cfg.ev_target_soc:
            return "pv"

        # Urgency override: departure imminent → charge at full power
        if departure_urgent:
            return "now"

        # No LP plan → conservative fallback
        if plan is None:
            return "pv"

        # LP says don't charge EV this slot → PV surplus only
        if not plan.current_ev_charge:
            return "pv"

        # LP says charge → select mode based on price percentile
        p = state.price_percentiles
        price = state.current_price

        if p:
            p30 = p.get(30, price)
            p60 = p.get(60, price)

            if price <= p30:
                return "now"      # Cheap: charge from grid at full power
            elif price <= p60:
                return "minpv"    # Moderate: grid + PV mix
            else:
                return "pv"       # Expensive: PV surplus only
        else:
            # No percentile data → fallback to ev_max_price comparison
            max_price_eur = self.cfg.ev_max_price_ct / 100.0
            if price <= max_price_eur * 0.5:
                return "now"
            elif price <= max_price_eur * 0.8:
                return "minpv"
            else:
                return "pv"

    # ------------------------------------------------------------------
    # Main per-cycle entry point
    # ------------------------------------------------------------------

    def step(
        self,
        state: SystemState,
        plan: Optional[PlanHorizon],
        evcc_state: Optional[Dict],
        departure_urgent: bool = False,
    ) -> Dict:
        """Execute one mode-control cycle. Called from main decision loop.

        Args:
            state: Current SystemState snapshot
            plan: Current LP plan (or None if LP unavailable)
            evcc_state: Raw evcc /api/state response (reused from DataCollector)
            departure_urgent: True if EV departure is imminent

        Returns:
            Status dict for StateStore/SSE broadcast.
        """
        now = datetime.now(timezone.utc)

        # --- Handle evcc unreachable ---
        if evcc_state is None:
            if self._evcc_unreachable_since is None:
                self._evcc_unreachable_since = now
                log("warning", "EvccModeController: evcc unreachable")
            unreachable_min = (now - self._evcc_unreachable_since).total_seconds() / 60
            if unreachable_min > _UNREACHABLE_WARN_MINUTES:
                since_str = self._evcc_unreachable_since.strftime("%H:%M")
                log("warning", f"EvccModeController: evcc nicht erreichbar seit {since_str}")
            return self.get_status()

        # --- Extract loadpoint data ---
        loadpoints = evcc_state.get("loadpoints", [])
        if not loadpoints:
            log("warning", "EvccModeController: evcc state has no loadpoints")
            return self.get_status()

        lp = loadpoints[0]
        current_evcc_mode = lp.get("mode")
        lp_connected = lp.get("connected", False)

        if current_evcc_mode is None:
            log("warning", "EvccModeController: loadpoint has no mode field")
            return self.get_status()

        # --- evcc recovered ---
        if self._evcc_unreachable_since is not None:
            log("info", "EvccModeController: evcc wieder erreichbar")
            self._evcc_unreachable_since = None

        self._current_mode = current_evcc_mode

        # --- Startup: adopt current mode as baseline ---
        if not self._startup_complete:
            self._last_set_mode = current_evcc_mode
            self._startup_complete = True
            log("info", f"Startup: evcc mode adopted as baseline: {current_evcc_mode}")
            return self.get_status()

        # --- Override lifecycle check ---
        if self._override_active:
            override_ended = False
            reason = ""

            # End condition 1: EV disconnected
            if not state.ev_connected or not lp_connected:
                override_ended = True
                reason = "EV abgekoppelt"

            # End condition 2: Target SoC reached
            elif state.ev_soc >= self.cfg.ev_target_soc:
                override_ended = True
                reason = f"Ziel-SoC {self.cfg.ev_target_soc}% erreicht"

            if override_ended:
                log("info", f"Override beendet ({reason}), SmartLoad übernimmt")
                self._override_active = False
                self._override_mode = None
                self._override_since = None
                self._last_set_mode = None  # Reset so we don't false-detect
                # Don't send mode command this cycle — resume next cycle
                return self.get_status()

            # Override still active — skip mode control
            return self.get_status()

        # --- Override detection ---
        if self._check_override(current_evcc_mode):
            self._override_active = True
            self._override_mode = current_evcc_mode
            self._override_since = now
            log("info", f"Override erkannt — SmartLoad pausiert EV-Modus-Steuerung "
                        f"(manuell: {current_evcc_mode})")
            return self.get_status()

        # --- Mode selection and application ---
        target_mode = self.decide_mode(state, plan, departure_urgent=departure_urgent)
        self._apply_mode(target_mode, current_evcc_mode)

        return self.get_status()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_override(self, current_evcc_mode: str) -> bool:
        """Check if user manually changed the evcc mode.

        Returns True if override detected, False otherwise.
        """
        if self._last_set_mode is None:
            return False
        if not self._startup_complete:
            return False
        return current_evcc_mode != self._last_set_mode

    def _apply_mode(self, target_mode: str, current_mode: str) -> None:
        """Send mode command to evcc if target differs from current."""
        if target_mode == current_mode:
            return

        success = self.evcc.set_loadpoint_mode(0, target_mode)
        if success:
            self._last_set_mode = target_mode
            log("info", f"EvccModeController: mode {current_mode} -> {target_mode}")
        else:
            log("warning", f"EvccModeController: set_loadpoint_mode({target_mode}) failed")

    # ------------------------------------------------------------------
    # Status reporting
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Return current state for dashboard/API/SSE."""
        evcc_reachable = self._evcc_unreachable_since is None
        return {
            "active": self._startup_complete,
            "current_mode": self._current_mode,
            "target_mode": self._last_set_mode,
            "override_active": self._override_active,
            "override_mode": self._override_mode,
            "override_since": self._override_since.isoformat() if self._override_since else None,
            "evcc_reachable": evcc_reachable,
            "evcc_unreachable_since": (
                self._evcc_unreachable_since.isoformat()
                if self._evcc_unreachable_since else None
            ),
            "startup_complete": self._startup_complete,
        }
