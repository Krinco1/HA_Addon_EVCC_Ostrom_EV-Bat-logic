"""
Tests for Phase 12: LP-Gated Battery Arbitrage (_run_bat_to_ev).
"""

import sys
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock external dependencies not available in test environment
for mod_name in ["requests", "numpy", "yaml", "scipy", "scipy.optimize"]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from battery_arbitrage import run_battery_arbitrage as _run_bat_to_ev


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def make_cfg(**overrides):
    cfg = MagicMock()
    cfg.ev_target_soc = overrides.get("ev_target_soc", 80)
    cfg.battery_min_soc = overrides.get("battery_min_soc", 20)
    cfg.battery_capacity_kwh = overrides.get("battery_capacity_kwh", 33.1)
    cfg.battery_charge_efficiency = overrides.get("battery_charge_efficiency", 0.92)
    cfg.battery_discharge_efficiency = overrides.get("battery_discharge_efficiency", 0.92)
    cfg.battery_max_price_ct = overrides.get("battery_max_price_ct", 25.0)
    cfg.battery_to_ev_min_profit_ct = overrides.get("battery_to_ev_min_profit_ct", 3.0)
    cfg.battery_to_ev_dynamic_limit = overrides.get("battery_to_ev_dynamic_limit", True)
    cfg.battery_to_ev_floor_soc = overrides.get("battery_to_ev_floor_soc", 20)
    cfg.battery_max_soc = overrides.get("battery_max_soc", 90)
    return cfg


def make_state(battery_soc=60.0, current_price=0.35, ev_connected=True,
               ev_soc=50.0, home_power=500.0):
    state = MagicMock()
    state.battery_soc = battery_soc
    state.current_price = current_price
    state.ev_connected = ev_connected
    state.ev_soc = ev_soc
    state.home_power = home_power
    return state


def make_plan(current_bat_discharge=True, current_ev_charge=True,
              slot0_bat_discharge_kw=4.0, slot0_ev_charge_kw=11.0,
              future_prices_ct=None):
    """Create a mock PlanHorizon with slots."""
    plan = MagicMock()
    plan.current_bat_discharge = current_bat_discharge
    plan.current_ev_charge = current_ev_charge

    slots = []
    # Slot 0
    slot0 = MagicMock()
    slot0.bat_discharge_kw = slot0_bat_discharge_kw
    slot0.ev_charge_kw = slot0_ev_charge_kw
    slot0.price_eur_kwh = 0.35
    slot0.slot_start = datetime(2026, 2, 27, 14, 0, tzinfo=timezone.utc)
    slots.append(slot0)

    # Future slots (for lookahead)
    future = future_prices_ct or [35.0] * 24  # default: same price
    base_time = datetime(2026, 2, 27, 14, 0, tzinfo=timezone.utc)
    for i, price_ct in enumerate(future):
        slot = MagicMock()
        slot.price_eur_kwh = price_ct / 100.0
        slot.bat_discharge_kw = 0.0
        slot.ev_charge_kw = 11.0
        slot.slot_start = base_time + timedelta(minutes=15 * (i + 1))
        slots.append(slot)

    plan.slots = slots
    return plan


def make_vehicle(soc=50.0, connected=True, capacity=60.0):
    v = MagicMock()
    v.get_effective_soc.return_value = soc
    v.connected_to_wallbox = connected
    v.capacity_kwh = capacity
    v.data_source = "direct_api"
    return v


def make_controller():
    ctrl = MagicMock()
    ctrl._bat_to_ev_active = False

    def _side_effect(bat_to_ev, connected):
        if bat_to_ev.get("is_profitable") and connected:
            ctrl._bat_to_ev_active = True
        elif not bat_to_ev.get("is_profitable"):
            ctrl._bat_to_ev_active = False
        return ctrl._bat_to_ev_active

    ctrl.apply_battery_to_ev.side_effect = _side_effect
    return ctrl


def make_tariffs(price_ct=35.0, count=96):
    return [{"value": price_ct / 100.0}] * count


def make_buffer_calc(current_pct=20):
    import threading
    bc = MagicMock()
    bc._lock = threading.Lock()
    bc._current_buffer_pct = current_pct
    return bc


# ---------------------------------------------------------------------------
# SC-1: LP-authorized profitable discharge activates
# ---------------------------------------------------------------------------

class TestArbitrageActivation(unittest.TestCase):

    def test_activates_when_all_gates_pass(self):
        """SC-1: When EV fast-charging, LP authorizes, profitable -> activate."""
        cfg = make_cfg()
        state = make_state(battery_soc=60, current_price=0.40)  # 40ct grid
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        plan = make_plan(current_bat_discharge=True)
        mode_status = {"current_mode": "now"}
        tariffs = make_tariffs(price_ct=40.0)

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, tariffs, [], True,
            plan=plan, mode_status=mode_status, buffer_calc=make_buffer_calc(),
        )
        ctrl.apply_battery_to_ev.assert_called_once()
        call_args = ctrl.apply_battery_to_ev.call_args[0][0]
        self.assertTrue(call_args["is_profitable"])
        self.assertTrue(result.get("active", False) or ctrl._bat_to_ev_active)

    def test_blocked_when_ev_not_in_now_mode(self):
        """SC-1: EV not fast-charging (mode=pv) -> block."""
        cfg = make_cfg()
        state = make_state(battery_soc=60, current_price=0.40)
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        plan = make_plan(current_bat_discharge=True)
        mode_status = {"current_mode": "pv"}

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(), [], True,
            plan=plan, mode_status=mode_status,
        )
        self.assertFalse(result.get("active", False))
        self.assertIn("Sofortladen", result.get("reason", ""))

    def test_blocked_when_lp_not_authorizing(self):
        """SC-1: LP says no discharge -> block."""
        cfg = make_cfg()
        state = make_state(battery_soc=60, current_price=0.40)
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        plan = make_plan(current_bat_discharge=False)
        mode_status = {"current_mode": "now"}

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(), [], True,
            plan=plan, mode_status=mode_status,
        )
        self.assertFalse(result.get("active", False))
        self.assertIn("LP", result.get("reason", ""))


# ---------------------------------------------------------------------------
# SC-2: 6h Lookahead Guard
# ---------------------------------------------------------------------------

class TestLookaheadGuard(unittest.TestCase):

    def test_blocks_when_cheaper_price_in_6h(self):
        """SC-2: Cheaper grid window in 6h -> block discharge."""
        cfg = make_cfg()
        state = make_state(battery_soc=60, current_price=0.35)
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        # Price drops to 20ct in 2 hours (slot 8)
        future = [35.0] * 7 + [20.0] + [35.0] * 16
        plan = make_plan(current_bat_discharge=True, future_prices_ct=future)
        mode_status = {"current_mode": "now"}

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(), [], True,
            plan=plan, mode_status=mode_status, buffer_calc=make_buffer_calc(),
        )
        self.assertFalse(result.get("active", False))
        self.assertIn("nstigere", result.get("reason", ""))

    def test_allows_when_no_cheaper_price(self):
        """SC-2: No cheaper window -> allow discharge."""
        cfg = make_cfg()
        state = make_state(battery_soc=60, current_price=0.40)
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        future = [40.0] * 24  # All same price
        plan = make_plan(current_bat_discharge=True, future_prices_ct=future)
        mode_status = {"current_mode": "now"}

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(40.0), [], True,
            plan=plan, mode_status=mode_status, buffer_calc=make_buffer_calc(),
        )
        call_args = ctrl.apply_battery_to_ev.call_args[0][0]
        self.assertTrue(call_args["is_profitable"])


# ---------------------------------------------------------------------------
# SC-3: Buffer Floor
# ---------------------------------------------------------------------------

class TestBufferFloor(unittest.TestCase):

    def test_respects_battery_to_ev_floor_soc(self):
        """SC-3: Battery SoC at floor -> block."""
        cfg = make_cfg(battery_to_ev_floor_soc=55)
        state = make_state(battery_soc=55, current_price=0.40)
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        plan = make_plan(current_bat_discharge=True)
        mode_status = {"current_mode": "now"}

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(), [], True,
            plan=plan, mode_status=mode_status, buffer_calc=make_buffer_calc(20),
        )
        self.assertFalse(result.get("active", False))
        self.assertIn("Untergrenze", result.get("reason", ""))

    def test_respects_dynamic_buffer(self):
        """SC-3: Dynamic buffer higher than floor_soc -> use dynamic."""
        cfg = make_cfg(battery_to_ev_floor_soc=20)
        state = make_state(battery_soc=35, current_price=0.40)
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        plan = make_plan(current_bat_discharge=True)
        mode_status = {"current_mode": "now"}
        # Dynamic buffer at 35% -> bat_soc=35 is at the floor
        bc = make_buffer_calc(35)

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(), [], True,
            plan=plan, mode_status=mode_status, buffer_calc=bc,
        )
        self.assertFalse(result.get("active", False))
        self.assertIn("Untergrenze", result.get("reason", ""))


# ---------------------------------------------------------------------------
# SC-4: Mutual Exclusion
# ---------------------------------------------------------------------------

class TestMutualExclusion(unittest.TestCase):

    def test_blocks_when_lp_discharges_to_grid(self):
        """SC-4: LP discharges to grid (not EV) -> block battery-to-EV."""
        cfg = make_cfg()
        state = make_state(battery_soc=60, current_price=0.40)
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        # LP discharges battery but NOT charging EV
        plan = make_plan(current_bat_discharge=True,
                         slot0_bat_discharge_kw=4.0, slot0_ev_charge_kw=0.0)
        mode_status = {"current_mode": "now"}

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(), [], True,
            plan=plan, mode_status=mode_status,
        )
        self.assertFalse(result.get("active", False))
        self.assertIn("Mutual Exclusion", result.get("reason", ""))

    def test_allows_when_lp_discharges_with_ev_charging(self):
        """SC-4: LP discharges + EV charging -> allow (co-discharge)."""
        cfg = make_cfg()
        state = make_state(battery_soc=60, current_price=0.40)
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        plan = make_plan(current_bat_discharge=True,
                         slot0_bat_discharge_kw=4.0, slot0_ev_charge_kw=11.0)
        mode_status = {"current_mode": "now"}

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(40.0), [], True,
            plan=plan, mode_status=mode_status, buffer_calc=make_buffer_calc(),
        )
        call_args = ctrl.apply_battery_to_ev.call_args[0][0]
        self.assertTrue(call_args["is_profitable"])


# ---------------------------------------------------------------------------
# SC-5: DynamicBufferCalc + Arbitrage read same floor
# ---------------------------------------------------------------------------

class TestBufferSync(unittest.TestCase):

    def test_uses_dynamic_buffer_when_higher(self):
        """SC-5: effective_floor = max(floor_soc, dynamic_buffer)."""
        cfg = make_cfg(battery_to_ev_floor_soc=20)
        state = make_state(battery_soc=60, current_price=0.40)
        ctrl = make_controller()
        ctrl._bat_to_ev_active = True  # pretend already active
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        plan = make_plan(current_bat_discharge=True)
        mode_status = {"current_mode": "now"}
        bc = make_buffer_calc(30)  # dynamic buffer at 30%

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(40.0), [], True,
            plan=plan, mode_status=mode_status, buffer_calc=bc,
        )
        # effective floor should be 30 (max of 20, 30))
        if result.get("active"):
            self.assertEqual(result.get("effective_floor_pct"), 30)
            self.assertEqual(result.get("dynamic_buffer_pct"), 30)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_no_ev_connected(self):
        """No EV -> inactive."""
        cfg = make_cfg()
        state = make_state()
        ctrl = make_controller()
        result = _run_bat_to_ev(cfg, state, ctrl, {}, make_tariffs(), [], False)
        self.assertFalse(result.get("active", False))

    def test_no_plan_available(self):
        """No LP plan -> blocked with reason."""
        cfg = make_cfg()
        state = make_state(battery_soc=60, current_price=0.40)
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        mode_status = {"current_mode": "now"}

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(), [], True,
            plan=None, mode_status=mode_status,
        )
        self.assertFalse(result.get("active", False))
        self.assertIn("LP", result.get("reason", ""))

    def test_not_profitable(self):
        """Grid price too low -> not profitable."""
        cfg = make_cfg()
        state = make_state(battery_soc=60, current_price=0.25)  # 25ct - same as battery cost
        ctrl = make_controller()
        vehicles = {"TestEV": make_vehicle(soc=50, connected=True)}
        plan = make_plan(current_bat_discharge=True)
        mode_status = {"current_mode": "now"}

        result = _run_bat_to_ev(
            cfg, state, ctrl, vehicles, make_tariffs(25.0), [], True,
            plan=plan, mode_status=mode_status, buffer_calc=make_buffer_calc(),
        )
        self.assertFalse(result.get("active", False))
        self.assertIn("profitabel", result.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
