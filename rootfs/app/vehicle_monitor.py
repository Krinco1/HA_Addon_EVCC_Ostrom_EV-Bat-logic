"""
Vehicle Monitor and Data Collector — v4 unchanged in v5.

VehicleMonitor:
  - Manages vehicle state, handles polling schedule
  - Exposes get_all_vehicles(), predict_charge_need(), trigger_refresh()

DataCollector:
  - Collects system state from evcc + vehicles
  - Runs background collection thread
  - Exposes get_current_state() → SystemState
"""

import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from config import Config
from logging_util import log
from state import ManualSocStore, SystemState
from vehicles.manager import VehicleManager
from vehicles.base import VehicleData


class VehicleMonitor:
    """Manages vehicle state and coordinates API polling."""

    def __init__(self, evcc, cfg: Config, manual_store: ManualSocStore):
        self.evcc = evcc
        self.cfg = cfg
        self.manual_store = manual_store
        self._manager = VehicleManager(cfg.vehicle_providers)
        self._lock = threading.Lock()
        self._refresh_requested: set = set()
        self._poll_interval_sec = cfg.vehicle_poll_interval_minutes * 60
        self._last_poll: Dict[str, float] = {}
        self._thread: Optional[threading.Thread] = None

    def start_polling(self):
        """Start background vehicle polling thread."""
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log("info", f"VehicleMonitor: polling every {self.cfg.vehicle_poll_interval_minutes}min")

    def _poll_loop(self):
        """Background loop: poll each vehicle on its schedule or when refresh requested."""
        while True:
            try:
                now = time.time()
                names = self._manager.get_pollable_names()

                with self._lock:
                    refresh_now = set(self._refresh_requested)
                    self._refresh_requested.clear()

                for name in names:
                    last = self._last_poll.get(name, 0)
                    if name in refresh_now or (now - last) >= self._poll_interval_sec:
                        log("debug", f"VehicleMonitor: polling {name}")
                        result = self._manager.poll_vehicle(name)
                        self._last_poll[name] = time.time()
                        if result:
                            # Apply manual SoC override if present
                            manual = self.manual_store.get(name)
                            if manual is not None:
                                result.manual_soc = manual
                            log("debug", f"VehicleMonitor: {name} SoC={result.get_effective_soc():.1f}%")

                # Apply manual SoC overrides to all vehicles
                for name, v in self._manager.get_all_vehicles().items():
                    manual = self.manual_store.get(name)
                    v.manual_soc = manual

            except Exception as e:
                log("error", f"VehicleMonitor poll loop error: {e}")

            time.sleep(30)  # Check every 30s whether any poll is due

    def update_from_evcc(self, evcc_state: dict):
        """Pass evcc state to vehicle manager (called by DataCollector)."""
        try:
            self._manager.update_from_evcc(evcc_state)
            # Re-apply manual SoC overrides
            for name, v in self._manager.get_all_vehicles().items():
                manual = self.manual_store.get(name)
                v.manual_soc = manual
        except Exception as e:
            log("error", f"VehicleMonitor update_from_evcc error: {e}")

    def get_all_vehicles(self) -> Dict[str, VehicleData]:
        """Return all configured vehicles with current data."""
        return self._manager.get_all_vehicles()

    def predict_charge_need(self) -> Dict[str, float]:
        """Estimate kWh needed to reach target SoC for each vehicle."""
        target = self.cfg.ev_target_soc
        result = {}
        for name, v in self._manager.get_all_vehicles().items():
            soc = v.get_effective_soc()
            cap = v.capacity_kwh or self.cfg.ev_default_energy_kwh
            need = max(0, (target - soc) / 100 * cap)
            result[name] = round(need, 1)
        return result

    def trigger_refresh(self, vehicle_name: Optional[str] = None):
        """Request immediate re-poll for a vehicle (or all if None)."""
        with self._lock:
            if vehicle_name:
                self._refresh_requested.add(vehicle_name)
                log("info", f"VehicleMonitor: refresh requested for {vehicle_name}")
            else:
                for name in self._manager.get_pollable_names():
                    self._refresh_requested.add(name)


class DataCollector:
    """Collects system state from evcc and vehicles, runs background thread."""

    def __init__(self, evcc, influx, cfg: Config, vehicle_monitor: VehicleMonitor):
        self.evcc = evcc
        self.influx = influx
        self.cfg = cfg
        self.vehicle_monitor = vehicle_monitor
        self._state: Optional[SystemState] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start_background_collection(self):
        """Start background data collection thread."""
        self._thread = threading.Thread(target=self._collect_loop, daemon=True)
        self._thread.start()
        log("info", f"DataCollector: collecting every {self.cfg.data_collect_interval_sec}s")

    def _collect_loop(self):
        """Background loop: collect state at regular intervals."""
        while True:
            try:
                self._collect_once()
            except Exception as e:
                log("error", f"DataCollector loop error: {e}")
            time.sleep(self.cfg.data_collect_interval_sec)

    def _collect_once(self):
        """Single collection cycle."""
        # Fetch evcc state
        evcc_state = self.evcc.get_state()
        if not evcc_state:
            return

        # Update vehicle monitor with evcc state
        self.vehicle_monitor.update_from_evcc(evcc_state)

        # Build SystemState
        site = evcc_state.get("result", evcc_state)

        # Battery
        bat_soc = site.get("batterySoc", 0) or 0
        bat_power = site.get("batteryPower", 0) or 0

        # Grid / PV / Home
        grid_power = site.get("gridPower", 0) or 0
        pv_power = site.get("pvPower", 0) or 0
        home_power = site.get("homePower", 0) or 0

        # Tariff (current price)
        tariff = self.evcc.get_current_tariff()
        current_price = tariff if tariff else 0.0

        # EV (connected vehicle at loadpoint)
        ev_name = None
        ev_soc = 0.0
        ev_cap = 0.0
        ev_connected = False

        loadpoints = site.get("loadpoints", [])
        for lp in loadpoints:
            if lp.get("connected"):
                ev_name = lp.get("vehicleName") or lp.get("vehicle")
                ev_soc = float(lp.get("vehicleSoc", 0) or 0)
                ev_connected = True
                # Try to get capacity from our vehicle data
                vehicles = self.vehicle_monitor.get_all_vehicles()
                for vname, vdata in vehicles.items():
                    if vname.lower() == (ev_name or "").lower():
                        ev_cap = vdata.capacity_kwh or 0
                        # Use best available SoC
                        ev_soc = vdata.get_effective_soc()
                        break
                break

        state = SystemState(
            timestamp=datetime.now(timezone.utc),
            battery_soc=float(bat_soc),
            battery_power=float(bat_power),
            pv_power=float(pv_power),
            home_power=float(home_power),
            grid_power=float(grid_power),
            current_price=float(current_price),
            ev_connected=ev_connected,
            ev_name=ev_name,
            ev_soc=float(ev_soc),
            ev_capacity_kwh=float(ev_cap),
        )

        with self._lock:
            self._state = state

        # Write to InfluxDB
        if self.influx:
            try:
                self.influx.write_state(state)
            except Exception as e:
                log("warning", f"InfluxDB write error: {e}")

    def get_current_state(self) -> Optional[SystemState]:
        """Return the most recently collected system state."""
        with self._lock:
            return self._state
