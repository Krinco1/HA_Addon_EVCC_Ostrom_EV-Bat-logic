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
from rl_agent import ResidualRLAgent
from seasonal_learner import SeasonalLearner
from forecast_reliability import ForecastReliabilityTracker
from reaction_timing import ReactionTimingTracker
from comparator import Comparator, RLDeviceController
from controller import Controller
from vehicle_monitor import DataCollector, VehicleMonitor
from charge_sequencer import ChargeSequencer
from driver_manager import DriverManager
from web import WebServer
from plan_snapshotter import PlanSnapshotter
from override_manager import OverrideManager
from departure_store import DepartureTimeStore
from evcc_mode_controller import EvccModeController
from battery_arbitrage import run_battery_arbitrage


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
    plan_snapshotter = PlanSnapshotter(influx)
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

    # --- Phase 5: DynamicBufferCalc (situational battery min SoC) ---
    buffer_calc = None
    try:
        from dynamic_buffer import DynamicBufferCalc
        buffer_calc = DynamicBufferCalc(cfg, evcc)
        log("info", "DynamicBufferCalc: initialized")
    except Exception as e:
        log("warning", f"DynamicBufferCalc: init failed ({e}), buffer management disabled")

    # --- Phase 8: ResidualRLAgent (replaces DQNAgent) ---
    rl_agent = None
    try:
        rl_agent = ResidualRLAgent(cfg)
        log("info", f"ResidualRLAgent: initialized (mode={rl_agent.mode})")
    except Exception as e:
        log("warning", f"ResidualRLAgent: init failed ({e}), RL corrections disabled")

    event_detector = EventDetector()
    comparator = Comparator(cfg)
    controller = Controller(evcc, cfg)
    rl_devices = RLDeviceController(cfg)

    # --- Phase 8: Learning subsystems ---
    seasonal_learner = None
    try:
        seasonal_learner = SeasonalLearner()
        log("info", f"SeasonalLearner: {seasonal_learner.populated_cell_count()} cells populated")
    except Exception as e:
        log("warning", f"SeasonalLearner init failed: {e}")

    forecast_reliability = None
    try:
        forecast_reliability = ForecastReliabilityTracker()
        log("info", "ForecastReliabilityTracker initialized")
    except Exception as e:
        log("warning", f"ForecastReliabilityTracker init failed: {e}")

    reaction_timing = None
    try:
        reaction_timing = ReactionTimingTracker()
        log("info", "ReactionTimingTracker initialized")
    except Exception as e:
        log("warning", f"ReactionTimingTracker init failed: {e}")

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

    # --- Phase 7: Override Manager (Boost Charge) ---
    override_manager = None
    try:
        override_manager = OverrideManager(cfg, evcc, notifier)
        log("info", "OverrideManager: initialized")
    except Exception as e:
        log("warning", f"OverrideManager: init failed ({e}), boost-charge disabled")

    # Inject override_manager into notifier for Telegram command handling
    if notifier is not None and override_manager is not None:
        notifier.override_manager = override_manager

    # --- Phase 7 Plan 02: DepartureTimeStore (proactive departure queries) ---
    departure_store = None
    try:
        departure_store = DepartureTimeStore(default_hour=cfg.ev_charge_deadline_hour)
        log("info", "DepartureTimeStore: initialized")
    except Exception as e:
        log("warning", f"DepartureTimeStore: init failed ({e}), departure queries disabled")

    # Inject departure_store into notifier, web server, and sequencer
    if notifier is not None and departure_store is not None:
        notifier.departure_store = departure_store
    web.departure_store = departure_store
    # Phase 7 Plan 03: urgency scoring needs departure times
    if sequencer is not None and departure_store is not None:
        sequencer.departure_store = departure_store

    # --- Phase 11: evcc Mode Controller (mode selection + override detection) ---
    mode_controller = None
    try:
        mode_controller = EvccModeController(evcc, cfg)
        log("info", "EvccModeController: initialized")
    except Exception as e:
        log("warning", f"EvccModeController: init failed ({e}), mode control disabled")

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
    web.buffer_calc = buffer_calc
    web.plan_snapshotter = plan_snapshotter
    web.override_manager = override_manager
    # Phase 8: Learning subsystems (late attribute assignment, consistent with other components)
    web.seasonal_learner = seasonal_learner
    web.forecast_reliability = forecast_reliability
    web.reaction_timing = reaction_timing
    # Phase 11: Mode controller
    web.mode_controller = mode_controller

    # --- Main decision loop ---
    last_state: Optional[SystemState] = None
    learning_steps = 0
    # Phase 7 Plan 02: plug-in detection state
    last_ev_connected = False
    last_ev_name = ""
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

            # --- Phase 7 Plan 02: Plug-in detection ---
            # Detect ev_connected False→True transition. Guard against cycles where
            # ev_name is empty (evcc may not have resolved the vehicle yet): only
            # update last_ev_connected when we have a name or the EV has disconnected.
            ev_just_plugged_in = state.ev_connected and not last_ev_connected
            if ev_just_plugged_in and state.ev_name and notifier and departure_store:
                if not departure_store.is_inquiry_pending(state.ev_name):
                    notifier.send_departure_inquiry(state.ev_name, state.ev_soc)
                    departure_store.mark_inquiry_sent(state.ev_name)
            if state.ev_name or not state.ev_connected:
                last_ev_connected = state.ev_connected
                last_ev_name = state.ev_name or ""

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

            # --- Phase 8: Forecast reliability updates ---
            # Update per-source rolling MAE before planner so confidence factors
            # are fresh for this cycle's LP call.
            if forecast_reliability is not None:
                current_slot_idx = _current_slot_index()

                # PV reliability: convert W -> kW (Pitfall 4 from research)
                if pv_96 is not None and state.pv_power is not None:
                    actual_pv_kw = state.pv_power / 1000.0
                    if 0 <= current_slot_idx < len(pv_96):
                        try:
                            forecast_reliability.update("pv", actual=actual_pv_kw, forecast=pv_96[current_slot_idx])
                        except Exception as e:
                            log("debug", f"ForecastReliabilityTracker.update(pv) error: {e}")

                # Consumption reliability
                if consumption_96 is not None and state.home_power is not None:
                    if 0 <= current_slot_idx < len(consumption_96):
                        try:
                            forecast_reliability.update("consumption", actual=state.home_power, forecast=consumption_96[current_slot_idx])
                        except Exception as e:
                            log("debug", f"ForecastReliabilityTracker.update(consumption) error: {e}")

                # Price reliability
                if tariffs and state.current_price is not None:
                    try:
                        forecast_reliability.update("price", actual=state.current_price, forecast=float(tariffs[0].get("value", state.current_price)))
                    except Exception as e:
                        log("debug", f"ForecastReliabilityTracker.update(price) error: {e}")

            # Build confidence factors for planner (None if tracker unavailable)
            confidence_factors = None
            if forecast_reliability is not None:
                confidence_factors = {
                    "pv": forecast_reliability.get_confidence("pv"),
                    "consumption": forecast_reliability.get_confidence("consumption"),
                    "price": forecast_reliability.get_confidence("price"),
                }

            # PV reliability factor for buffer calc
            pv_reliability = 1.0
            if forecast_reliability is not None:
                pv_reliability = forecast_reliability.get_confidence("pv")

            # --- Phase 8.1: Seasonal cost correction ---
            _seasonal_corr = _seasonal_correction_eur(seasonal_learner, datetime.now(timezone.utc))
            if _seasonal_corr != 0.0:
                log("info", f"Seasonal correction: {_seasonal_corr:+.4f} EUR/kWh applied to LP objective")

            # --- Phase 4: Predictive Planner (LP-based) ---
            plan = None
            if horizon_planner is not None and consumption_96 is not None and pv_96 is not None:
                plan = horizon_planner.plan(
                    state=state,
                    tariffs=tariffs,
                    consumption_96=consumption_96,
                    pv_96=pv_96,
                    ev_departure_times=_get_departure_times(departure_store, cfg, state),
                    confidence_factors=confidence_factors,
                    seasonal_correction_eur=_seasonal_corr,
                )

            # --- Phase 7: Check Boost Charge override ---
            # If a driver override is active, skip LP-based EV action; evcc stays in 'now' mode.
            _override_status = override_manager.get_status() if override_manager else {"active": False}
            _override_active = _override_status.get("active", False)

            if plan is not None:
                lp_action = _action_from_plan(plan, state)
                store.update_plan(plan)
                try:
                    actual_state = {
                        "battery_power": state.battery_power,
                        "ev_power": state.ev_power,
                        "current_price": state.current_price,
                    }
                    plan_snapshotter.write_snapshot(plan, actual_state)
                except Exception as e:
                    log("warning", f"plan_snapshotter.write_snapshot error: {e}")
                log("info", f"Decision: LP plan (cost={plan.solver_fun:.4f} EUR), "
                             f"bat={'charge' if plan.current_bat_charge else 'discharge' if plan.current_bat_discharge else 'hold'}, "
                             f"ev={'charge' if plan.current_ev_charge else 'off'}")
            else:
                # Fallback: holistic optimizer (unchanged from Phase 3)
                lp_action = optimizer.optimize(state, tariffs)
                log("info", "Decision: HolisticOptimizer fallback")

            # --- Phase 8: ResidualRLAgent shadow/advisory mode branching ---
            # Skip RL entirely if agent not available or boost override is active.
            # (Pitfall 5 from research: override state pollutes shadow audit log.)
            override_active = _override_active  # alias for clarity

            # Track action index for RL learning step later
            _rl_bat_delta_ct: float = 0.0
            _rl_ev_delta_ct: float = 0.0
            _rl_action_idx: int = 0

            if rl_agent is not None and not override_active:
                _rl_bat_delta_ct, _rl_ev_delta_ct = rl_agent.select_delta(state, explore=True)
                # Derive action index from deltas for learning step
                from rl_agent import DELTA_OPTIONS_CT, N_EV_DELTAS
                try:
                    bat_idx = DELTA_OPTIONS_CT.index(_rl_bat_delta_ct)
                    ev_idx = DELTA_OPTIONS_CT.index(_rl_ev_delta_ct)
                    _rl_action_idx = bat_idx * N_EV_DELTAS + ev_idx
                except (ValueError, IndexError):
                    _rl_action_idx = 0

                if rl_agent.mode == "shadow":
                    # Log correction but do NOT apply (shadow mode)
                    rl_agent.log_shadow_correction(
                        _rl_bat_delta_ct, _rl_ev_delta_ct,
                        plan_bat_price_ct=(lp_action.battery_limit_eur or 0) * 100,
                        plan_ev_price_ct=(lp_action.ev_limit_eur or 0) * 100,
                        state=state,
                        is_override_active=override_active,
                    )
                    if _override_active:
                        final = Action(
                            battery_action=lp_action.battery_action,
                            battery_limit_eur=lp_action.battery_limit_eur,
                            ev_action=1,        # keep charging; override already set evcc to 'now'
                            ev_limit_eur=None,
                        )
                    else:
                        final = lp_action  # unmodified LP plan in shadow mode

                elif rl_agent.mode == "advisory":
                    adj_bat_ct, adj_ev_ct = rl_agent.apply_correction(
                        plan_bat_price_ct=(lp_action.battery_limit_eur or 0) * 100,
                        plan_ev_price_ct=(lp_action.ev_limit_eur or 0) * 100,
                        delta_bat_ct=_rl_bat_delta_ct,
                        delta_ev_ct=_rl_ev_delta_ct,
                        state=state,
                    )
                    if _override_active:
                        final = Action(
                            battery_action=lp_action.battery_action,
                            battery_limit_eur=adj_bat_ct / 100,
                            ev_action=1,        # keep charging; override already set evcc to 'now'
                            ev_limit_eur=None,
                        )
                    else:
                        final = Action(
                            battery_action=lp_action.battery_action,
                            battery_limit_eur=adj_bat_ct / 100,
                            ev_action=lp_action.ev_action,
                            ev_limit_eur=adj_ev_ct / 100,
                        )
                else:
                    # Unknown mode — fall through to LP plan
                    if _override_active:
                        final = Action(
                            battery_action=lp_action.battery_action,
                            battery_limit_eur=lp_action.battery_limit_eur,
                            ev_action=1,
                            ev_limit_eur=None,
                        )
                    else:
                        final = lp_action

            else:
                # RL agent unavailable or override active: use LP plan as-is
                if _override_active:
                    final = Action(
                        battery_action=lp_action.battery_action,
                        battery_limit_eur=lp_action.battery_limit_eur,
                        ev_action=1,        # keep charging; evcc already in 'now' mode
                        ev_limit_eur=None,
                    )
                else:
                    final = lp_action

            actual_cost = controller.apply(final)

            # --- Phase 11: evcc Mode Control ---
            _mode_status = {"active": False, "override_active": False}
            if mode_controller is not None:
                _evcc_raw = collector._evcc_raw  # Raw evcc API dict for mode controller

                # Determine departure urgency for mode selection
                _departure_urgent = False
                if state.ev_connected and departure_store:
                    _dep_time = departure_store.get_departure(state.ev_name or "")
                    if _dep_time:
                        _hours_left = (_dep_time - datetime.now(timezone.utc)).total_seconds() / 3600
                        _soc_needed = max(0, cfg.ev_target_soc - state.ev_soc)
                        _hours_needed = (_soc_needed / 100 * (state.ev_capacity_kwh or 30)) / (state.ev_charge_power_kw or 11)
                        _departure_urgent = _hours_left < _hours_needed * 1.3

                # Skip mode control if Boost Charge override is active (Phase 7 takes precedence)
                if not _override_active:
                    try:
                        _mode_status = mode_controller.step(
                            state=state,
                            plan=plan,
                            evcc_state=_evcc_raw,
                            departure_urgent=_departure_urgent,
                        )
                    except Exception as e:
                        log("warning", f"EvccModeController.step error: {e}")
                        _mode_status = mode_controller.get_status()
                else:
                    _mode_status = mode_controller.get_status()

            # --- Phase 12: LP-Gated Battery-to-EV Arbitrage ---
            all_vehicles = vehicle_monitor.get_all_vehicles()
            any_ev_connected = any(v.connected_to_wallbox for v in all_vehicles.values())
            _arb_status = run_battery_arbitrage(
                cfg, state, controller, all_vehicles, tariffs, solar_forecast,
                any_ev_connected, plan=plan, mode_status=_mode_status,
                buffer_calc=buffer_calc,
            )

            # --- Phase 5: Dynamic Buffer ---
            buffer_result = None
            if buffer_calc is not None and not controller._bat_to_ev_active:
                try:
                    buffer_result = buffer_calc.step(
                        pv_confidence=pv_forecaster.confidence,
                        price_spread=state.price_spread,
                        pv_96=pv_96 or [],
                        now=datetime.now(timezone.utc),
                        pv_reliability_factor=pv_reliability,  # Phase 8: LERN-04
                    )
                except Exception as e:
                    log("warning", f"DynamicBufferCalc: step failed ({e})")

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
                rl_action=final,  # Phase 8: final action (rl-adjusted or lp fallback)
                solar_forecast=solar_forecast,
                consumption_forecast=consumption_96,
                pv_forecast=pv_96,
                pv_confidence=pv_forecaster.confidence,
                pv_correction_label=pv_forecaster.correction_label,
                pv_quality_label=pv_forecaster.quality_label,
                forecaster_ready=consumption_forecaster.is_ready,
                forecaster_data_days=consumption_forecaster.data_days,
                ha_warnings=ha_discovery_result.get("warnings", []),
                buffer_result=buffer_result,
                mode_control_status=_mode_status,  # Phase 11
                arbitrage_status=_arb_status,  # Phase 12
            )

            # --- Phase 8: Shared slot-0 cost computation ---
            # Computed once and used by SeasonalLearner, Comparator, and RL learning.
            # This prevents NameError when one learner is None but another needs the values.
            plan_slot0_cost = None
            actual_slot0_cost = None
            if plan is not None:
                plan_slot0_cost = _compute_slot0_cost(plan, state)
                actual_slot0_cost = _compute_actual_slot0_cost(state)

            # --- Phase 8: SeasonalLearner update (LERN-02) ---
            if seasonal_learner is not None:
                if plan_slot0_cost is not None and actual_slot0_cost is not None:
                    plan_error = actual_slot0_cost - plan_slot0_cost  # positive = plan was optimistic
                    try:
                        seasonal_learner.update(datetime.now(timezone.utc), plan_error)
                    except Exception as e:
                        log("debug", f"SeasonalLearner.update error: {e}")

            # --- Phase 8: ReactionTimingTracker update + re-plan trigger (LERN-03) ---
            if reaction_timing is not None and plan is not None:
                plan_action_str = _action_to_str(lp_action)
                actual_action_str = _action_to_str(final)
                try:
                    reaction_timing.update(plan_action_str, actual_action_str)
                    # LERN-03: trigger immediate re-plan when deviation won't self-correct
                    if plan_action_str != actual_action_str and reaction_timing.should_replan_immediately():
                        log("info", "ReactionTimingTracker: deviation unlikely to self-correct, triggering re-plan")
                        try:
                            plan = horizon_planner.plan(
                                state=state,
                                tariffs=tariffs,
                                consumption_96=consumption_96,
                                pv_96=pv_96,
                                ev_departure_times=_get_departure_times(departure_store, cfg, state),
                                confidence_factors=confidence_factors,
                                seasonal_correction_eur=_seasonal_corr,
                            )
                            if plan and plan.slots:
                                lp_action = _action_from_plan(plan, state)
                        except Exception as e:
                            log("warning", f"Immediate re-plan failed: {e}")
                except Exception as e:
                    log("debug", f"ReactionTimingTracker.update error: {e}")

            # --- Phase 8: Comparator residual update (uses shared slot-0 costs) ---
            if comparator is not None and rl_agent is not None and not override_active:
                if plan_slot0_cost is not None and actual_slot0_cost is not None:
                    try:
                        comparator.compare_residual(plan_slot0_cost, actual_slot0_cost, _rl_bat_delta_ct, _rl_ev_delta_ct)
                    except Exception as e:
                        log("debug", f"Comparator.compare_residual error: {e}")

            # --- Phase 8: RL learning step (uses shared slot-0 costs) ---
            if rl_agent is not None and not override_active:
                if plan_slot0_cost is not None and actual_slot0_cost is not None and last_state is not None:
                    try:
                        reward = rl_agent.calculate_reward(plan_slot0_cost, actual_slot0_cost)
                        rl_agent.learn_from_correction(last_state, _rl_action_idx, reward, state)
                        learning_steps += 1
                        if learning_steps % 50 == 0:
                            log("info", f"RL: {learning_steps} correction steps, ε={rl_agent.epsilon:.3f}")
                    except Exception as e:
                        log("debug", f"RL learn_from_correction error: {e}")

            # Legacy comparator metrics (backward-compat with /comparisons dashboard endpoint)
            try:
                comparator.compare(state, lp_action, final, actual_cost)
                comparator.compare_per_device(state, lp_action, final, actual_cost,
                                              rl_devices, all_vehicles=all_vehicles)
            except Exception as e:
                log("debug", f"Comparator.compare error: {e}")

            # --- Phase 8: Auto-promotion check (once per cycle when shadow elapsed) ---
            if rl_agent is not None and rl_agent.mode == "shadow":
                if rl_agent.shadow_elapsed_days() >= 30:
                    try:
                        audit_result = rl_agent.run_constraint_audit()
                        rl_agent.maybe_promote(audit_result)
                    except Exception as e:
                        log("debug", f"RL auto-promotion check error: {e}")

            last_state = state

            # --- Logging ---
            p20 = state.price_percentiles.get(20, 0) * 100
            bat_names = {0: "hold", 1: "P20", 2: "P40", 3: "P60", 4: "max", 5: "PV", 6: "dis"}
            rl_mode_label = f"[{rl_agent.mode}]" if rl_agent is not None else "[no-rl]"
            epsilon_label = f"ε={rl_agent.epsilon:.3f}" if rl_agent is not None else "ε=n/a"
            log("info",
                f"{rl_mode_label} Bat={bat_names.get(lp_action.battery_action, '?')} "
                f"EV={lp_action.ev_action} "
                f"price={state.current_price * 100:.1f}ct P20={p20:.1f}ct "
                f"spread={state.price_spread * 100:.1f}ct {epsilon_label}")

            try:
                log_main_cycle(decision_log, state, cfg, all_vehicles,
                               lp_action, final, comparator, tariffs,
                               solar_forecast, sequencer=sequencer)
            except Exception as e:
                log("debug", f"Decision log error: {e}")

            if rl_agent is not None and rl_agent.total_steps % 50 == 0 and rl_agent.total_steps > 0:
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

def _get_departure_times(departure_store, cfg, state=None) -> Dict[str, datetime]:
    """Return departure datetime per EV name for LP formulation.

    Phase 7 Plan 02: reads per-vehicle departure from DepartureTimeStore when available.
    Falls back to cfg.ev_charge_deadline_hour (original Phase 4 behaviour) when
    departure_store is None or no vehicle is currently connected.

    Args:
        departure_store: DepartureTimeStore instance (may be None for fallback).
        cfg: Config object with ev_charge_deadline_hour.
        state: Current SystemState (optional) — used to get connected vehicle name.

    Returns:
        Dict mapping vehicle_name -> departure datetime (UTC-aware).
    """
    now = datetime.now(timezone.utc)
    deadline_hour = getattr(cfg, 'ev_charge_deadline_hour', 6)

    def _default_deadline():
        d = now.replace(hour=deadline_hour, minute=0, second=0, microsecond=0)
        if d <= now:
            d += timedelta(days=1)
        return d

    if departure_store is None:
        return {"_default": _default_deadline()}

    # Build per-vehicle dict from DepartureTimeStore
    result: Dict[str, datetime] = {}

    # Include currently connected vehicle (if any)
    if state is not None and state.ev_connected and state.ev_name:
        result[state.ev_name] = departure_store.get(state.ev_name)

    # If no vehicle resolved, fall back to a single default entry
    if not result:
        result["_default"] = _default_deadline()

    return result


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


    # _run_bat_to_ev moved to battery_arbitrage.py (Phase 12)


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


_SEASONAL_DAMPING = 0.5        # Apply only 50% of historical error (conservative per user decision)
_SEASONAL_CAP_EUR_KWH = 0.05  # Max correction +/-5ct/kWh (safety cap)


def _seasonal_correction_eur(seasonal_learner, now: datetime) -> float:
    """Return a dampened, capped seasonal cost correction (EUR/kWh).

    Returns 0.0 when seasonal_learner is None or data is insufficient.
    Positive = plan historically underestimated costs -> raise cost -> charge less.
    Negative = plan historically overestimated costs -> lower cost -> charge more.

    Note: mean_error_eur from SeasonalLearner is an approximate EUR-per-slot value.
    The safety cap ensures the correction stays in a safe range regardless of exact
    unit interpretation. This is consistent with the 'dampen toward neutral' approach.
    """
    if seasonal_learner is None:
        return 0.0
    try:
        raw = seasonal_learner.get_correction_factor(now)
    except Exception:
        return 0.0
    if raw is None:
        return 0.0  # sparse data -- stay neutral
    dampened = raw * _SEASONAL_DAMPING
    return max(-_SEASONAL_CAP_EUR_KWH, min(_SEASONAL_CAP_EUR_KWH, dampened))


def _current_slot_index() -> int:
    """Return the current 15-min slot index (0..95) for the current UTC time.

    Phase 8: used by ForecastReliabilityTracker to look up the forecast value
    corresponding to the current cycle's actual measurement.

    Returns:
        int in [0, 95]: hour*4 + minute//15
    """
    now = datetime.now(timezone.utc)
    return now.hour * 4 + now.minute // 15


def _compute_slot0_cost(plan, state) -> Optional[float]:
    """Compute planned grid energy cost for slot 0 (15-min window, EUR).

    CRITICAL (Pitfall 2 from research): Do NOT use plan.solver_fun (full 24h LP
    objective). Use slot-0 only for per-cycle RL reward computation.

    Formula: slot0.price_eur_kwh * (bat_charge_kw + ev_charge_kw) * 0.25

    Args:
        plan: PlanHorizon with at least one slot.
        state: Current SystemState (unused but included for future extension).

    Returns:
        Float cost in EUR, or None if plan has no slots.
    """
    if plan is None or not plan.slots:
        return None
    slot0 = plan.slots[0]
    total_charge_kw = slot0.bat_charge_kw + slot0.ev_charge_kw
    return slot0.price_eur_kwh * total_charge_kw * 0.25


def _compute_actual_slot0_cost(state) -> Optional[float]:
    """Compute actual grid energy cost for the current 15-min window (EUR).

    Formula: current_price * actual_grid_power_kw * 0.25
    Grid power: state.grid_power (positive = importing from grid).

    Args:
        state: Current SystemState.

    Returns:
        Float cost in EUR, or None if current_price not available.
    """
    if state is None or state.current_price is None:
        return None
    grid_kw = max(0.0, getattr(state, "grid_power", 0) / 1000.0)
    return state.current_price * grid_kw * 0.25


def _action_to_str(action) -> str:
    """Convert an Action object to a ReactionTimingTracker action string.

    Maps Action battery/ev fields to canonical strings:
        bat_charge   — battery charging (action 1-4)
        bat_discharge — battery discharging (action 6)
        bat_hold     — battery holding (action 0)
        ev_charge    — EV charging (action 1+)
        ev_idle      — EV not charging (action 0)

    Returns compound string "bat_X/ev_Y" for combined identification.
    The tracker stores the first segment only for battery comparison;
    for simplicity we return the combined form and let tracker use it as-is.
    """
    if action is None:
        return "bat_hold/ev_idle"

    bat_act = getattr(action, "battery_action", 0)
    ev_act = getattr(action, "ev_action", 0)

    if bat_act in (1, 2, 3, 4):
        bat_str = "bat_charge"
    elif bat_act == 6:
        bat_str = "bat_discharge"
    else:
        bat_str = "bat_hold"

    ev_str = "ev_charge" if ev_act and ev_act > 0 else "ev_idle"

    return f"{bat_str}/{ev_str}"


if __name__ == "__main__":
    main()
