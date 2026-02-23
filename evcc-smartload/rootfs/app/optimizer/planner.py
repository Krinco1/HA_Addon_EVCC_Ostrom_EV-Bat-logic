"""
HorizonPlanner — Rolling-Horizon LP-based energy dispatch optimizer.

Phase 4 of EVCC-Smartload. Uses scipy.optimize.linprog (HiGHS backend) to
produce a joint 24h battery + EV dispatch plan from price, consumption, and
PV forecast inputs.

Key design decisions:
- 96-slot (15-min) LP formulation: bat_charge, bat_discharge, ev_charge,
  bat_soc, ev_soc as continuous non-negative variables.
- SoC dynamics as equality constraints (banded structure).
- EV departure time as inequality constraint on ev_soc at departure slot.
- scipy is lazy-imported inside _solve_lp() to avoid ImportError if scipy
  is not yet installed at module load time.
- MPC receding horizon: only current-slot decision is applied; LP re-solved
  fresh every 15-min cycle from actual SoC (corrects model-plant mismatch).
- HolisticOptimizer remains the required fallback for LP failures.

Variable layout (T=96, N_vars = 5*T+2 = 482):
  bat_charge[t]    t=0..T-1   kW battery charge power
  bat_discharge[t] t=0..T-1   kW battery discharge power
  ev_charge[t]     t=0..T-1   kW EV charge power (0 when not connected)
  bat_soc[t]       t=0..T     fraction battery SoC (auxiliary, T+1 values)
  ev_soc[t]        t=0..T     fraction EV SoC (auxiliary, T+1 values)
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import Config
from logging_util import log
from state import DispatchSlot, PlanHorizon, SystemState


# Threshold in kW below which a continuous LP decision is treated as "off"
_CHARGE_THRESHOLD_KW = 0.1

# 15-minute slot duration in hours
_DT_H = 0.25

# Number of 15-min slots in 24h
_T = 96


class HorizonPlanner:
    """Rolling-horizon LP planner for joint battery + EV dispatch optimization.

    Replaces static price-gate logic in HolisticOptimizer when LP succeeds.
    Falls back to HolisticOptimizer on any solver failure, exception, or
    insufficient price data (< 32 slots = < 8 hours of price data).

    Usage:
        planner = HorizonPlanner(cfg)
        plan = planner.plan(state, tariffs, consumption_96, pv_96, ev_departure_times)
        if plan is not None:
            # LP succeeded: use plan.slots[0] for immediate decision
        else:
            # Fall back to HolisticOptimizer
    """

    def __init__(self, cfg: Config):
        """Initialize planner with config values needed for LP formulation."""
        self.cfg = cfg

        # Battery parameters
        self._bat_cap = cfg.battery_capacity_kwh
        self._bat_p_max = cfg.battery_charge_power_kw
        self._eta_c = cfg.battery_charge_efficiency
        self._eta_d = cfg.battery_discharge_efficiency
        self._bat_min_soc = cfg.battery_min_soc / 100.0
        self._bat_max_soc = cfg.battery_max_soc / 100.0

        # Price limits (used as LP upper-bound inputs, not gate thresholds)
        self._bat_max_price = cfg.battery_max_price_ct / 100.0
        self._ev_max_price = cfg.ev_max_price_ct / 100.0

        # Feed-in revenue (default 0.08 EUR/kWh if not in config)
        self._feed_in = getattr(cfg, "feed_in_tariff_ct", 7.0) / 100.0

        # EV defaults when state reports 0
        self._ev_default_cap = cfg.ev_default_energy_kwh
        self._ev_default_power = cfg.sequencer_default_charge_power_kw

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def plan(
        self,
        state: SystemState,
        tariffs: List[Dict],
        consumption_96: List[float],
        pv_96: List[float],
        ev_departure_times: Dict[str, datetime],
        confidence_factors: Optional[Dict] = None,
    ) -> Optional[PlanHorizon]:
        """Solve LP for the next 24h horizon.

        Args:
            state: Current system state snapshot
            tariffs: Raw evcc tariff dicts with 'start' and 'value' fields
            consumption_96: 96-element list of Watt values (house consumption forecast)
            pv_96: 96-element list of kW values (PV generation forecast)
            ev_departure_times: Dict mapping EV name (or '_default') to departure UTC datetime
            confidence_factors: Optional dict with per-source confidence values (0.0–1.0).
                Keys: "pv", "consumption", "price". Missing keys default to 1.0.
                Applied as a multiplier on the PV surplus reduction in the LP objective.
                Lower PV confidence means the planner trusts PV forecasts less and acts
                more conservatively with battery discharge timing.
                NOTE (Phase 8 research): Price confidence affects planning conservatism
                via DynamicBufferCalc (not LP coefficients directly). Only "pv" is applied
                to the LP objective. See Phase 8 RESEARCH.md Open Question 1.

        Returns:
            PlanHorizon with 96 DispatchSlots on success, None on any failure.
        """
        try:
            now = state.timestamp or datetime.now(timezone.utc)

            # Resolve confidence factors (default to 1.0 for backward compatibility)
            if confidence_factors is None:
                confidence_factors = {}
            pv_confidence_factor = float(confidence_factors.get("pv", 1.0))
            # Clamp to [0, 1] for safety
            pv_confidence_factor = max(0.0, min(1.0, pv_confidence_factor))

            # Step 1: Convert tariffs to 96-slot price array
            price_96 = self._tariffs_to_96slots(tariffs, now)
            if price_96 is None:
                log("info", "HorizonPlanner: insufficient price data (< 32 slots), falling back")
                return None

            # Step 2: Pre-check EV infeasibility before calling LP
            if state.ev_connected:
                self._check_ev_feasibility(state, price_96, ev_departure_times, now)

            # Step 3: Solve LP (pass pv_confidence_factor for objective scaling)
            result = self._solve_lp(
                state, price_96, consumption_96, pv_96, ev_departure_times, now,
                pv_confidence_factor=pv_confidence_factor,
            )
            if result is None:
                return None

            # Step 4: Extract PlanHorizon from LP result
            return self._extract_plan(result, price_96, state, consumption_96, pv_96,
                                      ev_departure_times, now)

        except Exception as exc:
            log("warning", f"HorizonPlanner: exception in LP solve: {exc}, falling back to HolisticOptimizer")
            return None

    # ------------------------------------------------------------------
    # Price array construction
    # ------------------------------------------------------------------

    def _tariffs_to_96slots(self, tariffs: List[Dict], now: datetime) -> Optional[np.ndarray]:
        """Convert evcc tariff list to 96-element price array (EUR/kWh, 15-min slots).

        Reuses the same parsing logic as HolisticOptimizer._tariffs_to_hourly().
        Each hourly price expands to 4 x 15-min slots.
        Pads to 96 slots with last known price if between 32 and 96 slots available.
        Returns None if fewer than 32 slots available (insufficient horizon for LP).
        """
        if not tariffs:
            return None

        # Parse tariffs into (hour_datetime, price_eur_kwh) tuples
        buckets: Dict[datetime, List[float]] = defaultdict(list)
        now_hour = now.replace(minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

        for t in tariffs:
            try:
                start_str = t.get("start", "")
                val = float(t.get("value", 0))

                if start_str.endswith("Z"):
                    start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                elif "+" in start_str or start_str.count("-") > 2:
                    start = datetime.fromisoformat(start_str)
                else:
                    start = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)

                hour = start.replace(minute=0, second=0, microsecond=0)
                if hour.timestamp() >= now_hour.timestamp() - 3600:
                    buckets[hour].append(val)
            except Exception:
                continue

        hourly = sorted([(h, sum(v) / len(v)) for h, v in buckets.items()])

        if not hourly:
            return None

        # Expand hourly → 15-min slots (4 slots per hour)
        prices: List[float] = []
        for _hour_dt, price_eur in hourly:
            prices.extend([price_eur] * 4)

        if len(prices) < 32:
            log("info", f"HorizonPlanner: only {len(prices)} price slots available (need >= 32)")
            return None

        T = _T
        if len(prices) >= T:
            return np.array(prices[:T], dtype=np.float64)
        else:
            # Pad with last known price (conservative: don't assume cheap prices)
            pad_count = T - len(prices)
            pad = [prices[-1]] * pad_count
            log("info", f"HorizonPlanner: padding {pad_count} price slots with last known price {prices[-1]:.4f} EUR/kWh")
            return np.array(prices + pad, dtype=np.float64)

    # ------------------------------------------------------------------
    # LP formulation and solver
    # ------------------------------------------------------------------

    def _solve_lp(
        self,
        state: SystemState,
        price_96: np.ndarray,
        consumption_96: List[float],
        pv_96: List[float],
        ev_departure_times: Dict[str, datetime],
        now: datetime,
        pv_confidence_factor: float = 1.0,
    ):
        """Build and solve the LP for joint battery + EV dispatch.

        Args:
            pv_confidence_factor: Confidence multiplier (0.0–1.0) from ForecastReliabilityTracker.
                Applied to the PV surplus reduction in the objective: a lower factor means
                the planner trusts PV forecasts less, reducing PV coverage benefit and
                acting more conservatively with PV-driven free charging.

        Variable layout (T=96, N_vars = 5*T+2 = 482):
            bat_charge[t]    [i_bat_chg, i_bat_chg+T)   kW battery charge
            bat_discharge[t] [i_bat_dis, i_bat_dis+T)   kW battery discharge
            ev_charge[t]     [i_ev_chg,  i_ev_chg+T)    kW EV charge
            bat_soc[t]       [i_bat_soc, i_bat_soc+T+1) fraction 0..1
            ev_soc[t]        [i_ev_soc,  i_ev_soc+T+1)  fraction 0..1

        Returns scipy OptimizeResult on success (status==0), None on failure.
        """
        # Lazy import: avoids ImportError if scipy not installed until planner is called
        from scipy.optimize import linprog

        T = len(price_96)  # may be less than 96 if padded
        dt_h = _DT_H

        # --- Variable index offsets ---
        i_bat_chg = 0
        i_bat_dis = T
        i_ev_chg = 2 * T
        i_bat_soc = 3 * T
        i_ev_soc = 3 * T + (T + 1)
        N_vars = 3 * T + 2 * (T + 1)  # = 5*T + 2

        # --- EV parameters (with fallbacks for unknown vehicle) ---
        ev_connected = state.ev_connected
        ev_capacity = (state.ev_capacity_kwh or self._ev_default_cap) if ev_connected else self._ev_default_cap
        ev_charge_power = (state.ev_charge_power_kw or self._ev_default_power) if ev_connected else 0.0
        ev_current_soc = (state.ev_soc / 100.0) if ev_connected else 0.0
        ev_name = state.ev_name if ev_connected else ""

        # --- Objective: minimize grid cost ---
        # c[t] for bat_charge and ev_charge = effective grid price net of PV surplus
        # c[t] for bat_discharge = -feed_in_rate (revenue from grid export)
        # SoC auxiliary variables have zero cost coefficient
        c = np.zeros(N_vars)

        # Pad consumption_96 and pv_96 to T slots if needed
        cons_96 = list(consumption_96) + [consumption_96[-1] if consumption_96 else 1200.0] * max(0, T - len(consumption_96))
        pv_kw_96 = list(pv_96) + [0.0] * max(0, T - len(pv_96))
        cons_96 = cons_96[:T]
        pv_kw_96 = pv_kw_96[:T]

        for t in range(T):
            # PV surplus available this slot (kW) — reduces effective grid import cost
            pv_surplus_kw = max(0.0, pv_kw_96[t] - cons_96[t] / 1000.0)

            # Effective grid price for charging: reduce when PV can cover it
            # We model this by reducing cost proportionally to PV surplus coverage
            # (Pitfall 3 mitigation: don't over-count PV as grid-priced)
            # Phase 8: pv_confidence_factor scales PV surplus — lower confidence means
            # less PV benefit in the objective (more conservative PV-driven decisions).
            effective_price = price_96[t]
            if pv_surplus_kw > 0.05:
                # PV surplus: reduce charge cost proportionally
                # When PV fully covers bat_p_max, charge is effectively free
                # Apply confidence factor: reduces PV coverage benefit when forecast is unreliable
                pv_coverage = min(1.0, pv_surplus_kw / max(self._bat_p_max, 0.1))
                effective_price = price_96[t] * (1.0 - pv_coverage * pv_confidence_factor)

            # Apply config max-price bounds: charging above threshold is penalized
            # (LP upper-bound enforcement via objective — acts as soft price gate)
            if price_96[t] > self._bat_max_price:
                # Heavy penalty to prevent battery charging above user's max price
                c[i_bat_chg + t] = price_96[t] * 10.0
            else:
                c[i_bat_chg + t] = effective_price

            if price_96[t] > self._ev_max_price and ev_connected:
                # Heavy penalty to prevent EV charging above user's max price
                c[i_ev_chg + t] = price_96[t] * 10.0
            else:
                c[i_ev_chg + t] = effective_price

            # Discharge revenue: negative cost (HiGHS minimizes, so negative = good)
            c[i_bat_dis + t] = -self._feed_in

        # --- Equality constraints: SoC dynamics ---
        # Battery: soc[t+1] = soc[t] + charge[t]*eta_c*dt/cap - discharge[t]*dt/(eta_d*cap)
        # Written as: soc[t+1] - soc[t] - charge[t]*eta_c*dt/cap + discharge[t]*dt/(eta_d*cap) = 0
        # EV: soc[t+1] = soc[t] + charge[t]*dt/ev_cap (only when connected)
        # Initial SoC: soc[0] = current_soc (separate row per asset)

        eta_c = self._eta_c
        eta_d = self._eta_d
        cap = self._bat_cap

        # Pre-allocate: T bat_dynamics + 1 bat_initial + T ev_dynamics + 1 ev_initial = 2*T + 2 rows
        n_eq = 2 * T + 2
        A_eq = np.zeros((n_eq, N_vars))
        b_eq = np.zeros(n_eq)

        row = 0

        # Battery SoC dynamics: t = 0..T-1
        for t in range(T):
            A_eq[row, i_bat_soc + t + 1] = 1.0      # soc[t+1]
            A_eq[row, i_bat_soc + t] = -1.0          # -soc[t]
            A_eq[row, i_bat_chg + t] = -eta_c * dt_h / cap    # charge contribution
            A_eq[row, i_bat_dis + t] = dt_h / (eta_d * cap)   # discharge cost
            b_eq[row] = 0.0
            row += 1

        # Battery initial SoC: soc[0] = current_bat_soc / 100
        A_eq[row, i_bat_soc] = 1.0
        b_eq[row] = state.battery_soc / 100.0
        row += 1

        # EV SoC dynamics: t = 0..T-1
        for t in range(T):
            if ev_connected and ev_capacity > 0:
                A_eq[row, i_ev_soc + t + 1] = 1.0         # soc[t+1]
                A_eq[row, i_ev_soc + t] = -1.0             # -soc[t]
                A_eq[row, i_ev_chg + t] = -dt_h / ev_capacity  # charge contribution
                b_eq[row] = 0.0
            else:
                # No EV: ev_soc stays at 0 (identity constraint soc[t+1] - soc[t] = 0)
                A_eq[row, i_ev_soc + t + 1] = 1.0
                A_eq[row, i_ev_soc + t] = -1.0
                b_eq[row] = 0.0
            row += 1

        # EV initial SoC: soc[0] = current_ev_soc (or 0 if not connected)
        A_eq[row, i_ev_soc] = 1.0
        b_eq[row] = ev_current_soc
        row += 1

        # --- Inequality constraints: departure + mutual exclusion ---
        # We may have 0 or more departure constraints + T mutual exclusion constraints
        A_ub_rows = []
        b_ub_rows = []

        # Departure constraint for connected EV
        if ev_connected:
            # Use '_default' key (Phase 4) or EV name if available
            departure_dt = ev_departure_times.get(ev_name) or ev_departure_times.get("_default")
            if departure_dt is not None:
                dep_slot = self._departure_slot(departure_dt, now)
                target_soc = getattr(self.cfg, "ev_target_soc", 80) / 100.0

                # Inequality: ev_soc[dep_slot] >= target_soc
                # Written as: -ev_soc[dep_slot] <= -target_soc
                row_dep = np.zeros(N_vars)
                row_dep[i_ev_soc + dep_slot] = -1.0
                A_ub_rows.append(row_dep)
                b_ub_rows.append(-target_soc)

        # Mutual exclusion guard: bat_charge[t] + bat_discharge[t] <= P_max
        # (Prevents degeneracy at unit efficiency — Research Open Question 1)
        p_max_sum = max(self._bat_p_max, 0.1)
        for t in range(T):
            row_mx = np.zeros(N_vars)
            row_mx[i_bat_chg + t] = 1.0
            row_mx[i_bat_dis + t] = 1.0
            A_ub_rows.append(row_mx)
            b_ub_rows.append(p_max_sum)

        if A_ub_rows:
            A_ub = np.array(A_ub_rows)
            b_ub = np.array(b_ub_rows)
        else:
            A_ub = None
            b_ub = None

        # --- Variable bounds ---
        # bat_charge: [0, P_bat_max]
        # bat_discharge: [0, P_bat_max]
        # ev_charge: [0, P_ev] if connected, else [0, 0]
        # bat_soc: [min_soc, max_soc] (fraction)
        # ev_soc: [0, 1.0] if connected, else [0, 0]

        bounds = (
            [(0.0, self._bat_p_max)] * T           # bat_charge
            + [(0.0, self._bat_p_max)] * T          # bat_discharge
            + [(0.0, ev_charge_power if ev_connected else 0.0)] * T  # ev_charge
            + [(self._bat_min_soc, self._bat_max_soc)] * (T + 1)    # bat_soc
            + [(0.0, 1.0 if ev_connected else 0.0)] * (T + 1)       # ev_soc
        )

        # --- Solve ---
        t_start = time.time()
        result = linprog(
            c,
            A_ub=A_ub,
            b_ub=b_ub,
            A_eq=A_eq,
            b_eq=b_eq,
            bounds=bounds,
            method="highs",
            options={"time_limit": 10.0, "disp": False, "presolve": True},
        )
        elapsed = time.time() - t_start

        if result.status == 0:
            log("info", f"HorizonPlanner: LP solved in {elapsed:.1f}s, status={result.status}, cost={result.fun:.4f} EUR")
        else:
            log("info", f"HorizonPlanner: LP solved in {elapsed:.1f}s, status={result.status} ({result.message})")

        if result.status == 0 and result.success:
            return result

        log("warning", f"HorizonPlanner: LP failed (status={result.status}: {result.message}), falling back")
        return None

    # ------------------------------------------------------------------
    # Plan extraction
    # ------------------------------------------------------------------

    def _extract_plan(
        self,
        result,
        price_96: np.ndarray,
        state: SystemState,
        consumption_96: List[float],
        pv_96: List[float],
        ev_departure_times: Dict[str, datetime],
        now: datetime,
    ) -> PlanHorizon:
        """Build a PlanHorizon from the LP optimal result vector.

        Applies np.clip to all power values to eliminate numerical precision
        artifacts (Pitfall 5: HiGHS may return tiny negatives near bounds).
        """
        T = len(price_96)

        i_bat_chg = 0
        i_bat_dis = T
        i_ev_chg = 2 * T
        i_bat_soc = 3 * T
        i_ev_soc = 3 * T + (T + 1)

        x = result.x

        # Clip all power variables to eliminate numerical precision artifacts
        bat_charge = np.clip(x[i_bat_chg:i_bat_chg + T], 0.0, self._bat_p_max)
        bat_discharge = np.clip(x[i_bat_dis:i_bat_dis + T], 0.0, self._bat_p_max)

        ev_connected = state.ev_connected
        ev_charge_power = (state.ev_charge_power_kw or self._ev_default_power) if ev_connected else 0.0
        ev_charge = np.clip(x[i_ev_chg:i_ev_chg + T], 0.0, ev_charge_power)

        bat_soc = np.clip(x[i_bat_soc:i_bat_soc + T + 1], self._bat_min_soc, self._bat_max_soc)
        ev_soc = np.clip(x[i_ev_soc:i_ev_soc + T + 1], 0.0, 1.0)

        # Pad consumption and PV to T slots
        cons_96 = (list(consumption_96) + [consumption_96[-1] if consumption_96 else 1200.0] * max(0, T - len(consumption_96)))[:T]
        pv_kw_96 = (list(pv_96) + [0.0] * max(0, T - len(pv_96)))[:T]

        # EV name for slots
        ev_name = state.ev_name if ev_connected else ""

        # Build DispatchSlot objects
        slots = []
        for t in range(T):
            slot_start = now + timedelta(minutes=t * 15)
            slots.append(
                DispatchSlot(
                    slot_index=t,
                    slot_start=slot_start,
                    bat_charge_kw=float(bat_charge[t]),
                    bat_discharge_kw=float(bat_discharge[t]),
                    ev_charge_kw=float(ev_charge[t]),
                    ev_name=ev_name,
                    price_eur_kwh=float(price_96[t]),
                    pv_kw=float(pv_kw_96[t]),
                    consumption_kw=float(cons_96[t] / 1000.0),
                    bat_soc_pct=float(bat_soc[t] * 100.0),
                    ev_soc_pct=float(ev_soc[t] * 100.0),
                )
            )

        # Current-slot (slot 0) action booleans
        slot0 = slots[0]
        current_bat_charge = slot0.bat_charge_kw > _CHARGE_THRESHOLD_KW
        current_bat_discharge = slot0.bat_discharge_kw > _CHARGE_THRESHOLD_KW
        current_ev_charge = slot0.ev_charge_kw > _CHARGE_THRESHOLD_KW and ev_connected

        # Effective price limit for slot 0
        current_price_limit = slot0.price_eur_kwh

        return PlanHorizon(
            computed_at=now,
            slots=slots,
            solver_status=result.status,
            solver_fun=float(result.fun),
            current_bat_charge=current_bat_charge,
            current_bat_discharge=current_bat_discharge,
            current_ev_charge=current_ev_charge,
            current_price_limit=current_price_limit,
        )

    # ------------------------------------------------------------------
    # EV feasibility pre-check
    # ------------------------------------------------------------------

    def _check_ev_feasibility(
        self,
        state: SystemState,
        price_96: np.ndarray,
        ev_departure_times: Dict[str, datetime],
        now: datetime,
    ) -> None:
        """Log a warning if EV departure constraint is physically infeasible.

        Does not prevent LP call — LP will return status=2 (infeasible) if
        the constraint cannot be satisfied. This pre-check enables a more
        informative log message before the LP failure.
        """
        ev_capacity = state.ev_capacity_kwh or self._ev_default_cap
        ev_charge_power = state.ev_charge_power_kw or self._ev_default_power
        ev_name = state.ev_name

        departure_dt = ev_departure_times.get(ev_name) or ev_departure_times.get("_default")
        if departure_dt is None or ev_capacity <= 0:
            return

        dep_slot = self._departure_slot(departure_dt, now)
        target_soc = getattr(self.cfg, "ev_target_soc", 80) / 100.0
        current_soc = state.ev_soc / 100.0

        max_deliverable_fraction = (dep_slot * ev_charge_power * _DT_H) / ev_capacity
        soc_needed = target_soc - current_soc

        if soc_needed > 0 and max_deliverable_fraction < soc_needed:
            log(
                "warning",
                f"HorizonPlanner: EV departure constraint may be infeasible — "
                f"need {soc_needed * 100:.0f}% SoC in {dep_slot} slots but can deliver "
                f"max {max_deliverable_fraction * 100:.0f}% (capacity={ev_capacity:.0f} kWh, "
                f"power={ev_charge_power:.1f} kW). LP will attempt to relax target.",
            )

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _departure_slot(departure_dt: datetime, now: datetime) -> int:
        """Return the 15-min slot index (0..95) for a departure datetime.

        Slot 0 = current slot. Clamps to [1, 95].
        """
        delta_minutes = (departure_dt - now).total_seconds() / 60
        slot_offset = int(delta_minutes / 15)
        return max(1, min(95, slot_offset))
