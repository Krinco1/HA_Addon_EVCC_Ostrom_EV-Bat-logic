"""
EVCC-Smartload v4.0.0 – Hybrid LP + Shadow RL Optimizer

Entry point. Initialises all components and runs the main decision loop.
"""

import time
from typing import Optional

from version import VERSION
from logging_util import log
from config import load_config
from evcc_client import EvccClient
from influxdb_client import InfluxDBClient
from state import Action, ManualSocStore, SystemState
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

    log("info", "Starting main decision loop...")

    while True:
        try:
            state = collector.get_current_state()
            if not state:
                log("warning", "Could not get system state")
                time.sleep(60)
                continue

            events = event_detector.detect(state)
            if events:
                log("info", f"Events: {events}")

            tariffs = evcc.get_tariff_grid()

            # LP decision (production)
            lp_action = optimizer.optimize(state, tariffs)

            # RL decision (shadow)
            rl_action = rl_agent.select_action(state, explore=True)

            # Update web server
            web.update_state(state, lp_action, rl_action)

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
            comparator.compare_per_device(state, lp_action, rl_action, actual_cost, rl_devices)

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
