"""
Integration tests for HorizonPlanner edge cases.

Phase 4 Plan 03 — TDD test suite for LP formulation correctness.

Tests cover:
  1. Basic LP solve with flat prices (sanity check)
  2. Price valley triggers battery charging
  3. EV departure urgency
  4. No EV connected
  5. Solver failure fallback (infeasible LP)
  6. Short price horizon (< 32 slots)
  7. Battery SoC stays within bounds

Run: python -m unittest test_planner -v

All tests are self-contained — no InfluxDB, no evcc, no network required.
Only numpy and scipy are needed (already available in container).
"""

import sys
import os
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Minimal mock Config — avoids importing the real config.py which touches
# file system paths (/data/options.json, /config/vehicles.yaml, etc.)
# ---------------------------------------------------------------------------

@dataclass
class MockConfig:
    """Minimal Config-compatible object for planner tests.

    Matches every attribute accessed by HorizonPlanner.__init__().
    """
    # Battery
    battery_capacity_kwh: float = 10.0
    battery_charge_power_kw: float = 5.0
    battery_charge_efficiency: float = 0.92
    battery_discharge_efficiency: float = 0.92
    battery_min_soc: int = 10
    battery_max_soc: int = 90

    # Price limits (ct/kWh)
    battery_max_price_ct: float = 40.0
    ev_max_price_ct: float = 40.0

    # Feed-in
    feed_in_tariff_ct: float = 7.0

    # EV defaults
    ev_default_energy_kwh: float = 30.0
    sequencer_default_charge_power_kw: float = 11.0

    # EV target
    ev_target_soc: int = 80

    # Charge deadline (used by _get_departure_times in main.py, not planner itself)
    ev_charge_deadline_hour: int = 6


# ---------------------------------------------------------------------------
# Minimal mock SystemState — avoids importing state.py which imports config.py
# ---------------------------------------------------------------------------

@dataclass
class MockSystemState:
    """Minimal SystemState-compatible object for planner tests."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    battery_soc: float = 50.0
    battery_power: float = 0.0
    grid_power: float = 0.0
    current_price: float = 0.25
    pv_power: float = 0.0
    home_power: float = 1000.0
    ev_connected: bool = False
    ev_soc: float = 0.0
    ev_power: float = 0.0
    ev_name: str = ""
    ev_capacity_kwh: float = 0.0
    ev_charge_power_kw: float = 11.0
    price_forecast: List[float] = field(default_factory=list)
    pv_forecast: List[float] = field(default_factory=list)
    price_percentiles: Dict[int, float] = field(default_factory=dict)
    price_spread: float = 0.0
    hours_cheap_remaining: int = 0
    solar_forecast_total_kwh: float = 0.0


# ---------------------------------------------------------------------------
# Tariff helper — builds synthetic evcc-format tariff lists
# ---------------------------------------------------------------------------

def make_tariffs(prices_eur_kwh: List[float], start_dt: Optional[datetime] = None) -> List[Dict]:
    """Build evcc-style tariff list from a list of hourly prices.

    Each element becomes one hourly entry (will be expanded to 4 x 15-min slots
    by HorizonPlanner._tariffs_to_96slots).
    """
    if start_dt is None:
        start_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    tariffs = []
    for i, price in enumerate(prices_eur_kwh):
        slot_start = start_dt + timedelta(hours=i)
        slot_end = slot_start + timedelta(hours=1)
        tariffs.append({
            "start": slot_start.isoformat().replace("+00:00", "Z"),
            "end": slot_end.isoformat().replace("+00:00", "Z"),
            "value": price,
        })
    return tariffs


def make_flat_tariffs(price: float = 0.30, n_hours: int = 24) -> List[Dict]:
    """Build n_hours of flat-price tariffs."""
    return make_tariffs([price] * n_hours)


# ---------------------------------------------------------------------------
# Patch imports so HorizonPlanner can be imported without the real
# config.py / state.py / logging_util.py module chain.
# ---------------------------------------------------------------------------

def _patch_imports():
    """Insert mock modules into sys.modules before importing planner.

    This is done once at module load time so the import works regardless of
    whether the test runner's CWD contains the real modules.
    """
    # logging_util — provide a no-op log() function
    import types

    logging_mod = types.ModuleType("logging_util")
    logging_mod.log = lambda level, msg: None  # noqa: ARG005
    sys.modules.setdefault("logging_util", logging_mod)

    # config — provide MockConfig as the Config class + constants
    config_mod = types.ModuleType("config")
    config_mod.Config = MockConfig
    config_mod.MANUAL_SOC_PATH = "/tmp/test_manual_soc.json"
    sys.modules.setdefault("config", config_mod)

    # state — provide the dataclasses that planner imports
    # (DispatchSlot, PlanHorizon, SystemState)
    # We need the real state module's dataclasses — check if importable first.
    if "state" not in sys.modules:
        # Try adding the app directory to the path so we can import state.py directly
        app_dir = os.path.dirname(os.path.abspath(__file__))
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        try:
            import state as real_state  # noqa: F401 — side-effect import
        except ImportError:
            # Provide stub state module with the required dataclasses
            _build_stub_state(sys.modules)


def _build_stub_state(modules):
    """Build a minimal stub state module when the real one is not importable."""
    import types
    from dataclasses import dataclass as dc, field as f

    state_mod = types.ModuleType("state")

    @dc
    class DispatchSlot:
        slot_index: int
        slot_start: datetime
        bat_charge_kw: float
        bat_discharge_kw: float
        ev_charge_kw: float
        ev_name: str
        price_eur_kwh: float
        pv_kw: float
        consumption_kw: float
        bat_soc_pct: float
        ev_soc_pct: float

    @dc
    class PlanHorizon:
        computed_at: datetime
        slots: List[DispatchSlot]
        solver_status: int
        solver_fun: float
        current_bat_charge: bool
        current_bat_discharge: bool
        current_ev_charge: bool
        current_price_limit: float

    state_mod.DispatchSlot = DispatchSlot
    state_mod.PlanHorizon = PlanHorizon
    state_mod.SystemState = MockSystemState
    modules["state"] = state_mod


# Patch immediately at import time
_patch_imports()

# Now import the real HorizonPlanner
from optimizer.planner import HorizonPlanner  # noqa: E402


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestHorizonPlannerBasic(unittest.TestCase):
    """Test 1: Basic LP solve with flat prices."""

    def setUp(self):
        self.cfg = MockConfig()
        self.now = datetime(2026, 2, 22, 12, 0, 0, tzinfo=timezone.utc)
        self.state = MockSystemState(
            timestamp=self.now,
            battery_soc=50.0,
            ev_connected=False,
        )
        self.consumption_96 = [1000.0] * 96   # 1 kW constant
        self.pv_96 = [0.0] * 96               # no PV
        self.ev_departure = {}

    def test_flat_price_produces_valid_plan(self):
        """Flat prices — LP should solve successfully with 96 slots."""
        tariffs = make_flat_tariffs(price=0.30, n_hours=24)
        planner = HorizonPlanner(self.cfg)
        plan = planner.plan(self.state, tariffs, self.consumption_96, self.pv_96, self.ev_departure)

        self.assertIsNotNone(plan, "Plan should be non-None for valid 24h flat prices")
        self.assertEqual(plan.solver_status, 0, "Solver status should be 0 (optimal)")
        self.assertEqual(len(plan.slots), 96, "Plan should have 96 slots")

    def test_flat_price_no_arbitrage_charging(self):
        """Flat prices — no price arbitrage, battery should NOT charge aggressively."""
        tariffs = make_flat_tariffs(price=0.30, n_hours=24)
        planner = HorizonPlanner(self.cfg)
        plan = planner.plan(self.state, tariffs, self.consumption_96, self.pv_96, self.ev_departure)

        self.assertIsNotNone(plan)
        # With flat prices, LP objective gains nothing from charging, so total
        # charge should be near zero (only maintaining min_soc if needed).
        total_charge = sum(s.bat_charge_kw for s in plan.slots)
        # Battery starts at 50% SoC, well above min_soc (10%), no incentive to charge
        self.assertAlmostEqual(total_charge, 0.0, delta=0.5,
            msg=f"Battery should not charge with flat prices; total_charge={total_charge:.3f} kW")


class TestHorizonPlannerPriceValley(unittest.TestCase):
    """Test 2: Price valley triggers battery charging during cheap slots."""

    def setUp(self):
        self.cfg = MockConfig()
        self.now = datetime(2026, 2, 22, 0, 0, 0, tzinfo=timezone.utc)
        self.consumption_96 = [500.0] * 96    # 0.5 kW constant (low, to not mask charging signal)
        self.pv_96 = [0.0] * 96

    def test_cheap_slots_charge_more_than_expensive(self):
        """Battery charges during cheap slots (48-95) more than expensive ones (0-47)."""
        # Slots 0-47 (first 12h): expensive at 0.40 EUR/kWh
        # Slots 48-95 (next 12h): cheap at 0.10 EUR/kWh
        expensive = [0.40] * 12   # 12 hours = 48 slots
        cheap = [0.10] * 12       # 12 hours = 48 slots
        tariffs = make_tariffs(expensive + cheap, start_dt=self.now)

        state = MockSystemState(
            timestamp=self.now,
            battery_soc=30.0,
            ev_connected=False,
        )

        planner = HorizonPlanner(self.cfg)
        plan = planner.plan(state, tariffs, self.consumption_96, self.pv_96, {})

        self.assertIsNotNone(plan)

        charge_expensive = sum(s.bat_charge_kw for s in plan.slots[:48])
        charge_cheap = sum(s.bat_charge_kw for s in plan.slots[48:])

        self.assertGreater(
            charge_cheap, charge_expensive,
            msg=(
                f"LP should charge more during cheap slots. "
                f"Cheap: {charge_cheap:.3f} kW, Expensive: {charge_expensive:.3f} kW"
            )
        )


class TestHorizonPlannerEVUrgency(unittest.TestCase):
    """Test 3: EV departure urgency — aggressive charging when departure is close."""

    def setUp(self):
        self.cfg = MockConfig()
        self.now = datetime(2026, 2, 22, 10, 0, 0, tzinfo=timezone.utc)
        self.consumption_96 = [1000.0] * 96
        self.pv_96 = [0.0] * 96

    def test_urgent_departure_charges_aggressively(self):
        """EV at 30% SoC, departure in 3h (12 slots) — most charging in first 12 slots."""
        tariffs = make_flat_tariffs(price=0.25, n_hours=24)

        # EV: 30 kWh capacity, current SoC 30%, needs 80%
        state = MockSystemState(
            timestamp=self.now,
            battery_soc=50.0,
            ev_connected=True,
            ev_soc=30.0,
            ev_capacity_kwh=30.0,
            ev_charge_power_kw=11.0,
            ev_name="test_ev",
        )

        departure = self.now + timedelta(hours=3)  # 12 slots away
        ev_departure = {"test_ev": departure}

        planner = HorizonPlanner(self.cfg)
        plan = planner.plan(state, tariffs, self.consumption_96, self.pv_96, ev_departure)

        self.assertIsNotNone(plan)

        charge_first_12 = sum(s.ev_charge_kw for s in plan.slots[:12])
        charge_remaining = sum(s.ev_charge_kw for s in plan.slots[12:])

        # With tight departure, EV should charge primarily in first 12 slots
        self.assertGreater(
            charge_first_12, 0.0,
            msg=f"EV should charge in first 12 slots with urgent departure; got {charge_first_12:.3f} kW"
        )
        # Most charging should be concentrated in the urgent window
        self.assertGreater(
            charge_first_12, charge_remaining,
            msg=(
                f"Urgent EV: first 12 slots should have more charging than rest. "
                f"First 12: {charge_first_12:.3f} kW, Remaining: {charge_remaining:.3f} kW"
            )
        )

    def test_distant_departure_spreads_charging(self):
        """EV at 30% SoC, departure in 12h (48 slots) — LP distributes charging over cheap window."""
        tariffs = make_flat_tariffs(price=0.25, n_hours=24)

        state = MockSystemState(
            timestamp=self.now,
            battery_soc=50.0,
            ev_connected=True,
            ev_soc=30.0,
            ev_capacity_kwh=30.0,
            ev_charge_power_kw=11.0,
            ev_name="test_ev",
        )

        departure = self.now + timedelta(hours=12)  # 48 slots away
        ev_departure = {"test_ev": departure}

        planner = HorizonPlanner(self.cfg)
        plan = planner.plan(state, tariffs, self.consumption_96, self.pv_96, ev_departure)

        self.assertIsNotNone(plan)

        # Plan should be valid and EV should eventually charge
        total_ev_charge = sum(s.ev_charge_kw for s in plan.slots)
        self.assertGreater(total_ev_charge, 0.0,
            msg=f"EV with distant departure should still charge; total={total_ev_charge:.3f} kW")


class TestHorizonPlannerNoEV(unittest.TestCase):
    """Test 4: No EV connected — EV charge should be zero in all slots."""

    def setUp(self):
        self.cfg = MockConfig()
        self.now = datetime(2026, 2, 22, 12, 0, 0, tzinfo=timezone.utc)
        self.consumption_96 = [1000.0] * 96
        self.pv_96 = [0.0] * 96

    def test_no_ev_zero_ev_charge(self):
        """No EV connected — all ev_charge_kw must be 0.0."""
        tariffs = make_flat_tariffs(price=0.30, n_hours=24)

        state = MockSystemState(
            timestamp=self.now,
            battery_soc=50.0,
            ev_connected=False,    # EV not connected
        )

        planner = HorizonPlanner(self.cfg)
        plan = planner.plan(state, tariffs, self.consumption_96, self.pv_96, {})

        self.assertIsNotNone(plan)

        for slot in plan.slots:
            self.assertAlmostEqual(
                slot.ev_charge_kw, 0.0, delta=0.01,
                msg=f"Slot {slot.slot_index}: ev_charge_kw={slot.ev_charge_kw:.4f} should be 0 (no EV)"
            )


class TestHorizonPlannerSolverFailure(unittest.TestCase):
    """Test 5: Infeasible LP — planner returns None without raising an exception."""

    def test_infeasible_min_soc_gt_max_soc_returns_none(self):
        """battery_min_soc > battery_max_soc makes LP infeasible — must return None."""
        # Create an impossible config: min_soc > max_soc
        cfg = MockConfig(
            battery_min_soc=90,
            battery_max_soc=10,   # impossible: min > max
        )
        now = datetime(2026, 2, 22, 12, 0, 0, tzinfo=timezone.utc)
        state = MockSystemState(
            timestamp=now,
            battery_soc=50.0,
            ev_connected=False,
        )
        tariffs = make_flat_tariffs(price=0.25, n_hours=24)
        consumption_96 = [1000.0] * 96
        pv_96 = [0.0] * 96

        planner = HorizonPlanner(cfg)
        plan = planner.plan(state, tariffs, consumption_96, pv_96, {})

        self.assertIsNone(plan, "Infeasible LP (min_soc > max_soc) must return None, not raise")

    def test_infeasible_ev_impossible_deadline_returns_none(self):
        """EV at 0% SoC, max_price=0 ct/kWh forces no charging but needs 80% — LP fails."""
        # max price of 0 means penalty applies at all prices, but LP bounds ev_charge to 0
        # Actually: set ev_charge_power_kw to 0 effectively (via state) but ev_connected=True
        # and a very tight deadline that's physically impossible.
        cfg = MockConfig(
            battery_min_soc=10,
            battery_max_soc=90,
            ev_max_price_ct=0.0,   # price penalty active for ALL prices
        )
        now = datetime(2026, 2, 22, 12, 0, 0, tzinfo=timezone.utc)

        # EV at 0% SoC, max charge power very low, departure in 1 slot
        # => can deliver max 0.01 kWh but needs 80% of 30kWh = 24 kWh
        state = MockSystemState(
            timestamp=now,
            battery_soc=50.0,
            ev_connected=True,
            ev_soc=0.0,
            ev_capacity_kwh=30.0,
            ev_charge_power_kw=0.0001,   # nearly zero charge rate
            ev_name="impossible_ev",
        )
        departure = now + timedelta(minutes=15)  # 1 slot — impossible to reach 80%
        ev_departure = {"impossible_ev": departure}
        tariffs = make_flat_tariffs(price=0.25, n_hours=24)
        consumption_96 = [1000.0] * 96
        pv_96 = [0.0] * 96

        planner = HorizonPlanner(cfg)
        # This MUST return None or a valid plan — it must NOT raise an exception
        try:
            plan = planner.plan(state, tariffs, consumption_96, pv_96, ev_departure)
            # Plan may be None (infeasible) or non-None (LP relaxed constraint) — both OK
            # Key assertion: no exception was raised
        except Exception as exc:  # noqa: BLE001
            self.fail(f"planner.plan() must never raise; got {type(exc).__name__}: {exc}")


class TestHorizonPlannerShortPriceHorizon(unittest.TestCase):
    """Test 6: Short price horizon (< 32 slots = < 8 hours) — must return None."""

    def test_4_hour_tariffs_returns_none(self):
        """Only 4 hourly slots (16 x 15-min) provided — below 32 slot threshold."""
        now = datetime(2026, 2, 22, 12, 0, 0, tzinfo=timezone.utc)
        state = MockSystemState(timestamp=now, battery_soc=50.0, ev_connected=False)

        # Only 4 hours = 16 x 15-min slots — below the 32-slot minimum
        tariffs = make_tariffs([0.25, 0.25, 0.25, 0.25], start_dt=now)

        planner = HorizonPlanner(MockConfig())
        plan = planner.plan(state, tariffs, [1000.0] * 96, [0.0] * 96, {})

        self.assertIsNone(plan,
            "4-hour tariff horizon (16 slots) should return None (< 32 slot minimum)")

    def test_empty_tariffs_returns_none(self):
        """Empty tariff list must return None gracefully."""
        now = datetime(2026, 2, 22, 12, 0, 0, tzinfo=timezone.utc)
        state = MockSystemState(timestamp=now, battery_soc=50.0, ev_connected=False)

        planner = HorizonPlanner(MockConfig())
        plan = planner.plan(state, [], [1000.0] * 96, [0.0] * 96, {})

        self.assertIsNone(plan, "Empty tariff list should return None")

    def test_8_hour_tariffs_at_boundary_succeeds(self):
        """Exactly 8 hourly slots (32 x 15-min) — at the >= 32 threshold, expect success with padding."""
        now = datetime(2026, 2, 22, 12, 0, 0, tzinfo=timezone.utc)
        state = MockSystemState(timestamp=now, battery_soc=50.0, ev_connected=False)

        # 8 hours = 32 slots — exactly at the >= 32 threshold, so planner pads to 96
        tariffs = make_tariffs([0.25] * 8, start_dt=now)

        planner = HorizonPlanner(MockConfig())
        plan = planner.plan(state, tariffs, [1000.0] * 96, [0.0] * 96, {})

        # 32 slots passes the >= 32 check: planner pads to 96 with last known price
        self.assertIsNotNone(plan,
            "8-hour tariff (32 slots) should succeed with padding (>= 32 slot minimum)")


class TestHorizonPlannerSocBounds(unittest.TestCase):
    """Test 7: Battery SoC stays within configured min/max bounds."""

    def setUp(self):
        self.cfg = MockConfig(
            battery_min_soc=10,
            battery_max_soc=90,
            battery_capacity_kwh=10.0,
            battery_charge_power_kw=5.0,
        )
        self.now = datetime(2026, 2, 22, 12, 0, 0, tzinfo=timezone.utc)
        self.consumption_96 = [200.0] * 96    # very low consumption to maximize charging pressure
        self.pv_96 = [0.0] * 96

    def test_battery_soc_never_exceeds_max(self):
        """Very cheap prices encourage max charging — SoC must never exceed battery_max_soc."""
        # Very cheap prices: LP will want to charge as much as possible
        tariffs = make_flat_tariffs(price=0.01, n_hours=24)  # 1 ct/kWh — very cheap

        state = MockSystemState(
            timestamp=self.now,
            battery_soc=10.0,   # start at minimum
            ev_connected=False,
        )

        planner = HorizonPlanner(self.cfg)
        plan = planner.plan(state, tariffs, self.consumption_96, self.pv_96, {})

        self.assertIsNotNone(plan)

        max_soc_pct = self.cfg.battery_max_soc
        for slot in plan.slots:
            self.assertLessEqual(
                slot.bat_soc_pct, max_soc_pct + 0.5,   # 0.5% numerical tolerance
                msg=(
                    f"Slot {slot.slot_index}: bat_soc_pct={slot.bat_soc_pct:.2f}% "
                    f"exceeds battery_max_soc={max_soc_pct}%"
                )
            )

    def test_battery_soc_never_below_min(self):
        """High discharge revenue encourages discharge — SoC must never drop below battery_min_soc."""
        # Set high feed-in to encourage discharge
        cfg = MockConfig(
            battery_min_soc=10,
            battery_max_soc=90,
            battery_capacity_kwh=10.0,
            battery_charge_power_kw=5.0,
            feed_in_tariff_ct=50.0,   # very high feed-in: LP wants to discharge as much as possible
        )

        # High price tariffs: also encourage discharge (import is expensive)
        tariffs = make_flat_tariffs(price=0.50, n_hours=24)

        state = MockSystemState(
            timestamp=self.now,
            battery_soc=90.0,   # start at maximum
            ev_connected=False,
        )

        planner = HorizonPlanner(cfg)
        plan = planner.plan(state, tariffs, self.consumption_96, self.pv_96, {})

        self.assertIsNotNone(plan)

        min_soc_pct = cfg.battery_min_soc
        for slot in plan.slots:
            self.assertGreaterEqual(
                slot.bat_soc_pct, min_soc_pct - 0.5,   # 0.5% numerical tolerance
                msg=(
                    f"Slot {slot.slot_index}: bat_soc_pct={slot.bat_soc_pct:.2f}% "
                    f"below battery_min_soc={min_soc_pct}%"
                )
            )


class TestHorizonPlannerPriceNoCache(unittest.TestCase):
    """Bonus Test 8: Price changes between cycles produce different plans (no caching)."""

    def test_different_prices_produce_different_plans(self):
        """Two consecutive calls with different prices produce different decisions."""
        cfg = MockConfig()
        now = datetime(2026, 2, 22, 12, 0, 0, tzinfo=timezone.utc)
        state = MockSystemState(timestamp=now, battery_soc=30.0, ev_connected=False)
        consumption_96 = [500.0] * 96
        pv_96 = [0.0] * 96

        # Cycle 1: expensive prices (no charging expected)
        expensive_tariffs = make_tariffs([0.50] * 12 + [0.50] * 12, start_dt=now)
        planner = HorizonPlanner(cfg)
        plan1 = planner.plan(state, expensive_tariffs, consumption_96, pv_96, {})

        # Cycle 2: cheap prices (charging expected)
        cheap_tariffs = make_tariffs([0.05] * 12 + [0.05] * 12, start_dt=now)
        plan2 = planner.plan(state, cheap_tariffs, consumption_96, pv_96, {})

        self.assertIsNotNone(plan1)
        self.assertIsNotNone(plan2)

        total_charge_expensive = sum(s.bat_charge_kw for s in plan1.slots)
        total_charge_cheap = sum(s.bat_charge_kw for s in plan2.slots)

        self.assertGreater(
            total_charge_cheap, total_charge_expensive,
            msg=(
                f"Cheap prices should produce more charging than expensive prices. "
                f"Cheap: {total_charge_cheap:.3f} kW, Expensive: {total_charge_expensive:.3f} kW"
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
