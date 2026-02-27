"""
Tests for EvccModeController — Phase 11 evcc Mode Control + Override Detection.

TDD RED phase: tests written before implementation.
"""

import sys
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock external dependencies not available in test environment
for mod_name in ["requests", "numpy", "yaml", "scipy", "scipy.optimize"]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from evcc_mode_controller import EvccModeController


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def make_config(**overrides):
    cfg = MagicMock()
    cfg.ev_target_soc = overrides.get("ev_target_soc", 80)
    cfg.ev_max_price_ct = overrides.get("ev_max_price_ct", 30.0)
    return cfg


def make_state(ev_connected=True, ev_soc=50.0, current_price=0.20,
               percentiles=None, ev_name="TestEV", ev_capacity_kwh=60.0,
               ev_charge_power_kw=11.0):
    state = MagicMock()
    state.ev_connected = ev_connected
    state.ev_soc = ev_soc
    state.current_price = current_price
    state.price_percentiles = percentiles or {20: 0.10, 30: 0.15, 40: 0.20, 60: 0.25, 80: 0.35}
    state.ev_name = ev_name
    state.ev_capacity_kwh = ev_capacity_kwh
    state.ev_charge_power_kw = ev_charge_power_kw
    return state


def make_plan(current_ev_charge=True, price_eur_kwh=0.15):
    plan = MagicMock()
    plan.current_ev_charge = current_ev_charge
    plan.current_price_limit = price_eur_kwh
    slot0 = MagicMock()
    slot0.price_eur_kwh = price_eur_kwh
    slot0.ev_charge_kw = 11.0 if current_ev_charge else 0.0
    plan.slots = [slot0]
    return plan


def make_evcc_state(mode="pv", connected=True, vehicle_soc=50):
    return {
        "loadpoints": [
            {
                "mode": mode,
                "connected": connected,
                "vehicleSoc": vehicle_soc,
                "vehicleName": "TestEV",
            }
        ]
    }


# ---------------------------------------------------------------------------
# Mode Selection Tests (MODE-01, MODE-02)
# ---------------------------------------------------------------------------

class TestDecideMode(unittest.TestCase):

    def setUp(self):
        self.evcc = MagicMock()
        self.cfg = make_config()
        self.ctrl = EvccModeController(self.evcc, self.cfg)

    def test_decide_mode_cheap_price_returns_now(self):
        """When current price <= P30, and LP says charge, return 'now'."""
        state = make_state(current_price=0.10, percentiles={20: 0.08, 30: 0.12, 60: 0.25, 80: 0.35})
        plan = make_plan(current_ev_charge=True, price_eur_kwh=0.10)
        mode = self.ctrl.decide_mode(state, plan)
        self.assertEqual(mode, "now")

    def test_decide_mode_moderate_price_returns_minpv(self):
        """When P30 < current price <= P60, and LP says charge, return 'minpv'."""
        state = make_state(current_price=0.20, percentiles={20: 0.08, 30: 0.12, 60: 0.25, 80: 0.35})
        plan = make_plan(current_ev_charge=True, price_eur_kwh=0.20)
        mode = self.ctrl.decide_mode(state, plan)
        self.assertEqual(mode, "minpv")

    def test_decide_mode_expensive_price_returns_pv(self):
        """When current price > P60, return 'pv'."""
        state = make_state(current_price=0.30, percentiles={20: 0.08, 30: 0.12, 60: 0.25, 80: 0.35})
        plan = make_plan(current_ev_charge=True, price_eur_kwh=0.30)
        mode = self.ctrl.decide_mode(state, plan)
        self.assertEqual(mode, "pv")

    def test_decide_mode_urgency_override_returns_now(self):
        """When departure is urgent, return 'now' regardless of price."""
        state = make_state(current_price=0.35)
        plan = make_plan(current_ev_charge=False, price_eur_kwh=0.35)
        mode = self.ctrl.decide_mode(state, plan, departure_urgent=True)
        self.assertEqual(mode, "now")

    def test_decide_mode_no_ev_connected_returns_pv(self):
        """When no EV connected, return 'pv'."""
        state = make_state(ev_connected=False)
        plan = make_plan(current_ev_charge=False)
        mode = self.ctrl.decide_mode(state, plan)
        self.assertEqual(mode, "pv")

    def test_decide_mode_ev_at_target_soc_returns_pv(self):
        """When EV SoC >= target SoC, return 'pv' (fully charged)."""
        state = make_state(ev_soc=85.0)  # target is 80
        plan = make_plan(current_ev_charge=False)
        mode = self.ctrl.decide_mode(state, plan)
        self.assertEqual(mode, "pv")

    def test_decide_mode_no_plan_returns_pv(self):
        """When no LP plan available, fallback to 'pv'."""
        state = make_state()
        mode = self.ctrl.decide_mode(state, None)
        self.assertEqual(mode, "pv")

    def test_decide_mode_plan_says_no_charge_returns_pv(self):
        """When LP plan says don't charge EV, return 'pv'."""
        state = make_state(current_price=0.10)
        plan = make_plan(current_ev_charge=False)
        mode = self.ctrl.decide_mode(state, plan)
        self.assertEqual(mode, "pv")

    def test_decide_mode_empty_percentiles_uses_max_price(self):
        """When no percentiles available, fall back to ev_max_price comparison."""
        state = make_state(current_price=0.20, percentiles={})
        plan = make_plan(current_ev_charge=True, price_eur_kwh=0.20)
        # With ev_max_price_ct=30 (0.30 EUR/kWh), 0.20 is cheap → "now"
        mode = self.ctrl.decide_mode(state, plan)
        self.assertIn(mode, ["now", "minpv"])


# ---------------------------------------------------------------------------
# Mode Application Tests
# ---------------------------------------------------------------------------

class TestApplyMode(unittest.TestCase):

    def setUp(self):
        self.evcc = MagicMock()
        self.evcc.set_loadpoint_mode.return_value = True
        self.cfg = make_config()
        self.ctrl = EvccModeController(self.evcc, self.cfg)

    def test_apply_mode_sends_command_when_mode_changes(self):
        """set_loadpoint_mode called when target differs from current."""
        self.ctrl._apply_mode("now", "pv")
        self.evcc.set_loadpoint_mode.assert_called_once_with(0, "now")

    def test_apply_mode_skips_when_mode_unchanged(self):
        """set_loadpoint_mode NOT called when target == current."""
        self.ctrl._apply_mode("pv", "pv")
        self.evcc.set_loadpoint_mode.assert_not_called()

    def test_apply_mode_updates_last_set_mode(self):
        """_last_set_mode updated after successful mode command."""
        self.ctrl._apply_mode("now", "pv")
        self.assertEqual(self.ctrl._last_set_mode, "now")

    def test_apply_mode_no_update_on_failure(self):
        """_last_set_mode NOT updated if evcc rejects the command."""
        self.evcc.set_loadpoint_mode.return_value = False
        self.ctrl._apply_mode("now", "pv")
        self.assertIsNone(self.ctrl._last_set_mode)


# ---------------------------------------------------------------------------
# Override Detection Tests (MODE-03)
# ---------------------------------------------------------------------------

class TestOverrideDetection(unittest.TestCase):

    def setUp(self):
        self.evcc = MagicMock()
        self.evcc.set_loadpoint_mode.return_value = True
        self.cfg = make_config()
        self.ctrl = EvccModeController(self.evcc, self.cfg)

    def test_check_override_detects_manual_change(self):
        """evcc mode differs from last SmartLoad-set mode → override detected."""
        self.ctrl._last_set_mode = "pv"
        self.ctrl._startup_complete = True
        override = self.ctrl._check_override("now")
        self.assertTrue(override)

    def test_check_override_no_false_positive_when_smartload_changed(self):
        """Mode matches _last_set_mode → no override."""
        self.ctrl._last_set_mode = "pv"
        self.ctrl._startup_complete = True
        override = self.ctrl._check_override("pv")
        self.assertFalse(override)

    def test_check_override_no_detection_when_no_prior_mode(self):
        """_last_set_mode is None (startup) → no override."""
        self.ctrl._last_set_mode = None
        override = self.ctrl._check_override("now")
        self.assertFalse(override)


# ---------------------------------------------------------------------------
# Override Lifecycle Tests (MODE-04)
# ---------------------------------------------------------------------------

class TestOverrideLifecycle(unittest.TestCase):

    def setUp(self):
        self.evcc = MagicMock()
        self.evcc.set_loadpoint_mode.return_value = True
        self.cfg = make_config()
        self.ctrl = EvccModeController(self.evcc, self.cfg)

    def _activate_override(self):
        """Helper: put controller into override state."""
        self.ctrl._override_active = True
        self.ctrl._override_mode = "now"
        self.ctrl._override_since = datetime.now(timezone.utc)
        self.ctrl._last_set_mode = "pv"
        self.ctrl._startup_complete = True

    def test_override_persists_while_ev_connected(self):
        """Override stays active when EV is still connected and below target SoC."""
        self._activate_override()
        state = make_state(ev_connected=True, ev_soc=50.0)
        evcc_state = make_evcc_state(mode="now", connected=True)

        result = self.ctrl.step(state, make_plan(), evcc_state)
        self.assertTrue(result.get("override_active", False))

    def test_override_ends_on_ev_disconnect(self):
        """Override clears when EV disconnects."""
        self._activate_override()
        state = make_state(ev_connected=False)
        evcc_state = make_evcc_state(mode="now", connected=False)

        result = self.ctrl.step(state, make_plan(), evcc_state)
        self.assertFalse(result.get("override_active", False))
        self.assertFalse(self.ctrl._override_active)

    def test_override_ends_on_target_soc_reached(self):
        """Override clears when EV SoC reaches target."""
        self._activate_override()
        state = make_state(ev_connected=True, ev_soc=85.0)
        evcc_state = make_evcc_state(mode="now", connected=True, vehicle_soc=85)

        result = self.ctrl.step(state, make_plan(), evcc_state)
        self.assertFalse(result.get("override_active", False))

    def test_mode_control_skipped_during_override(self):
        """No mode commands sent while override is active."""
        self._activate_override()
        state = make_state(ev_connected=True, ev_soc=50.0)
        evcc_state = make_evcc_state(mode="now", connected=True)

        self.ctrl.step(state, make_plan(), evcc_state)
        self.evcc.set_loadpoint_mode.assert_not_called()

    def test_mode_control_resumes_after_override_ends(self):
        """After override clears, mode command is sent on same cycle."""
        self._activate_override()
        state = make_state(ev_connected=False)
        evcc_state = make_evcc_state(mode="now", connected=False)

        self.ctrl.step(state, make_plan(), evcc_state)
        # After disconnect, EV is gone — pv mode, but no command since EV disconnected
        self.assertFalse(self.ctrl._override_active)


# ---------------------------------------------------------------------------
# Startup Behavior Tests
# ---------------------------------------------------------------------------

class TestStartupBehavior(unittest.TestCase):

    def setUp(self):
        self.evcc = MagicMock()
        self.evcc.set_loadpoint_mode.return_value = True
        self.cfg = make_config()
        self.ctrl = EvccModeController(self.evcc, self.cfg)

    def test_startup_adopts_current_mode(self):
        """First cycle: reads evcc mode, adopts as baseline, no command sent."""
        self.assertFalse(self.ctrl._startup_complete)

        state = make_state()
        evcc_state = make_evcc_state(mode="minpv", connected=True)
        result = self.ctrl.step(state, make_plan(), evcc_state)

        self.assertTrue(self.ctrl._startup_complete)
        self.assertEqual(self.ctrl._last_set_mode, "minpv")
        self.evcc.set_loadpoint_mode.assert_not_called()

    def test_startup_evcc_unreachable(self):
        """evcc unreachable on startup → graceful handling, no crash."""
        state = make_state()
        result = self.ctrl.step(state, make_plan(), None)

        self.assertFalse(self.ctrl._startup_complete)
        self.assertFalse(result.get("evcc_reachable", True))
        self.evcc.set_loadpoint_mode.assert_not_called()

    def test_startup_evcc_no_loadpoints(self):
        """evcc reachable but no loadpoints → graceful handling."""
        state = make_state()
        result = self.ctrl.step(state, make_plan(), {"loadpoints": []})

        self.assertFalse(self.ctrl._startup_complete)
        self.evcc.set_loadpoint_mode.assert_not_called()


# ---------------------------------------------------------------------------
# Status Reporting Tests
# ---------------------------------------------------------------------------

class TestGetStatus(unittest.TestCase):

    def setUp(self):
        self.evcc = MagicMock()
        self.cfg = make_config()
        self.ctrl = EvccModeController(self.evcc, self.cfg)

    def test_get_status_no_override(self):
        """Status without override active."""
        self.ctrl._startup_complete = True
        self.ctrl._last_set_mode = "pv"
        status = self.ctrl.get_status()
        self.assertFalse(status["override_active"])
        self.assertTrue(status["evcc_reachable"])

    def test_get_status_with_override(self):
        """Status with override active includes manual mode and timestamp."""
        self.ctrl._startup_complete = True
        self.ctrl._override_active = True
        self.ctrl._override_mode = "now"
        self.ctrl._override_since = datetime(2026, 2, 27, 14, 30, tzinfo=timezone.utc)

        status = self.ctrl.get_status()
        self.assertTrue(status["override_active"])
        self.assertEqual(status["override_mode"], "now")
        self.assertIn("override_since", status)

    def test_get_status_evcc_unreachable(self):
        """Status when evcc has been unreachable."""
        self.ctrl._evcc_unreachable_since = datetime(2026, 2, 27, 14, 0, tzinfo=timezone.utc)
        status = self.ctrl.get_status()
        self.assertFalse(status["evcc_reachable"])
        self.assertIsNotNone(status.get("evcc_unreachable_since"))


# ---------------------------------------------------------------------------
# evcc Unreachable Tracking Tests
# ---------------------------------------------------------------------------

class TestEvccUnreachable(unittest.TestCase):

    def setUp(self):
        self.evcc = MagicMock()
        self.evcc.set_loadpoint_mode.return_value = True
        self.cfg = make_config()
        self.ctrl = EvccModeController(self.evcc, self.cfg)
        self.ctrl._startup_complete = True
        self.ctrl._last_set_mode = "pv"

    def test_tracks_unreachable_since(self):
        """When evcc_state is None, unreachable_since is set."""
        state = make_state()
        result = self.ctrl.step(state, make_plan(), None)
        self.assertIsNotNone(self.ctrl._evcc_unreachable_since)
        self.assertFalse(result.get("evcc_reachable", True))

    def test_clears_unreachable_on_recovery(self):
        """When evcc_state returns, unreachable_since is cleared."""
        self.ctrl._evcc_unreachable_since = datetime.now(timezone.utc) - timedelta(minutes=45)
        state = make_state()
        evcc_state = make_evcc_state(mode="pv", connected=True)
        result = self.ctrl.step(state, make_plan(), evcc_state)
        self.assertIsNone(self.ctrl._evcc_unreachable_since)
        self.assertTrue(result.get("evcc_reachable", False))


if __name__ == "__main__":
    unittest.main()
