"""
EVCC-Smartload v5.0 – Hybrid LP + Shadow RL + Charge Sequencer

Entry point. Initialises all components and runs the main decision loop.

v5 additions:
  - Percentile computation every cycle (state.price_percentiles)
  - ChargeSequencer for multi-EV coordination
  - DriverManager + Telegram Bot (optional, requires drivers.yaml)
  - Notification triggers for charge inquiries and quiet-hour reminders
"""

import time
from datetime import datetime, timezone
from typing import Optional

from version import VERSION
from logging_util import log
from config import load_config
from evcc_client import EvccClient
from influxdb_client import InfluxDBClient
from state import Action, ManualSocStore, SystemState, calc_solar_surplus_kwh, compute_price_percentiles
from decision_log import DecisionLog, log_main_cycle
from optimizer import HolisticOptimizer, EventDetector
from rl_agent import DQNAgent
from comparator import Comparator, RLDeviceController
from controller import Controller
from vehicle_monitor import DataCollector, VehicleMonitor
from charge_sequencer import ChargeSequencer
from driver_manager import DriverManager
from web import WebServer


def main():
    log("info", "=" * 60)
    log("info", f"  EVCC-Smartload v{VERSION}")
    log("info", "  Hybrid LP + Shadow RL + Charge Sequencer")
    log("info", "=" * 60)

    cfg = load_config()
    log("info", f"Config: battery_max={cfg.battery_max_price_ct}ct, ev_max={cfg.ev_max_price_ct}ct, "
                f"quiet={cfg.quiet_hours_start}:00–{cfg.quiet_hours_end}:00, rl_auto={cfg.rl_auto_switch}")

    # --- Core infrastructure ---
    evcc = EvccClient(cfg)
    influx = InfluxDBClient(cfg)
    manual_store = ManualSocStore()

    # --- Energy management ---
    vehicle_monitor = VehicleMonitor(evcc, cfg, manual_store)
    collector = DataCollector(evcc, influx, cfg, vehicle_monitor)
    optimizer = HolisticOptimizer(cfg)
    rl_agent = DQNAgent(cfg)
    event_detector = EventDetector()
    comparator = Comparator(cfg)
    controller = Controller(evcc, cfg)
    rl_devices = RLDeviceController(cfg)

    # --- v5: EV charge sequencer ---
    sequencer = ChargeSequencer(cfg, evcc) if cfg.sequencer_enabled else None

    # --- v5: Driver manager + Telegram (optional) ---
    driver_mgr = DriverManager()
    telegram_bot = None
    notifier = None

    if driver_mgr.telegram_enabled:
        try:
            from notification import TelegramBot, NotificationManager
            telegram_bot = TelegramBot(driver_mgr.telegram_bot_token)
            notifier = NotificationManager(
                bot=telegram_bot,
                driver_manager=driver_mgr,
                on_soc_response=lambda vehicle, soc, chat_id:
                    _handle_soc_response(sequencer, vehicle_monitor, vehicle, soc),
            )
            telegram_bot.start_polling()
            log("info", f"Telegram Bot aktiv für {len(driver_mgr.drivers)} Fahrer")
        except Exception as e:
            log("error", f"Telegram setup failed: {e}")
            notifier = None

    # --- RL bootstrap ---
    if not rl_agent.load():
        bootstrapped = rl_agent.bootstrap_from_influxdb(influx, hours=168)
        if bootstrapped:
            rl_agent.save()
            comparator.seed_from_bootstrap(bootstrapped)

    # --- Register all known devices for RL tracking ---
    rl_devices.get_device_mode("battery")
    for vp in cfg.vehicle_providers:
        vname = vp.get("evcc_name") or vp.get("name", "")
        if vname:
            rl_devices.get_device_mode(vname)
    rl_devices.dedup_case_duplicates()

    # --- Start background services ---
    collector.start_background_collection()
    vehicle_monitor.start_polling()

    decision_log = DecisionLog(max_entries=100)
    web = WebServer(
        cfg, optimizer, rl_agent, comparator, event_detector,
        collector, vehicle_monitor, rl_devices, manual_store,
        decision_log=decision_log,
        sequencer=sequencer,
        driver_mgr=driver_mgr,
        notifier=notifier,
    )
    web.start()

    # --- Main decision loop ---
    last_state: Optional[SystemState] = None
    last_rl_action: Optional[Action] = None
    learning_steps = 0
    registered_rl_devices: set = {"battery"} | {
        vp.get("evcc_name") or vp.get("name", "")
        for vp in cfg.vehicle_providers
        if vp.get("evcc_name") or vp.get("name")
    }
    registered_rl_lower: set = {n.lower() for n in registered_rl_devices}

    log("info", "Starting main decision loop (v5)...")

    while True:
        try:
            state = collector.get_current_state()
            if not state:
                log("warning", "Could not get system state")
                time.sleep(60)
                continue

            # Fetch prices + forecasts first — needed for percentile computation
            tariffs = evcc.get_tariff_grid()
            solar_forecast = evcc.get_tariff_solar()

            # --- v5: Enrich SystemState with percentile context ---
            if tariffs:
                state.price_percentiles = compute_price_percentiles(tariffs)
                state.price_spread = (
                    state.price_percentiles.get(80, 0)
                    - state.price_percentiles.get(20, 0)
                )
                now_utc = datetime.now(timezone.utc)
                state.hours_cheap_remaining = sum(
                    1 for t in tariffs
                    if float(t.get("value", 1)) <= state.price_percentiles.get(30, 0.20)
                )
                state.solar_forecast_total_kwh = sum(
                    max(0, float(t.get("value", 0))) for t in solar_forecast
                ) * (0.001 if solar_forecast and float(solar_forecast[0].get("value", 0)) > 100 else 1.0)

            # Dynamic RL device registration
            for vname in vehicle_monitor.get_all_vehicles():
                if vname not in registered_rl_devices and vname.lower() not in registered_rl_lower:
                    rl_devices.get_device_mode(vname)
                    registered_rl_devices.add(vname)
                    registered_rl_lower.add(vname.lower())

            events = event_detector.detect(state)

            # --- LP decision (production) ---
            lp_action = optimizer.optimize(state, tariffs)

            # --- RL decision (shadow) ---
            rl_action = rl_agent.select_action(state, explore=True)

            # --- Per-device mode selection ---
            bat_mode = rl_devices.get_device_mode("battery")
            ev_mode = (
                rl_devices.get_device_mode(state.ev_name)
                if state.ev_connected and state.ev_name
                else "lp"
            )

            final = Action(
                battery_action=rl_action.battery_action if bat_mode == "rl" else lp_action.battery_action,
                battery_limit_eur=rl_action.battery_limit_eur if bat_mode == "rl" else lp_action.battery_limit_eur,
                ev_action=rl_action.ev_action if ev_mode == "rl" else lp_action.ev_action,
                ev_limit_eur=rl_action.ev_limit_eur if ev_mode == "rl" else lp_action.ev_limit_eur,
            )

            actual_cost = controller.apply(final)

            # --- Battery-to-EV optimisation ---
            all_vehicles = vehicle_monitor.get_all_vehicles()
            any_ev_connected = any(v.connected_to_wallbox for v in all_vehicles.values())
            _run_bat_to_ev(cfg, state, controller, all_vehicles, tariffs, solar_forecast, any_ev_connected)

            # --- v5: Charge Sequencer ---
            now = datetime.now(timezone.utc)
            if sequencer is not None:
                connected_vehicle = next(
                    (n for n, v in all_vehicles.items() if v.connected_to_wallbox), None
                )
                sequencer.plan(tariffs, solar_forecast, connected_vehicle, now)
                sequencer.apply_to_evcc(now)

                # Quiet-hours plug reminder via Telegram
                if notifier:
                    rec = sequencer.get_pre_quiet_recommendation(now)
                    if rec:
                        notifier.send_plug_reminder(rec["vehicle"], rec["message"])

            # --- Notification triggers (charge inquiry) ---
            if notifier and sequencer is not None:
                _check_notification_triggers(
                    notifier, driver_mgr, sequencer, all_vehicles,
                    tariffs, state, cfg,
                )

            # --- Update web server ---
            web.update_state(state, lp_action, rl_action, solar_forecast=solar_forecast)

            # --- RL learning ---
            rl_agent.imitation_learn(state, lp_action)
            if last_state is not None and last_rl_action is not None:
                reward = comparator.calculate_reward(last_state, last_rl_action, state, events)
                priority = 2.0 if events else 1.0
                rl_agent.learn(last_state, last_rl_action, reward, state, False, priority)
                learning_steps += 1
                if learning_steps % 50 == 0:
                    log("info", f"RL: {learning_steps} steps, ε={rl_agent.epsilon:.3f}")

            comparator.compare(state, lp_action, rl_action, actual_cost)
            comparator.compare_per_device(state, lp_action, rl_action, actual_cost,
                                          rl_devices, all_vehicles=all_vehicles)

            last_state = state
            last_rl_action = rl_action

            # --- Logging ---
            p20 = state.price_percentiles.get(20, 0) * 100
            bat_names = {0: "hold", 1: "P20", 2: "P40", 3: "P60", 4: "max", 5: "PV", 6: "dis"}
            bi = "🟢" if bat_mode == "rl" else "🔵"
            log("info",
                f"{bi}Bat={bat_names.get(lp_action.battery_action, '?')} "
                f"EV={lp_action.ev_action} "
                f"price={state.current_price * 100:.1f}ct P20={p20:.1f}ct "
                f"spread={state.price_spread * 100:.1f}ct ε={rl_agent.epsilon:.3f}")

            try:
                log_main_cycle(decision_log, state, cfg, all_vehicles,
                               lp_action, rl_action, comparator, tariffs,
                               solar_forecast, sequencer=sequencer)
            except Exception as e:
                log("debug", f"Decision log error: {e}")

            if rl_agent.total_steps % 50 == 0 and rl_agent.total_steps > 0:
                rl_agent.save()
                comparator.save()

            time.sleep(cfg.decision_interval_minutes * 60)

        except Exception as e:
            log("error", f"Main loop error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)


# =============================================================================
# Helpers
# =============================================================================

def _run_bat_to_ev(cfg, state, controller, all_vehicles, tariffs, solar_forecast, any_ev_connected):
    """Battery-to-EV discharge optimisation (unchanged logic from v4)."""
    if not any_ev_connected or not tariffs:
        controller.apply_battery_to_ev({"is_profitable": False}, False)
        return

    total_ev_need = sum(
        max(0, (cfg.ev_target_soc - v.get_effective_soc()) / 100 * v.capacity_kwh)
        for v in all_vehicles.values()
        if v.get_effective_soc() > 0 or v.connected_to_wallbox or v.data_source == "direct_api"
    )
    if total_ev_need < 1:
        controller.apply_battery_to_ev({"is_profitable": False}, False)
        return

    bat_available = max(0, (state.battery_soc - cfg.battery_min_soc) / 100 * cfg.battery_capacity_kwh)
    rt_eff = cfg.battery_charge_efficiency * cfg.battery_discharge_efficiency
    bat_cost_ct = cfg.battery_max_price_ct / rt_eff
    grid_ct = state.current_price * 100
    savings = grid_ct - bat_cost_ct

    home_kw = state.home_power / 1000 if state.home_power else 1.0
    solar_surplus_kwh = calc_solar_surplus_kwh(solar_forecast, home_kw)
    cheap_hours = sum(1 for t in tariffs if float(t.get("value", 1)) * 100 <= cfg.battery_max_price_ct)

    controller.apply_battery_to_ev({
        "is_profitable": savings >= cfg.battery_to_ev_min_profit_ct,
        "usable_kwh": min(bat_available, total_ev_need),
        "savings_ct_per_kwh": savings,
        "bat_soc": state.battery_soc,
        "ev_need_kwh": total_ev_need,
        "solar_surplus_kwh": solar_surplus_kwh,
        "cheap_hours": cheap_hours,
    }, any_ev_connected)


def _handle_soc_response(sequencer, vehicle_monitor, vehicle_name: str, target_soc: int):
    """Callback: driver confirmed target SoC via Telegram."""
    if sequencer is None:
        return
    vehicles = vehicle_monitor.get_all_vehicles()
    v = vehicles.get(vehicle_name)
    if v:
        sequencer.add_request(
            vehicle=vehicle_name,
            driver="",
            target_soc=target_soc,
            current_soc=v.get_effective_soc(),
            capacity_kwh=v.capacity_kwh,
            charge_power_kw=getattr(v, "charge_power_kw", None) or 11.0,
        )


def _check_notification_triggers(notifier, driver_mgr, sequencer, all_vehicles,
                                  tariffs, state, cfg):
    """Send charge inquiries when price is attractive and vehicle is not yet in sequencer."""
    p30 = state.price_percentiles.get(30, state.current_price)
    price_is_cheap = state.current_price <= p30

    if not price_is_cheap:
        return

    for name, v in all_vehicles.items():
        # Skip if already in sequencer
        if name in sequencer.requests:
            continue

        soc = v.get_effective_soc()
        need_kwh = max(0, (cfg.ev_target_soc - soc) / 100 * v.capacity_kwh)
        if need_kwh < 2:
            continue  # nothing meaningful to charge

        driver = driver_mgr.get_driver(name)
        if not driver or not driver.telegram_chat_id:
            continue

        reason = (
            f"Günstiger Strom: {state.current_price * 100:.1f}ct (P30={p30 * 100:.1f}ct)\n"
            f"Bedarf: {need_kwh:.0f} kWh bis {cfg.ev_target_soc}%"
        )
        notifier.send_charge_inquiry(name, soc, reason)


if __name__ == "__main__":
    main()
