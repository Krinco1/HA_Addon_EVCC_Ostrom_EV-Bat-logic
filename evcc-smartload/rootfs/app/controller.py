"""
Controller – applies optimiser/RL actions to evcc.
"""

from typing import Optional

from config import Config
from evcc_client import EvccClient
from logging_util import log
from state import Action


class Controller:
    """Translates Action objects into evcc API calls."""

    def __init__(self, evcc: EvccClient, cfg: Config):
        self.evcc = evcc
        self.cfg = cfg
        self.last_action: Optional[Action] = None
        self._bat_to_ev_active = False
        self._last_buffer_soc: Optional[int] = None
        self._last_priority_soc: Optional[int] = None

    def apply(self, action: Action) -> float:
        """Apply action and return estimated cost (placeholder, refined later)."""

        # Battery
        if action.battery_limit_eur is not None and action.battery_limit_eur > 0:
            self.evcc.set_battery_grid_charge_limit(action.battery_limit_eur)
        else:
            self.evcc.clear_battery_grid_charge_limit()

        # EV
        if action.ev_limit_eur is not None:
            self.evcc.set_smart_cost_limit(max(0, action.ev_limit_eur))

        self.last_action = action
        return 0.0

    def calculate_dynamic_discharge_limit(self, bat_to_ev: dict) -> dict:
        """Calculate dynamic bufferSoc and prioritySoc based on forecasts.
        
        Logic:
          1. Estimate how much solar + cheap grid will refill the battery
          2. Allow discharge proportional to expected refill
          3. Never go below battery_to_ev_floor_soc
          4. Only discharge what the EV actually needs
          
        Returns dict with buffer_soc, priority_soc, buffer_start_soc, reasoning.
        """
        cfg = self.cfg
        floor = cfg.battery_to_ev_floor_soc
        bat_soc = bat_to_ev.get("bat_soc", 50)
        bat_cap = cfg.battery_capacity_kwh
        rt_eff = cfg.battery_charge_efficiency * cfg.battery_discharge_efficiency

        # --- Expected refill from solar ---
        solar_surplus_kwh = bat_to_ev.get("solar_surplus_kwh", 0)
        solar_refill_soc = min(90, (solar_surplus_kwh / bat_cap) * 100) if bat_cap > 0 else 0

        # --- Expected refill from cheap grid ---
        cheap_hours = bat_to_ev.get("cheap_hours", 0)
        grid_refill_kwh = cheap_hours * cfg.battery_charge_power_kw * cfg.battery_charge_efficiency
        grid_refill_soc = min(90, (grid_refill_kwh / bat_cap) * 100) if bat_cap > 0 else 0

        # --- Total expected refill (capped at realistic max) ---
        total_refill_soc = min(80, solar_refill_soc + grid_refill_soc)

        # --- How deep can we safely go? ---
        # If we expect 40% refill, we can afford to discharge 40% for EV
        safe_discharge_soc = total_refill_soc * 0.8  # 80% confidence factor
        dynamic_floor = max(floor, int(bat_soc - safe_discharge_soc))

        # --- But only discharge what EV actually needs ---
        ev_need_kwh = bat_to_ev.get("ev_need_kwh", 0)
        ev_need_soc = (ev_need_kwh / (bat_cap * rt_eff)) * 100 if bat_cap > 0 else 0
        target_soc = max(dynamic_floor, int(bat_soc - ev_need_soc))

        # --- evcc parameters ---
        # bufferSoc: above this, battery may power EV in PV mode
        buffer_soc = max(floor, target_soc)
        # prioritySoc: below this, battery has absolute priority
        priority_soc = max(cfg.battery_min_soc, floor - 5)
        # bufferStartSoc: above this, EV may start without PV surplus
        buffer_start_soc = min(90, buffer_soc + 10)

        # Reasoning for dashboard
        parts = []
        if solar_refill_soc > 5:
            parts.append(f"☀️ Solar: +{solar_refill_soc:.0f}% erwartet")
        if grid_refill_soc > 5:
            parts.append(f"⚡ Günstig-Netz: +{grid_refill_soc:.0f}% möglich")
        if ev_need_soc > 0:
            parts.append(f"🚗 EV braucht: {ev_need_soc:.0f}% (inkl. Verluste)")
        parts.append(f"🛡️ Untergrenze: {floor}%")

        return {
            "buffer_soc": int(buffer_soc),
            "priority_soc": int(priority_soc),
            "buffer_start_soc": int(buffer_start_soc),
            "dynamic_floor": int(dynamic_floor),
            "solar_refill_pct": round(solar_refill_soc, 1),
            "grid_refill_pct": round(grid_refill_soc, 1),
            "total_refill_pct": round(total_refill_soc, 1),
            "ev_need_pct": round(ev_need_soc, 1),
            "reasoning": " · ".join(parts),
        }

    def apply_battery_to_ev(self, bat_to_ev: dict, ev_connected: bool) -> bool:
        """Activate or deactivate battery-to-EV discharge mode with dynamic limits.
        
        When profitable:
          - Calculate dynamic bufferSoc/prioritySoc from forecasts
          - Set evcc parameters via API
          - Enable discharge control
        
        When not profitable or no EV:
          - Restore default buffer settings
        """
        if not bat_to_ev:
            return False

        is_profitable = bat_to_ev.get("is_profitable", False)
        usable = bat_to_ev.get("usable_kwh", 0)
        should_activate = is_profitable and usable > 0.5 and ev_connected

        if should_activate:
            # Calculate dynamic limits
            if self.cfg.battery_to_ev_dynamic_limit:
                limits = self.calculate_dynamic_discharge_limit(bat_to_ev)
                new_buffer = limits["buffer_soc"]
                new_priority = limits["priority_soc"]
                new_start = limits["buffer_start_soc"]

                # Only update evcc if values changed (avoid API spam)
                if new_buffer != self._last_buffer_soc:
                    self.evcc.set_buffer_soc(new_buffer)
                    self._last_buffer_soc = new_buffer
                if new_priority != self._last_priority_soc:
                    self.evcc.set_priority_soc(new_priority)
                    self._last_priority_soc = new_priority
                self.evcc.set_buffer_start_soc(new_start)

                bat_to_ev["dynamic_limits"] = limits

            if not self._bat_to_ev_active:
                log("info", f"🔋→🚗 Aktiviere Batterie-Entladung für EV "
                    f"(spare {bat_to_ev.get('savings_ct_per_kwh', 0):.0f}ct/kWh, "
                    f"{usable:.0f}kWh verfügbar)")
                if self.cfg.battery_to_ev_dynamic_limit:
                    log("info", f"   bufferSoc={new_buffer}% prioritySoc={new_priority}%")
                self.evcc.set_battery_discharge_control(True)
                self._bat_to_ev_active = True

            return True

        elif self._bat_to_ev_active:
            log("info", "🔋→🚗 Deaktiviere Batterie-Entladung für EV")
            # Restore conservative defaults
            if self.cfg.battery_to_ev_dynamic_limit:
                self.evcc.set_buffer_soc(self.cfg.battery_max_soc)
                self.evcc.set_priority_soc(self.cfg.battery_min_soc + 10)
                self.evcc.set_buffer_start_soc(0)  # 0 = disabled
                self._last_buffer_soc = None
                self._last_priority_soc = None
            self._bat_to_ev_active = False

        return self._bat_to_ev_active
