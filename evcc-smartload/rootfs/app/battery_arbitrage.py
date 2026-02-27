"""
Phase 12: LP-Gated Battery-to-EV Arbitrage

Controls battery-to-EV discharge with 7 gates that all must pass:
  1. EV connected and needs charge
  2. LP authorizes battery discharge (current_bat_discharge)
  3. EV in 'now' mode (fast charging via mode controller)
  4. Economically profitable (accounting for ~85% roundtrip efficiency)
  5. No cheaper grid window in next 6h (lookahead guard)
  6. Battery SoC above floor: max(battery_to_ev_floor_soc, dynamic_buffer)
  7. No LP-planned grid discharge in same slot (mutual exclusion)
"""

from typing import Dict, List, Optional

from logging_util import log
from state import calc_solar_surplus_kwh


def run_battery_arbitrage(cfg, state, controller, all_vehicles, tariffs,
                          solar_forecast, any_ev_connected,
                          plan=None, mode_status=None, buffer_calc=None) -> Dict:
    """Evaluate all arbitrage gates and activate/deactivate battery-to-EV discharge.

    Returns status dict for StateStore/SSE/dashboard.
    """
    _inactive = {"active": False, "reason": None}

    if not any_ev_connected or not tariffs:
        controller.apply_battery_to_ev({"is_profitable": False}, False)
        return _inactive

    total_ev_need = sum(
        max(0, (cfg.ev_target_soc - v.get_effective_soc()) / 100 * v.capacity_kwh)
        for v in all_vehicles.values()
        if v.get_effective_soc() > 0 or v.connected_to_wallbox or v.data_source == "direct_api"
    )
    if total_ev_need < 1:
        controller.apply_battery_to_ev({"is_profitable": False}, False)
        return _inactive

    # --- Gate 3: EV must be in 'now' mode (fast charging) ---
    current_ev_mode = (mode_status or {}).get("current_mode")
    if current_ev_mode != "now":
        controller.apply_battery_to_ev({"is_profitable": False}, False)
        return {**_inactive, "reason": f"EV nicht im Sofortladen-Modus ({current_ev_mode})"}

    # --- Gate 2: LP must authorize battery discharge ---
    lp_authorizes = plan is not None and plan.current_bat_discharge
    if not lp_authorizes:
        controller.apply_battery_to_ev({"is_profitable": False}, False)
        reason = "LP plant keine Batterie-Entladung" if plan else "kein LP-Plan verfügbar"
        return {**_inactive, "reason": reason}

    # --- Gate 7: Mutual exclusion — LP grid discharge vs battery-to-EV ---
    if plan and plan.slots:
        slot0 = plan.slots[0]
        if slot0.bat_discharge_kw > 0.1 and slot0.ev_charge_kw < 0.1:
            controller.apply_battery_to_ev({"is_profitable": False}, False)
            log("info", "Phase 12: LP-Entladung aktiv (Grid), Battery-to-EV blockiert (Mutual Exclusion)")
            return {**_inactive, "reason": "LP entlaedt zur Netzeinspeisung (Mutual Exclusion)"}

    # --- Gate 6: Battery SoC floor ---
    dynamic_buffer_pct = cfg.battery_min_soc
    if buffer_calc is not None:
        with buffer_calc._lock:
            dynamic_buffer_pct = buffer_calc._current_buffer_pct
    effective_floor = max(cfg.battery_to_ev_floor_soc, dynamic_buffer_pct)

    bat_available = max(0, (state.battery_soc - effective_floor) / 100 * cfg.battery_capacity_kwh)
    if bat_available < 0.5:
        controller.apply_battery_to_ev({"is_profitable": False}, False)
        return {**_inactive, "reason": f"Batterie-SoC ({state.battery_soc:.0f}%) zu nah an Untergrenze ({effective_floor}%)"}

    # --- Gate 4: Profitability (85% roundtrip efficiency) ---
    rt_eff = cfg.battery_charge_efficiency * cfg.battery_discharge_efficiency
    bat_cost_ct = cfg.battery_max_price_ct / rt_eff
    grid_ct = state.current_price * 100
    savings = grid_ct - bat_cost_ct

    if savings < cfg.battery_to_ev_min_profit_ct:
        controller.apply_battery_to_ev({"is_profitable": False}, False)
        return {**_inactive, "reason": f"Nicht profitabel ({savings:.1f} ct/kWh < {cfg.battery_to_ev_min_profit_ct} ct Minimum)"}

    # --- Gate 5: 6h lookahead — block if cheaper grid window coming ---
    if plan and plan.slots:
        current_grid_ct = grid_ct
        lookahead_slots = plan.slots[1:25]  # Next 6h = 24 slots x 15min
        for slot in lookahead_slots:
            future_price_ct = slot.price_eur_kwh * 100
            if future_price_ct < current_grid_ct * 0.8:
                controller.apply_battery_to_ev({"is_profitable": False}, False)
                cheaper_time = slot.slot_start.strftime("%H:%M") if slot.slot_start else "?"
                log("info", f"Phase 12: Lookahead-Guard blockiert Entladung -- "
                            f"guenstigere Preise um {cheaper_time} ({future_price_ct:.1f} ct vs {current_grid_ct:.1f} ct)")
                return {**_inactive, "reason": f"Guenstigere Netzpreise um {cheaper_time} erwartet"}

    # --- All gates passed: activate battery-to-EV ---
    home_kw = state.home_power / 1000 if state.home_power else 1.0
    solar_surplus_kwh = calc_solar_surplus_kwh(solar_forecast, home_kw)
    cheap_hours = sum(1 for t in tariffs if float(t.get("value", 1)) * 100 <= cfg.battery_max_price_ct)

    usable = min(bat_available, total_ev_need)
    controller.apply_battery_to_ev({
        "is_profitable": True,
        "usable_kwh": usable,
        "savings_ct_per_kwh": savings,
        "bat_soc": state.battery_soc,
        "ev_need_kwh": total_ev_need,
        "solar_surplus_kwh": solar_surplus_kwh,
        "cheap_hours": cheap_hours,
    }, any_ev_connected)

    return {
        "active": controller._bat_to_ev_active,
        "reason": None,
        "savings_ct": round(savings, 1),
        "usable_kwh": round(usable, 1),
        "effective_floor_pct": effective_floor,
        "dynamic_buffer_pct": dynamic_buffer_pct,
    }
