"""
Holistic LP Optimizer.

Considers battery, EV, PV and household load together to find cost-optimal
charge/discharge schedules using a priority-based greedy approach.

Principles:
  1. Compute total demand (battery + EV + house)
  2. Compute available sources (PV + grid)
  3. Prioritise: use PV > cheap grid hours > avoid expensive hours
  4. EV has a hard deadline; battery is more flexible
  5. Avoid grid overload (~20 kW parallel)
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from config import Config
from logging_util import log
from state import Action, SystemState


@dataclass
class ChargePlan:
    """Planned charge schedule for the next hours."""
    battery_threshold_eur: Optional[float] = None
    ev_threshold_eur: Optional[float] = None
    battery_hours: List[datetime] = field(default_factory=list)
    ev_hours: List[datetime] = field(default_factory=list)
    reason_battery: str = ""
    reason_ev: str = ""
    total_cost_estimate: float = 0.0


class HolisticOptimizer:
    """Greedy charge scheduler that optimises across all devices."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def optimize(self, state: SystemState, tariffs: List[Dict]) -> Action:
        action = Action(battery_action=0, ev_action=0)
        now = state.timestamp

        hourly = self._tariffs_to_hourly(tariffs, now)
        if not hourly:
            log("warning", "No hourly prices available – cannot optimise!")
            return action

        # --- 1. Demand analysis ---
        battery_soc = state.battery_soc
        battery_need_kwh = max(0, (self.cfg.battery_max_soc - battery_soc) / 100 * self.cfg.battery_capacity_kwh)
        battery_power = self.cfg.battery_charge_power_kw
        battery_hours_needed = int(battery_need_kwh / battery_power) + 1 if battery_need_kwh > 0.5 else 0

        ev_need_kwh = 0
        ev_hours_needed = 0
        ev_capacity = state.ev_capacity_kwh or self.cfg.ev_default_energy_kwh
        ev_charge_power = state.ev_charge_power_kw or 11

        if state.ev_connected:
            ev_need_kwh = max(0, (self.cfg.ev_target_soc - state.ev_soc) / 100 * ev_capacity)
            ev_hours_needed = int(ev_need_kwh / ev_charge_power * 1.2) + 1 if ev_need_kwh > 1 else 0

        # --- 2. Time windows & constraints ---
        deadline_hour = self.cfg.ev_charge_deadline_hour
        if now.hour < deadline_hour:
            ev_deadline = now.replace(hour=deadline_hour, minute=0, second=0, microsecond=0)
        else:
            ev_deadline = (now + timedelta(days=1)).replace(hour=deadline_hour, minute=0, second=0, microsecond=0)

        hours_until_ev_deadline = (ev_deadline - now).total_seconds() / 3600
        max_battery_price = self.cfg.battery_max_price_ct / 100
        max_ev_price = self.cfg.ev_max_price_ct / 100
        feed_in_price = self.cfg.feed_in_tariff_ct / 100

        prices_24h = [p for _, p in hourly[:24]] or [state.current_price]
        min_price = min(prices_24h)
        avg_price = sum(prices_24h) / len(prices_24h)

        # --- 3. PV analysis ---
        pv_surplus = max(0, state.pv_power - state.home_power)

        if pv_surplus > 500:
            # Case A: PV surplus available – use PV first
            if pv_surplus > 2000 and state.ev_connected and ev_need_kwh > 1:
                action.ev_action = 3
                action.ev_limit_eur = 0
                log("info", f"EV: Charging from PV surplus ({pv_surplus:.0f}W)")
            if pv_surplus > 500 and battery_need_kwh > 0.5:
                action.battery_action = 2
                action.battery_limit_eur = 0
                log("info", "Battery: Charging from PV surplus")
            if action.ev_action != 0 or action.battery_action != 0:
                return action

        # Case B: Grid charging – compute holistic plan
        plan = self._create_holistic_plan(
            hourly=hourly,
            now=now,
            battery_need_kwh=battery_need_kwh,
            battery_hours_needed=battery_hours_needed,
            battery_power_kw=battery_power,
            max_battery_price=max_battery_price,
            ev_need_kwh=ev_need_kwh,
            ev_hours_needed=ev_hours_needed,
            ev_power_kw=ev_charge_power,
            max_ev_price=max_ev_price,
            ev_deadline=ev_deadline,
            hours_until_ev_deadline=hours_until_ev_deadline,
            current_price=state.current_price,
            min_price=min_price,
        )

        if plan.battery_threshold_eur is not None and battery_need_kwh > 0.5:
            action.battery_action = 1
            action.battery_limit_eur = plan.battery_threshold_eur
            log("info", f"Battery: {plan.reason_battery}")

        if plan.ev_threshold_eur is not None and ev_need_kwh > 1 and state.ev_connected:
            action.ev_action = 1
            action.ev_limit_eur = plan.ev_threshold_eur
            log("info", f"EV: {plan.reason_ev}")

        # --- 5. Emergency checks ---
        if state.ev_connected and ev_need_kwh > 1 and hours_until_ev_deadline < ev_hours_needed * 1.2:
            action.ev_action = 2
            action.ev_limit_eur = max_ev_price
            log("warning", f"EV URGENT: {hours_until_ev_deadline:.1f}h until deadline, need {ev_hours_needed}h!")

        if battery_soc < 15 and battery_need_kwh > 0 and action.battery_action == 0:
            action.battery_action = 1
            action.battery_limit_eur = min(state.current_price + 0.02, max_battery_price)
            log("warning", f"Battery LOW ({battery_soc}%)! Emergency charging")

        # --- 6. Discharge logic ---
        if battery_soc > 50 and battery_need_kwh < 1:
            price_is_high = state.current_price > avg_price * 1.15
            price_above_feedin = state.current_price > feed_in_price * 1.3
            home_needs_power = state.home_power > state.pv_power
            if price_is_high and price_above_feedin and home_needs_power:
                action.battery_action = 3
                log("info", f"Battery: Discharging at {state.current_price * 100:.1f}ct")

        return action

    # ------------------------------------------------------------------
    # Holistic plan builder
    # ------------------------------------------------------------------

    def _create_holistic_plan(
        self, *, hourly, now, battery_need_kwh, battery_hours_needed,
        battery_power_kw, max_battery_price, ev_need_kwh, ev_hours_needed,
        ev_power_kw, max_ev_price, ev_deadline, hours_until_ev_deadline,
        current_price, min_price,
    ) -> ChargePlan:
        plan = ChargePlan()
        sorted_hourly = sorted(hourly, key=lambda x: x[0])

        # EV planning (priority – has deadline)
        if ev_hours_needed > 0:
            ev_eligible = [(h, p) for h, p in sorted_hourly
                           if h.timestamp() < ev_deadline.timestamp() and p <= max_ev_price]
            if ev_eligible:
                ev_by_price = sorted(ev_eligible, key=lambda x: x[1])
                ev_chosen = ev_by_price[:ev_hours_needed]
                if len(ev_chosen) >= ev_hours_needed:
                    ev_max_price = max(p for _, p in ev_chosen)
                    plan.ev_threshold_eur = ev_max_price + 0.001
                    plan.ev_hours = [h for h, _ in ev_chosen]
                    avg = sum(p for _, p in ev_chosen) / len(ev_chosen)
                    plan.reason_ev = (
                        f"Lade {ev_need_kwh:.1f}kWh in {len(ev_chosen)} günstigsten Stunden "
                        f"@ max {plan.ev_threshold_eur * 100:.1f}ct (avg {avg * 100:.1f}ct)"
                    )
                else:
                    plan.ev_threshold_eur = max(p for _, p in ev_chosen) + 0.001
                    plan.ev_hours = [h for h, _ in ev_chosen]
                    plan.reason_ev = f"Nur {len(ev_chosen)}/{ev_hours_needed} Stunden verfügbar"

        # Battery planning (flexible – no hard deadline)
        if battery_hours_needed > 0:
            battery_eligible = [(h, p) for h, p in sorted_hourly[:24] if p <= max_battery_price]
            if battery_eligible:
                battery_by_price = sorted(battery_eligible, key=lambda x: x[1])
                ev_hour_set = {h.hour for h in plan.ev_hours} if plan.ev_hours else set()
                preferred = [x for x in battery_by_price if x[0].hour not in ev_hour_set]
                overlap = [x for x in battery_by_price if x[0].hour in ev_hour_set]
                battery_sorted = preferred + overlap
                battery_chosen = battery_sorted[:battery_hours_needed]

                if battery_chosen:
                    plan.battery_threshold_eur = max(p for _, p in battery_chosen) + 0.001
                    plan.battery_hours = [h for h, _ in battery_chosen]
                    avg = sum(p for _, p in battery_chosen) / len(battery_chosen)
                    overlap_count = len([h for h in plan.battery_hours if h.hour in ev_hour_set])
                    plan.reason_battery = (
                        f"Lade {battery_need_kwh:.1f}kWh in {len(battery_chosen)} günstigsten Stunden "
                        f"@ max {plan.battery_threshold_eur * 100:.1f}ct "
                        f"(avg {avg * 100:.1f}ct, {overlap_count}h parallel mit EV)"
                    )

        return plan

    # ------------------------------------------------------------------
    # Tariff parsing helpers
    # ------------------------------------------------------------------

    def _tariffs_to_hourly(self, tariffs: List[Dict], now: datetime) -> List[Tuple[datetime, float]]:
        if not tariffs:
            return []

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

        return sorted([(h, sum(v) / len(v)) for h, v in buckets.items()])
