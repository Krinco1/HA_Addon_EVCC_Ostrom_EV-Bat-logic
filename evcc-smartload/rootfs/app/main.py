"""
EVCC-Smartload v4.3.9 – Hybrid LP + Shadow RL Optimizer

Entry point. Initialises all components and runs the main decision loop.
"""

import time
from typing import Optional

from version import VERSION
from logging_util import log
from config import load_config
from evcc_client import EvccClient
from influxdb_client import InfluxDBClient
from state import Action, ManualSocStore, SystemState, calc_solar_surplus_kwh
from optimizer import HolisticOptimizer, EventDetector
from rl_agent import DQNAgent
from comparator import Comparator, RLDeviceController
from controller import Controller
from vehicle_monitor import DataCollector, VehicleMonitor
from web import WebServer


def main():
    log("info", "=" * 60)
    log("info", f"  EVCC-Smartload v{VERSION}")
    log("info", "  Hybrid LP + Shadow RL Energy Optimizer")
    log("info", "=" * 60)

    cfg = load_config()
    log("info", f"Config: battery_max={cfg.battery_max_price_ct}ct, ev_max={cfg.ev_max_price_ct}ct, "
                f"ev_deadline={cfg.ev_charge_deadline_hour}:00, rl_auto={cfg.rl_auto_switch}")

    # --- Infrastructure ---
    evcc = EvccClient(cfg)
    influx = InfluxDBClient(cfg)
    manual_store = ManualSocStore()

    # --- Core components ---
    vehicle_monitor = VehicleMonitor(evcc, cfg, manual_store)
    collector = DataCollector(evcc, influx, cfg, vehicle_monitor)
    optimizer = HolisticOptimizer(cfg)
    rl_agent = DQNAgent(cfg)
    event_detector = EventDetector()
    comparator = Comparator(cfg)
    controller = Controller(evcc, cfg)
    rl_devices = RLDeviceController(cfg)

    # --- RL bootstrap ---
    if not rl_agent.load():
        bootstrapped = rl_agent.bootstrap_from_influxdb(influx, hours=168)
        if bootstrapped:
            rl_agent.save()
            # Seed comparator so RL maturity reflects historical data
            comparator.seed_from_bootstrap(bootstrapped)

    # --- Register ALL known devices for RL tracking ---
    rl_devices.get_device_mode("battery")  # Always register battery
    # Pre-register from vehicles.yaml (available immediately, no polling needed)
    for vp in cfg.vehicle_providers:
        vname = vp.get("evcc_name") or vp.get("name", "")
        if vname:
            rl_devices.get_device_mode(vname)
            log("info", f"Pre-registered RL device: {vname}")

    # Dedup AFTER pre-registration (catches old DB entries with different case)
    rl_devices.dedup_case_duplicates()

    # --- Start background services ---
    collector.start_background_collection()
    vehicle_monitor.start_polling()

    web = WebServer(cfg, optimizer, rl_agent, comparator, event_detector,
                    collector, vehicle_monitor, rl_devices, manual_store)
    web.start()

    # --- Main decision loop ---
    last_state: Optional[SystemState] = None
    last_rl_action: Optional[Action] = None
    learning_steps = 0
    registered_rl_devices: set = {"battery"} | {
        vp.get("evcc_name") or vp.get("name", "") for vp in cfg.vehicle_providers if vp.get("evcc_name") or vp.get("name")
    }
    # Case-insensitive lookup for dedup (evcc may use different case than vehicles.yaml)
    registered_rl_lower: set = {n.lower() for n in registered_rl_devices}

    log("info", "Starting main decision loop...")

    while True:
        try:
            state = collector.get_current_state()
            if not state:
                log("warning", "Could not get system state")
                time.sleep(60)
                continue

            # Dynamic RL device registration (catches vehicles that appear after startup)
            for vname in vehicle_monitor.get_all_vehicles():
                if vname not in registered_rl_devices and vname.lower() not in registered_rl_lower:
                    rl_devices.get_device_mode(vname)
                    registered_rl_devices.add(vname)
                    registered_rl_lower.add(vname.lower())
                    log("info", f"Registered RL device: {vname}")

            events = event_detector.detect(state)
            if events:
                log("info", f"Events: {events}")

            tariffs = evcc.get_tariff_grid()
            solar_forecast = evcc.get_tariff_solar()
            if solar_forecast:
                log("debug", f"Solar forecast: {len(solar_forecast)} entries")

            # LP decision (production)
            lp_action = optimizer.optimize(state, tariffs)

            # RL decision (shadow)
            rl_action = rl_agent.select_action(state, explore=True)

            # Update web server
            web.update_state(state, lp_action, rl_action, solar_forecast=solar_forecast)

            # Imitation learning
            rl_agent.imitation_learn(state, lp_action)

            # Per-device mode selection
            bat_mode = rl_devices.get_device_mode("battery")
            ev_mode = rl_devices.get_device_mode(state.ev_name) if state.ev_connected and state.ev_name else "lp"

            final = Action(
                battery_action=rl_action.battery_action if bat_mode == "rl" else lp_action.battery_action,
                battery_limit_eur=rl_action.battery_limit_eur if bat_mode == "rl" else lp_action.battery_limit_eur,
                ev_action=rl_action.ev_action if ev_mode == "rl" else lp_action.ev_action,
                ev_limit_eur=rl_action.ev_limit_eur if ev_mode == "rl" else lp_action.ev_limit_eur,
            )

            actual_cost = controller.apply(final)

            # Battery-to-EV optimization
            all_vehicles = vehicle_monitor.get_all_vehicles()
            any_ev_connected = any(v.connected_to_wallbox for v in all_vehicles.values())
            if any_ev_connected and tariffs:
                total_ev_need = sum(
                    max(0, (cfg.ev_target_soc - v.get_effective_soc()) / 100 * v.capacity_kwh)
                    for v in all_vehicles.values()
                    if v.get_effective_soc() > 0 or v.connected_to_wallbox or v.data_source == "direct_api"
                )
                if total_ev_need > 1:
                    bat_available = max(0, (state.battery_soc - cfg.battery_min_soc) / 100 * cfg.battery_capacity_kwh)
                    rt_eff = cfg.battery_charge_efficiency * cfg.battery_discharge_efficiency
                    bat_cost_ct = cfg.battery_max_price_ct / rt_eff
                    grid_ct = state.current_price * 100
                    savings = grid_ct - bat_cost_ct

                    # Solar surplus estimate for refill calculation
                    home_kw = state.home_power / 1000 if state.home_power else 1.0
                    solar_surplus_kwh = calc_solar_surplus_kwh(solar_forecast, home_kw)

                    # Count cheap hours remaining
                    cheap_hours = sum(
                        1 for t in tariffs
                        if t.get("value", 1) * 100 <= cfg.battery_max_price_ct
                    )

                    bat_to_ev_info = {
                        "is_profitable": savings >= cfg.battery_to_ev_min_profit_ct,
                        "usable_kwh": min(bat_available, total_ev_need),
                        "savings_ct_per_kwh": savings,
                        "bat_soc": state.battery_soc,
                        "ev_need_kwh": total_ev_need,
                        "solar_surplus_kwh": solar_surplus_kwh,
                        "cheap_hours": cheap_hours,
                    }
                    controller.apply_battery_to_ev(bat_to_ev_info, any_ev_connected)
                else:
                    controller.apply_battery_to_ev({"is_profitable": False}, False)
            else:
                controller.apply_battery_to_ev({"is_profitable": False}, False)

            # RL learning
            if last_state is not None and last_rl_action is not None:
                reward = comparator.calculate_reward(last_state, last_rl_action, state, events)
                priority = 2.0 if events else 1.0
                rl_agent.learn(last_state, last_rl_action, reward, state, False, priority)
                learning_steps += 1
                if learning_steps % 50 == 0:
                    log("info", f"RL: {learning_steps} steps, mem={len(rl_agent.memory)}, ε={rl_agent.epsilon:.3f}")

            # Comparison
            comparator.compare(state, lp_action, rl_action, actual_cost)
            comparator.compare_per_device(state, lp_action, rl_action, actual_cost,
                                          rl_devices, all_vehicles=all_vehicles)

            last_state = state
            last_rl_action = rl_action

            # Logging
            bl = f"{lp_action.battery_limit_eur * 100:.1f}ct" if lp_action.battery_limit_eur else "none"
            el = f"{lp_action.ev_limit_eur * 100:.1f}ct" if lp_action.ev_limit_eur else "none"
            bi = "🟢" if bat_mode == "rl" else "🔵"
            ei = "🟢" if ev_mode == "rl" else "🔵"
            log("info", f"{bi}Bat={lp_action.battery_action}({bl}) {ei}EV={lp_action.ev_action}({el}) "
                        f"price={state.current_price * 100:.1f}ct ε={rl_agent.epsilon:.3f}")

            # Periodic save
            if rl_agent.total_steps % 50 == 0 and rl_agent.total_steps > 0:
                rl_agent.save()
                comparator.save()

            time.sleep(cfg.decision_interval_minutes * 60)

        except Exception as e:
            log("error", f"Main loop error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)


if __name__ == "__main__":
    main()
