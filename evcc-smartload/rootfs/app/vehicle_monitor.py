"""
Vehicle monitoring and data collection.

VehicleMonitor: polls vehicle APIs and evcc for SoC data, manages manual overrides.
DataCollector: reads evcc state and writes to InfluxDB.
"""

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from config import Config
from evcc_client import EvccClient
from influxdb_client import InfluxDBClient
from logging_util import log
from state import ManualSocStore, SystemState, VehicleStatus

# Conditional import for the modular vehicle provider system
try:
    from vehicles import VehicleManager
    HAS_VEHICLE_MODULE = True
except ImportError:
    HAS_VEHICLE_MODULE = False
    VehicleManager = None  # type: ignore


# =============================================================================
# Known vehicle capacities (fallback database)
# =============================================================================

KNOWN_CAPACITIES = {
    "kiaev9": 99.8, "kia_ev9": 99.8, "ev9": 99.8,
    "twingo": 22.0, "renaulttwingo": 22.0,
    "ora03": 63.0, "ora": 63.0, "gwmora": 63.0,
    "teslamodel3": 60.0, "model3": 60.0,
    "teslamodely": 75.0, "modely": 75.0,
    "id3": 58.0, "id4": 77.0,
    "ioniq5": 77.4, "ioniq6": 77.4,
    "ev6": 77.4, "niro": 64.8,
}


def _guess_capacity(name: str, default: float) -> float:
    n = name.lower().replace(" ", "").replace("_", "").replace("-", "")
    for key, cap in KNOWN_CAPACITIES.items():
        if key in n:
            return cap
    return default


# =============================================================================
# Vehicle Monitor
# =============================================================================

class VehicleMonitor:
    """
    Monitors all configured vehicles.

    Data sources (in priority order):
      1. Direct vehicle API (KIA Connect, Renault API) via VehicleManager
      2. Manual SoC input via ManualSocStore
      3. evcc API (only when vehicle is physically connected to loadpoint)
    """

    def __init__(self, evcc: EvccClient, cfg: Config, manual_store: ManualSocStore):
        self.evcc = evcc
        self.cfg = cfg
        self.vehicles: Dict[str, VehicleStatus] = {}
        self.manual_store = manual_store
        self.poll_interval_minutes = cfg.vehicle_poll_interval_minutes
        self._running = False
        self._vehicle_manager: Optional[VehicleManager] = None
        self._init_vehicle_manager()

    def _init_vehicle_manager(self):
        if not HAS_VEHICLE_MODULE or not self.cfg.vehicle_providers:
            return
        try:
            parsed = urlparse(self.cfg.evcc_url)
            evcc_host = parsed.hostname or "192.168.1.66"
            evcc_port = parsed.port or 7070
            vm_cfg = {
                "poll_interval_minutes": self.poll_interval_minutes,
                "providers": self.cfg.vehicle_providers,
            }
            self._vehicle_manager = VehicleManager(vm_cfg, evcc_host, evcc_port)
            log("info", f"VehicleManager initialised with {len(self.cfg.vehicle_providers)} providers")
        except Exception as e:
            log("error", f"Failed to init VehicleManager: {e}")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def start_polling(self):
        self._running = True
        if self._vehicle_manager:
            self._vehicle_manager.start_polling()

        def loop():
            time.sleep(2)
            self._poll_vehicles()
            while self._running:
                try:
                    self._poll_vehicles()
                except Exception as e:
                    log("error", f"Vehicle polling error: {e}")
                time.sleep(60)

        threading.Thread(target=loop, daemon=True).start()
        log("info", f"Vehicle monitor started (every {self.poll_interval_minutes}min)")

    def _poll_vehicles(self):
        now = datetime.now(timezone.utc)

        # 1. Data from modular VehicleManager
        if self._vehicle_manager:
            try:
                for name, vs in self._vehicle_manager.get_all_vehicles().items():
                    if vs.has_valid_soc:
                        old = self.vehicles.get(name)
                        self.vehicles[name] = VehicleStatus(
                            name=name,
                            soc=vs.soc or 0,
                            capacity_kwh=vs.capacity_kwh,
                            range_km=vs.data.range_km if vs.data else 0,
                            last_update=vs.data.timestamp if vs.data else now,
                            connected_to_wallbox=vs.evcc_connected,
                            charging=vs.data.is_charging if vs.data else False,
                            data_source=vs.data_source,
                            provider_type=vs.provider_type,
                        )
                        if old and abs(old.soc - vs.soc) > 2:
                            log("info", f"🔋 {name}: SoC {old.soc}% → {vs.soc}% (via {vs.data_source})")
            except Exception as e:
                log("error", f"VehicleManager poll error: {e}")

        # 2. Merge evcc data for connected vehicles
        evcc_state = self.evcc.get_state()
        if evcc_state:
            self._merge_evcc_data(evcc_state, now)

        # 3. Apply manual SoC overrides
        self._apply_manual_overrides()

        log("debug", f"Polled {len(self.vehicles)} vehicles: " +
            ", ".join(f"{v.name}:{v.get_effective_soc():.0f}%({v.data_source})" for v in self.vehicles.values()))

    def _merge_evcc_data(self, evcc_state: Dict, now: datetime):
        """Merge data from evcc /api/state into our vehicle store."""
        connected = {}
        for lp in evcc_state.get("loadpoints", []):
            if lp.get("connected") and lp.get("vehicleName"):
                connected[lp["vehicleName"]] = {
                    "soc": lp.get("vehicleSoc", 0),
                    "charging": lp.get("charging", False),
                }

        for name, data in evcc_state.get("vehicles", {}).items():
            existing = self.vehicles.get(name)
            # Don't overwrite direct_api data
            if existing and existing.data_source == "direct_api" and existing.soc > 0:
                if name in connected:
                    existing.connected_to_wallbox = True
                    existing.charging = connected[name].get("charging", False)
                continue

            soc = data.get("soc", 0)
            if soc == 0 and name in connected:
                soc = connected[name].get("soc", 0)

            capacity = data.get("capacity", 0) or _guess_capacity(name, self.cfg.ev_default_energy_kwh)

            self.vehicles[name] = VehicleStatus(
                name=name,
                soc=soc,
                capacity_kwh=capacity,
                range_km=data.get("range", 0),
                last_update=now,
                connected_to_wallbox=name in connected,
                charging=connected.get(name, {}).get("charging", False),
                data_source="evcc",
                provider_type="evcc",
            )

    def _apply_manual_overrides(self):
        """Apply manually entered SoC values from the ManualSocStore."""
        for name, entry in self.manual_store.get_all().items():
            soc = entry.get("soc")
            ts_str = entry.get("timestamp")
            if soc is None:
                continue
            ts = datetime.fromisoformat(ts_str) if ts_str else datetime.now(timezone.utc)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            if name in self.vehicles:
                v = self.vehicles[name]
                v.manual_soc = soc
                v.manual_soc_timestamp = ts
            else:
                # Vehicle not yet known from any source – create entry
                cap = _guess_capacity(name, self.cfg.ev_default_energy_kwh)
                self.vehicles[name] = VehicleStatus(
                    name=name,
                    soc=0,
                    capacity_kwh=cap,
                    range_km=0,
                    last_update=ts,
                    data_source="manual",
                    provider_type="manual",
                    manual_soc=soc,
                    manual_soc_timestamp=ts,
                )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def trigger_refresh(self, vehicle_name: str = None):
        if self._vehicle_manager:
            self._vehicle_manager.trigger_immediate_refresh(vehicle_name)
        self._poll_vehicles()

    def get_vehicle(self, name: str) -> Optional[VehicleStatus]:
        return self.vehicles.get(name)

    def get_all_vehicles(self) -> Dict[str, VehicleStatus]:
        return self.vehicles.copy()

    def get_total_charge_needed(self, target_soc: int = 80) -> float:
        return sum(
            max(0, (target_soc - v.get_effective_soc()) / 100 * v.capacity_kwh)
            for v in self.vehicles.values()
        )

    def predict_charge_need(self) -> Dict[str, float]:
        target = self.cfg.ev_target_soc
        return {
            name: round(max(0, (target - v.get_effective_soc()) / 100 * v.capacity_kwh), 1)
            for name, v in self.vehicles.items()
        }


# =============================================================================
# Data Collector (reads evcc state → SystemState + InfluxDB)
# =============================================================================

class DataCollector:
    """Reads evcc state and converts it to SystemState; writes to InfluxDB."""

    def __init__(self, evcc: EvccClient, influx: InfluxDBClient, cfg: Config,
                 vehicle_monitor: VehicleMonitor):
        self.evcc = evcc
        self.influx = influx
        self.cfg = cfg
        self.vehicle_monitor = vehicle_monitor
        self._running = False

    def get_current_state(self) -> Optional[SystemState]:
        """Build SystemState from evcc + vehicle monitor data."""
        data = self.evcc.get_state()
        if not data:
            return None

        now = datetime.now(timezone.utc)

        battery_soc = data.get("batterySoc", 0) or 0
        battery_power = data.get("batteryPower", 0) or 0
        grid_power = data.get("gridPower", 0) or 0
        pv_power = data.get("pvPower", 0) or 0
        home_power = data.get("homePower", 0) or 0

        # EV from loadpoints
        ev_connected = False
        ev_soc = 0.0
        ev_power = 0.0
        ev_name = ""
        ev_capacity = 0.0
        ev_charge_power = 11.0

        for lp in data.get("loadpoints", []):
            if lp.get("connected"):
                ev_connected = True
                ev_soc = lp.get("vehicleSoc", 0) or 0
                ev_power = lp.get("chargePower", 0) or 0
                ev_name = lp.get("vehicleName", "")
                ev_capacity = _guess_capacity(ev_name, self.cfg.ev_default_energy_kwh)
                ev_charge_power = lp.get("maxCurrent", 16) * 230 * 3 / 1000  # rough

                # Override SoC with vehicle monitor data if better
                vm_vehicle = self.vehicle_monitor.get_vehicle(ev_name)
                if vm_vehicle:
                    eff_soc = vm_vehicle.get_effective_soc()
                    if eff_soc > 0:
                        ev_soc = eff_soc
                    ev_capacity = vm_vehicle.capacity_kwh or ev_capacity
                break

        # Price
        tariffs = data.get("tariffGrid", []) or []
        current_price = 0.30
        price_forecast: List[float] = []
        if tariffs:
            try:
                current_price = float(tariffs[0].get("value", 0.30))
                price_forecast = [float(t.get("value", 0)) for t in tariffs[1:7]]
            except Exception:
                pass

        return SystemState(
            timestamp=now,
            battery_soc=battery_soc,
            battery_power=battery_power,
            grid_power=grid_power,
            current_price=current_price,
            pv_power=pv_power,
            home_power=home_power,
            ev_connected=ev_connected,
            ev_soc=ev_soc,
            ev_power=ev_power,
            ev_name=ev_name,
            ev_capacity_kwh=ev_capacity,
            ev_charge_power_kw=ev_charge_power,
            price_forecast=price_forecast,
        )

    def start_background_collection(self):
        self._running = True

        def loop():
            while self._running:
                try:
                    state = self.get_current_state()
                    if state:
                        self._write(state)
                except Exception as e:
                    log("error", f"Collection error: {e}")
                time.sleep(self.cfg.data_collect_interval_sec)

        threading.Thread(target=loop, daemon=True).start()
        log("info", "Background data collection started")

    def _write(self, s: SystemState):
        ns = int(s.timestamp.timestamp() * 1e9)
        self.influx.write_batch([
            f"energy,source=smartprice "
            f"battery_soc={s.battery_soc},"
            f"battery_power={s.battery_power},"
            f"grid_power={s.grid_power},"
            f"pv_power={s.pv_power},"
            f"home_power={s.home_power},"
            f"ev_connected={int(s.ev_connected)},"
            f"ev_soc={s.ev_soc},"
            f"ev_power={s.ev_power},"
            f"price={s.current_price} "
            f"{ns}"
        ])
