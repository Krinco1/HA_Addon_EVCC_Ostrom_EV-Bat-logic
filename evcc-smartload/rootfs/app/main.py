"""
EVCC-Smartload v6.0 – Hybrid LP + Shadow RL + Charge Sequencer

Entry point. Initialises all components and runs the main decision loop.

v6 additions:
  - StateStore: thread-safe, RLock-guarded single source of truth for shared state
  - All state writes go through store.update(); web server reads only via snapshot()
  - SSE endpoint /events broadcasts live state to dashboard (no polling required)

v5 additions (preserved):
  - Percentile computation every cycle (state.price_percentiles)
  - ChargeSequencer for multi-EV coordination
  - DriverManager + Telegram Bot (optional, requires drivers.yaml)
  - Notification triggers for charge inquiries and quiet-hour reminders
"""

import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from version import VERSION
from logging_util import log
from config import load_config
from config_validator import ConfigValidator
from evcc_client import EvccClient
from influxdb_client import InfluxDBClient
from state import Action, ManualSocStore, SystemState, calc_solar_surplus_kwh, compute_price_percentiles
from state_store import StateStore
from forecaster import ConsumptionForecaster, PVForecaster
from forecaster.ha_energy import run_entity_discovery
from decision_log import DecisionLog, log_main_cycle
from optimizer import HolisticOptimizer, EventDetector
from optimizer.planner import HorizonPlanner
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
                f"quiet={cfg.quiet_hours_start}:00\u2013{cfg.quiet_hours_end}:00, rl_auto={cfg.rl_auto_switch}")

    # --- v6.1: Config validation — runs before any I/O (fail-fast) ---
    validator = ConfigValidator()
    config_errors = validator.validate(cfg)
    critical = [e for e in config_errors if e.severity == "critical"]

    for e in config_errors:
        level = "error" if e.severity == "critical" else "warning"
        log(level, f"Config {e.field}: {e.message}")
        if e.suggestion:
            log(level, f"  -> {e.suggestion}")

    # Apply safe defaults for non-critical warnings before starting I/O
    for e in config_errors:
        if e.severity == "warning":
            if e.field == "battery_max_price_ct":
                log("warning", f"Setze battery_max_price_ct auf 25.0ct (war: {cfg.battery_max_price_ct})")
                cfg.battery_max_price_ct = 25.0
            elif e.field == "ev_max_price_ct":
                log("warning", f"Setze ev_max_price_ct auf 30.0ct (war: {cfg.ev_max_price_ct})")
                cfg.ev_max_price_ct = 30.0
            elif e.field == "decision_interval_minutes":
                log("warning", f"Setze decision_interval_minutes auf 15 (war: {cfg.decision_interval_minutes})")
                cfg.decision_interval_minutes = 15

    # --- v6: StateStore — single source of truth for shared state ---
    store = StateStore()

    # --- v6.1: Start WebServer early so error page is reachable even on critical errors ---
    # WebServer is created with config_errors and started before any I/O objects are built.
    # If critical errors exist, we block here; the web server stays alive serving the error page.
    # If no critical errors, we populate the remaining attributes below before the main loop.
    web = WebServer(cfg, store, config_errors=config_errors)
    web.start()

    if critical:
        log("error", f"Kritische Config-Fehler ({len(critical)} Fehler) - Add-on startet nicht. Bitte options.json pruefen.")
        log("error", "Fehlerseite erreichbar unter http://localhost:8099")
        while True:
            time.sleep(60)

    # --- Core infrastructure (only reached if no critical config errors) ---
    evcc = EvccClient(cfg)
    influx = InfluxDBClient(cfg)
    manual_store = ManualSocStore()

    # --- v7: Forecasters (Phase 3) ---
    consumption_forecaster = ConsumptionForecaster(influx, cfg)
    pv_forecaster = PVForecaster(evcc)

    # HA entity discovery in daemon thread (non-blocking, per Research Pitfall 3)
    ha_discovery_result = {"status": "pending"}
    if getattr(cfg, "ha_url", None) and getattr(cfg, "ha_token", None):
        def _ha_discover():
            ha_discovery_result.update(run_entity_discovery(cfg.ha_url, cfg.ha_token))
        threading.Thread(target=_ha_discover, daemon=True).start()

    # Initial PV forecast fetch before loop starts
    pv_forecaster.refresh()
    _last_pv_refresh = time.time()

    # --- Energy management ---
    vehicle_monitor = VehicleMonitor(evcc, cfg, manual_store)
    collector = DataCollector(evcc, influx, cfg, vehicle_monitor)
    optimizer = HolisticOptimizer(cfg)

    # --- Phase 4: HorizonPlanner (LP-based, graceful fallback if scipy unavailable) ---
    horizon_planner = None
    try:
        horizon_planner = HorizonPlanner(cfg)
        log("info", "HorizonPlanner: initialized (scipy/HiGHS LP solver)")
    except ImportError as e:
        log("warning", f"HorizonPlanner: scipy not available ({e}), using HolisticOptimizer only")
    except Exception as e:
        log("warning", f"HorizonPlanner: init failed ({e}), using HolisticOptimizer only")

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
        max_rec = getattr(cfg, "rl_bootstrap_max_records", 1000)
        bootstrapped = rl_agent.bootstrap_from_influxdb(influx, hours=168, max_records=max_rec)
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

    # --- v6: Populate WebServer with all components (server already started above) ---
    # The server was started early to serve the error page; now we attach all components
    # so API handlers have access to the optimizer, RL agent, comparator, etc.
    web.lp = optimizer
    web.rl = rl_agent
    web.comparator = comparator
    web.events = event_detector
    web.collector = collector
    web.vehicle_monitor = vehicle_monitor
    web.rl_devices = rl_devices
    web.manual_store = manual_store
    web.decision_log = decision_log
    web.sequencer = sequencer
    web.driver_mgr = driver_mgr
    web.notifier = notifier

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

    log("info", "Starting main decision loop (v6)...")

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

            # --- v7: Forecaster updates ---
            # ConsumptionForecaster: update every cycle (15 min)
            if state and state.home_power is not None:
                consumption_forecaster.update(state.home_power, datetime.now(timezone.utc))
                # Immediate self-correction: compare actual vs forecast for current slot
                current_forecast = consumption_forecaster.get_forecast_24h()
                if current_forecast and current_forecast[0] > 100:
                    consumption_forecaster.apply_correction(state.home_power, current_forecast[0])
                if not consumption_forecaster.is_ready:
                    log("info", f"Verbrauchsprognose nicht bereit ({consumption_forecaster.data_days}/1 Tage Daten), verwende Standardwerte")

            # PVForecaster: refresh hourly
            if time.time() - _last_pv_refresh > 3600:
                pv_forecaster.refresh()
                _last_pv_refresh = time.time()

            # PVForecaster: update correction coefficient every cycle
            if state and state.pv_power is not None:
                pv_kw = state.pv_power / 1000.0 if state.pv_power > 100 else state.pv_power
                pv_forecaster.update_correction(pv_kw, datetime.now(timezone.utc))

            # Collect forecast data for StateStore
            consumption_96 = consumption_forecaster.get_forecast_24h() if consumption_forecaster.is_ready else None
            pv_96 = pv_forecaster.get_forecast_24h()

            events = event_detector.detect(state)

            # --- Phase 4: Predictive Planner (LP-based) ---
            plan = None
            if horizon_planner is not None and consumption_96 is not None and pv_96 is not None:
                plan = horizon_planner.plan(
                    state=state,
                    tariffs=tariffs,
                    consumption_96=consumption_96,
                    pv_96=pv_96,
                    ev_departure_times=_get_departure_times(cfg),
                )

            if plan is not None:
                lp_action = _action_from_plan(plan, state)
                store.update_plan(plan)
                log("info", f"Decision: LP plan (cost={plan.solver_fun:.4f} EUR), "
                             f"bat={'charge' if plan.current_bat_charge else 'discharge' if plan.current_bat_discharge else 'hold'}, "
                             f"ev={'charge' if plan.current_ev_charge else 'off'}")
            else:
                # Fallback: holistic optimizer (unchanged from Phase 3)
                lp_action = optimizer.optimize(state, tariffs)
                log("info", "Decision: HolisticOptimizer fallback")

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
                # Sync current SoC into all active sequencer requests every cycle
                for vname, vdata in all_vehicles.items():
                    if vname in sequencer.requests:
                        sequencer.update_soc(vname, vdata.get_effective_soc())

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

            # --- v6: Update StateStore (replaces web.update_state) ---
            # All state writes go through StateStore; web server reads only via snapshot().
            # This call also broadcasts to all connected SSE clients.
            store.update(
                state=state,
                lp_action=lp_action,
                rl_action=rl_action,
                solar_forecast=solar_forecast,
                consumption_forecast=consumption_96,
                pv_forecast=pv_96,
                pv_confidence=pv_forecaster.confidence,
                pv_correction_label=pv_forecaster.correction_label,
                pv_quality_label=pv_forecaster.quality_label,
                forecaster_ready=consumption_forecaster.is_ready,
                forecaster_data_days=consumption_forecaster.data_days,
                ha_warnings=ha_discovery_result.get("warnings", []),
            )

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

def _get_departure_times(cfg) -> Dict[str, datetime]:
    """Return departure datetime per EV name for LP formulation.

    Phase 4: uses cfg.ev_charge_deadline_hour as the single deadline.
    Phase 7 will extend with per-driver Telegram input.
    """
    now = datetime.now(timezone.utc)
    deadline_hour = getattr(cfg, 'ev_charge_deadline_hour', 6)
    local_deadline = now.replace(hour=deadline_hour, minute=0, second=0, microsecond=0)
    if local_deadline <= now:
        local_deadline += timedelta(days=1)
    return {"_default": local_deadline}


def _action_from_plan(plan, state) -> "Action":
    """Convert LP PlanHorizon slot-0 decision to an Action for the controller.

    Maps continuous LP power values to discrete Action codes:
    - Battery: charge (1) / discharge (6) / hold (0)
    - EV: charge (1) / off (0)

    The slot-0 price_eur_kwh is used as the battery/ev price limit so the
    controller applies the correct evcc charge mode.
    """
    from state import Action
    slot0 = plan.slots[0]

    # Battery action
    if slot0.bat_charge_kw > 0.1:
        battery_action = 1  # charge (price-limited)
        battery_limit_eur = slot0.price_eur_kwh
    elif slot0.bat_discharge_kw > 0.1:
        battery_action = 6  # discharge
        battery_limit_eur = None
    else:
        battery_action = 0  # hold
        battery_limit_eur = None

    # EV action
    if slot0.ev_charge_kw > 0.1 and state.ev_connected:
        ev_action = 1  # charge (price-limited)
        ev_limit_eur = slot0.price_eur_kwh
    else:
        ev_action = 0  # off
        ev_limit_eur = None

    return Action(
        battery_action=battery_action,
        battery_limit_eur=battery_limit_eur,
        ev_action=ev_action,
        ev_limit_eur=ev_limit_eur,
    )


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
