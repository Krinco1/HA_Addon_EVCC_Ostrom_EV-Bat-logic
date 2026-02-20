"""
Holistic LP Optimizer — v5.0

Percentile-based charge thresholds replace static price limits.
Same greedy scheduling logic, but now LP and RL speak the same language.

Battery actions (→ Action.battery_action):
    0 = hold
    1 = charge_p20  threshold = P20
    2 = charge_p40  threshold = P40
    3 = charge_p60  threshold = P60
    4 = charge_max  threshold = config battery_max_price_ct
    5 = charge_pv   threshold = 0 (solar only)
    6 = discharge

EV actions (→ Action.ev_action):
    0 = no_charge
    1 = charge_p30  threshold = P30
    2 = charge_p60  threshold = P60
    3 = charge_max  threshold = config ev_max_price_ct
    4 = charge_pv   threshold = 0
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
    battery_threshold_eur: Optional[float] = None
    ev_threshold_eur: Optional[float] = None
    battery_hours: List[datetime] = field(default_factory=list)
    ev_hours: List[datetime] = field(default_factory=list)
    reason_battery: str = ""
    reason_ev: str = ""
    battery_action: int = 0
    ev_action: int = 0


class HolisticOptimizer:
    """Greedy charge scheduler with percentile-based price thresholds."""

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

        # --- Demand analysis ---
        battery_soc = state.battery_soc
        battery_need_kwh = max(
            0, (self.cfg.battery_max_soc - battery_soc) / 100 * self.cfg.battery_capacity_kwh
        )
        battery_power = self.cfg.battery_charge_power_kw
        battery_hours_needed = (
            int(battery_need_kwh / battery_power) + 1 if battery_need_kwh > 0.5 else 0
        )

        ev_need_kwh = 0
        ev_hours_needed = 0
        ev_capacity = state.ev_capacity_kwh or self.cfg.ev_default_energy_kwh
        ev_charge_power = state.ev_charge_power_kw or 11

        if state.ev_connected:
            ev_need_kwh = max(
                0, (self.cfg.ev_target_soc - state.ev_soc) / 100 * ev_capacity
            )
            ev_hours_needed = (
                int(ev_need_kwh / ev_charge_power * 1.2) + 1 if ev_need_kwh > 1 else 0
            )

        # --- Time constraints ---
        deadline_hour = self.cfg.ev_charge_deadline_hour
        if now.hour < deadline_hour:
            ev_deadline = now.replace(
                hour=deadline_hour, minute=0, second=0, microsecond=0
            )
        else:
            ev_deadline = (now + timedelta(days=1)).replace(
                hour=deadline_hour, minute=0, second=0, microsecond=0
            )
        hours_until_ev_deadline = (ev_deadline - now).total_seconds() / 3600

        # --- Price context ---
        config_max_bat = self.cfg.battery_max_price_ct / 100
        config_max_ev = self.cfg.ev_max_price_ct / 100
        feed_in = self.cfg.feed_in_tariff_ct / 100
        prices_24h = [p for _, p in hourly[:24]] or [state.current_price]
        avg_price = sum(prices_24h) / len(prices_24h)

        # Get percentile thresholds from SystemState (computed in main loop)
        p20 = state.price_percentiles.get(20, state.current_price)
        p30 = state.price_percentiles.get(30, state.current_price)
        p40 = state.price_percentiles.get(40, state.current_price)
        p60 = state.price_percentiles.get(60, state.current_price)

        # --- PV surplus branch (case A: PV available right now) ---
        pv_surplus = max(0, state.pv_power - state.home_power)
        if pv_surplus > 500:
            if pv_surplus > 2000 and state.ev_connected and ev_need_kwh > 1:
                action.ev_action = 4
                action.ev_limit_eur = 0
                log("info", f"EV: Charging from PV surplus ({pv_surplus:.0f}W)")
            if pv_surplus > 500 and battery_need_kwh > 0.5:
                action.battery_action = 5
                action.battery_limit_eur = 0
                log("info", "Battery: Charging from PV surplus")
            if action.ev_action != 0 or action.battery_action != 0:
                return action

        # --- Grid charging: assess urgency and pick percentile tier ---
        bat_urgency = self._assess_battery_urgency(
            battery_soc, battery_need_kwh,
            state.solar_forecast_total_kwh,
            state.hours_cheap_remaining,
        )

        bat_tier_map = {
            "pv_only": (5, 0.0,         "PV only"),
            "low":     (1, min(p20, config_max_bat), f"P20={p20*100:.1f}ct"),
            "normal":  (2, min(p40, config_max_bat), f"P40={p40*100:.1f}ct"),
            "high":    (3, min(p60, config_max_bat), f"P60={p60*100:.1f}ct"),
            "urgent":  (4, config_max_bat,           f"Max={config_max_bat*100:.1f}ct"),
        }
        bat_action_idx, bat_threshold, bat_reason = bat_tier_map[bat_urgency]

        if battery_hours_needed > 0 and bat_action_idx > 0:
            # Validate: are there enough hours below threshold in 24h window?
            eligible_bat = [(h, p) for h, p in hourly[:24] if p <= bat_threshold]
            if len(eligible_bat) >= battery_hours_needed or bat_urgency == "urgent":
                action.battery_action = bat_action_idx
                action.battery_limit_eur = bat_threshold
                log("info", f"Battery: {bat_urgency} urgency → action {bat_action_idx} ({bat_reason})")
            else:
                # Not enough cheap hours at this tier — escalate one level
                action.battery_action = bat_action_idx + 1 if bat_action_idx < 4 else 4
                action.battery_limit_eur = min(p60, config_max_bat)
                log("info", f"Battery: escalated (only {len(eligible_bat)}h available)")

        # --- EV: percentile-based scheduling ---
        if ev_hours_needed > 0 and state.ev_connected:
            ev_eligible_p30 = [
                (h, p) for h, p in hourly
                if h.timestamp() < ev_deadline.timestamp() and p <= min(p30, config_max_ev)
            ]
            ev_eligible_p60 = [
                (h, p) for h, p in hourly
                if h.timestamp() < ev_deadline.timestamp() and p <= min(p60, config_max_ev)
            ]
            ev_eligible_max = [
                (h, p) for h, p in hourly
                if h.timestamp() < ev_deadline.timestamp() and p <= config_max_ev
            ]

            if len(ev_eligible_p30) >= ev_hours_needed:
                best = sorted(ev_eligible_p30, key=lambda x: x[1])[:ev_hours_needed]
                action.ev_action = 1
                action.ev_limit_eur = max(p for _, p in best) + 0.001
                log("info", f"EV: charge_p30 @ {action.ev_limit_eur*100:.1f}ct")
            elif len(ev_eligible_p60) >= ev_hours_needed:
                best = sorted(ev_eligible_p60, key=lambda x: x[1])[:ev_hours_needed]
                action.ev_action = 2
                action.ev_limit_eur = max(p for _, p in best) + 0.001
                log("info", f"EV: charge_p60 @ {action.ev_limit_eur*100:.1f}ct")
            elif ev_eligible_max:
                best = sorted(ev_eligible_max, key=lambda x: x[1])[:ev_hours_needed]
                action.ev_action = 3
                action.ev_limit_eur = config_max_ev
                log("info", f"EV: charge_max @ {config_max_ev*100:.1f}ct (limited slots)")

        # --- Emergency: EV deadline approaching ---
        if (
            state.ev_connected and ev_need_kwh > 1
            and hours_until_ev_deadline < ev_hours_needed * 1.2
        ):
            action.ev_action = 3
            action.ev_limit_eur = config_max_ev
            log("warning", f"EV URGENT: {hours_until_ev_deadline:.1f}h until deadline!")

        # --- Emergency: battery critically low ---
        if battery_soc < 15 and battery_need_kwh > 0 and action.battery_action == 0:
            action.battery_action = 4
            action.battery_limit_eur = config_max_bat
            log("warning", f"Battery LOW ({battery_soc}%)! Emergency charging")

        # --- Discharge logic ---
        if battery_soc > 50 and battery_need_kwh < 1:
            price_is_high = state.current_price > avg_price * 1.15
            price_above_feedin = state.current_price > feed_in * 1.3
            home_needs_power = state.home_power > state.pv_power
            if price_is_high and price_above_feedin and home_needs_power:
                action.battery_action = 6
                log("info", f"Battery: Discharging at {state.current_price * 100:.1f}ct")

        return action

    # ------------------------------------------------------------------
    # Battery urgency assessment
    # ------------------------------------------------------------------

    def _assess_battery_urgency(
        self,
        battery_soc: float,
        battery_need_kwh: float,
        solar_forecast_kwh: float,
        hours_cheap_remaining: int,
    ) -> str:
        """Determine how aggressively to charge the battery."""
        if battery_need_kwh < 0.5:
            return "pv_only"

        # Emergency
        if battery_soc < 15:
            return "urgent"

        # Lots of solar coming → wait for PV
        if solar_forecast_kwh > battery_need_kwh * 1.3 and battery_soc >= 40:
            return "pv_only"

        # Season-aware: low solar months → be more aggressive
        month = datetime.now().month
        winter = month in (11, 12, 1, 2, 3)

        if winter:
            if battery_soc < 30 or hours_cheap_remaining < 2:
                return "high"
            return "normal"
        else:
            # Summer: solar will likely refill → be conservative
            if battery_soc < 25:
                return "high"
            if hours_cheap_remaining >= 4:
                return "low"
            return "normal"

    # ------------------------------------------------------------------
    # Tariff parsing helpers (unchanged from v4)
    # ------------------------------------------------------------------

    def _tariffs_to_hourly(
        self, tariffs: List[Dict], now: datetime
    ) -> List[Tuple[datetime, float]]:
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
