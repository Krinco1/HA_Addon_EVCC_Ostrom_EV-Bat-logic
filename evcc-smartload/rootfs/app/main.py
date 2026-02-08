"""
EVCC-Smartload v2.0 - Hybrid Optimization with Shadow Reinforcement Learning

Architecture:
┌─────────────────────────────────────────────────────────────────┐
│  PRODUCTION (LP)              SHADOW (RL)                       │
│  ══════════════              ════════════                       │
│  • Linear Programming        • DQN Agent                        │
│  • Steuert evcc              • Beobachtet nur                   │
│  • Sofort optimal            • Lernt kontinuierlich             │
│  • Erklärbar                 • Simuliert Entscheidungen         │
│                              • Vergleicht mit LP                │
│                              • "RL READY" wenn besser           │
└─────────────────────────────────────────────────────────────────┘

Beschleunigungstechniken:
1. Imitation Learning - RL lernt initial von LP-Entscheidungen
2. Reward Shaping - Zusätzliche Signale für schnelleres Lernen
3. Prioritized Experience Replay - Wichtige Erfahrungen öfter nutzen
4. Event Detection - Fokus auf interessante Situationen
"""

import json
import os
import time
import random
import threading
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import requests

# Vehicle module (modular vehicle API providers)
try:
    from vehicles import VehicleManager
    HAS_VEHICLE_MODULE = True
except ImportError:
    HAS_VEHICLE_MODULE = False
    VehicleManager = None

# =============================================================================
# CONFIGURATION
# =============================================================================

OPTIONS_PATH = "/data/options.json"
STATE_PATH = "/data/smartprice_state.json"
RL_MODEL_PATH = "/data/smartprice_rl_model.json"
RL_MEMORY_PATH = "/data/smartprice_rl_memory.json"
COMPARISON_LOG_PATH = "/data/smartprice_comparison.json"


def _log(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level.upper():5}] {msg}", flush=True)


@dataclass
class Config:
    # evcc
    evcc_url: str = "http://192.168.1.66:7070"
    evcc_password: str = ""
    
    # InfluxDB
    influxdb_host: str = "192.168.1.67"
    influxdb_port: int = 8086
    influxdb_database: str = "smartprice"
    influxdb_username: str = "smartprice"
    influxdb_password: str = "smartprice"
    
    # Battery
    battery_capacity_kwh: float = 33.1
    battery_charge_power_kw: float = 4.3
    battery_max_price_ct: float = 25.0
    battery_min_soc: int = 10
    battery_max_soc: int = 90
    battery_price_corridor_ct: float = 0.8  # Basis-Korridor zum Bestpreis
    
    # EV
    ev_max_price_ct: float = 30.0
    ev_target_soc: int = 80
    ev_default_energy_kwh: float = 30.0
    ev_price_corridor_ct: float = 1.0  # Basis-Korridor für EV
    ev_charge_deadline_hour: int = 6  # Bis wann soll EV voll sein (Uhrzeit)
    
    # Feed-in
    feed_in_tariff_ct: float = 7.0
    
    # Scheduling
    decision_interval_minutes: int = 15  # Entscheidung alle 15 Min
    data_collect_interval_sec: int = 60
    
    # RL Configuration
    rl_enabled: bool = True
    rl_learning_rate: float = 0.001
    rl_discount_factor: float = 0.95
    rl_epsilon_start: float = 0.3  # Exploration (niedrig wg. Imitation Learning)
    rl_epsilon_min: float = 0.05
    rl_epsilon_decay: float = 0.995
    rl_batch_size: int = 32
    rl_memory_size: int = 10000
    rl_ready_threshold: float = 0.8  # RL muss in 80% der Fälle besser/gleich sein
    rl_ready_min_comparisons: int = 200  # Mindestens 200 Vergleiche
    
    # RL Pro-Device Control (v2.6.8)
    rl_auto_switch: bool = True  # Automatisch zu RL wechseln wenn ready
    rl_fallback_threshold: float = 0.7  # Zurück zu LP wenn < 70%
    
    # Vehicle Providers (modulares System)
    vehicle_poll_interval_minutes: int = 30  # Wie oft Fahrzeug-APIs pollen
    vehicle_providers: List[Dict] = field(default_factory=list)  # Provider-Konfigurationen
    
    # API
    api_port: int = 8099


def load_config() -> Config:
    try:
        with open(OPTIONS_PATH, "r") as f:
            raw = json.load(f)
        _log("debug", f"Loaded options: {list(raw.keys())}")
        cfg = Config()
        for k, v in raw.items():
            if hasattr(cfg, k):
                old_val = getattr(cfg, k)
                setattr(cfg, k, v)
                if 'price' in k or 'corridor' in k:
                    _log("debug", f"Config {k}: {old_val} -> {v}")
        
        # Parse vehicle_providers if it's a string (JSON)
        if isinstance(cfg.vehicle_providers, str):
            try:
                cfg.vehicle_providers = json.loads(cfg.vehicle_providers)
            except:
                cfg.vehicle_providers = []
        
        return cfg
    except Exception as e:
        _log("warning", f"Could not load config: {e}, using defaults")
        return Config()


def load_version() -> str:
    """Lädt Version dynamisch aus config.yaml"""
    try:
        import yaml
        config_path = Path("/etc/smartprice/config.yaml")
        if not config_path.exists():
            # Fallback für Development
            config_path = Path(__file__).parent.parent.parent / "config.yaml"
        
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)
            return cfg.get('version', '2.6.8')
    except Exception as e:
        _log("warning", f"Could not load version from config.yaml: {e}")
        return "2.6.8"  # Fallback


# Global version
VERSION = load_version()


# =============================================================================
# INFLUXDB CLIENT
# =============================================================================

class InfluxDBClient:
    def __init__(self, cfg: Config):
        self.base_url = f"http://{cfg.influxdb_host}:{cfg.influxdb_port}"
        self.db = cfg.influxdb_database
        self.auth = (cfg.influxdb_username, cfg.influxdb_password)
    
    def write_batch(self, lines: List[str]) -> bool:
        try:
            r = requests.post(
                f"{self.base_url}/write",
                params={"db": self.db, "precision": "ns"},
                auth=self.auth,
                data="\n".join(lines),
                timeout=10
            )
            return r.status_code == 204
        except Exception as e:
            _log("error", f"InfluxDB write failed: {e}")
            return False
    
    def query(self, q: str) -> List[Dict]:
        """Führt Query aus und gibt Liste von Datenpunkten zurück."""
        try:
            r = requests.get(
                f"{self.base_url}/query",
                params={"db": self.db, "q": q},
                auth=self.auth,
                timeout=30
            )
            if r.status_code != 200:
                return []
            
            data = r.json()
            results = []
            
            # Parse InfluxDB Response Format
            if "results" in data:
                for result in data["results"]:
                    if "series" in result:
                        for series in result["series"]:
                            columns = series.get("columns", [])
                            values = series.get("values", [])
                            
                            for row in values:
                                point = {}
                                for i, col in enumerate(columns):
                                    if i < len(row):
                                        point[col] = row[i]
                                results.append(point)
            
            return results
            
        except Exception as e:
            _log("error", f"InfluxDB query failed: {e}")
            return []
    
    def get_history_hours(self, hours: int = 168) -> List[Dict]:
        """Holt historische Daten der letzten X Stunden."""
        query = f'''
            SELECT mean(battery_soc) as battery_soc, 
                   mean(price) as price,
                   mean(pv_power) as pv_power,
                   mean(home_power) as home_power,
                   mean(ev_soc) as ev_soc,
                   max(ev_connected) as ev_connected
            FROM energy 
            WHERE time > now() - {hours}h 
            GROUP BY time(1h)
            ORDER BY time ASC
        '''
        return self.query(query)


# =============================================================================
# EVCC CLIENT
# =============================================================================

class EvccClient:
    def __init__(self, cfg: Config):
        self.base_url = cfg.evcc_url.rstrip("/")
        self.password = cfg.evcc_password
        self.sess = requests.Session()
        self._logged_in = False
    
    def _login(self) -> None:
        if self._logged_in or not self.password:
            return
        try:
            r = self.sess.post(f"{self.base_url}/api/auth/login",
                             json={"password": self.password}, timeout=10)
            self._logged_in = r.status_code == 200
        except:
            pass
    
    def get_state(self) -> Optional[Dict]:
        self._login()
        try:
            r = self.sess.get(f"{self.base_url}/api/state", timeout=15)
            data = r.json()
            return data.get("result", data)
        except:
            return None
    
    def get_tariff_grid(self) -> List[Dict]:
        """Holt Grid-Tarife von evcc."""
        self._login()
        try:
            url = f"{self.base_url}/api/tariff/grid"
            _log("debug", f"Fetching tariffs: GET {url}")
            r = self.sess.get(url, timeout=15)
            _log("debug", f"Tariff response status: {r.status_code}")
            
            if r.status_code != 200:
                _log("warning", f"Tariff API returned {r.status_code}")
                return []
            
            data = r.json()
            _log("debug", f"Tariff response keys: {data.keys() if isinstance(data, dict) else type(data)}")
            
            # evcc kann verschiedene Formate zurückgeben
            if isinstance(data, dict):
                if "result" in data:
                    result = data["result"]
                    if isinstance(result, dict) and "rates" in result:
                        rates = result["rates"]
                    elif isinstance(result, list):
                        rates = result
                    else:
                        rates = []
                elif "rates" in data:
                    rates = data["rates"]
                else:
                    rates = []
            elif isinstance(data, list):
                rates = data
            else:
                rates = []
            
            _log("debug", f"Found {len(rates)} tariff rates")
            if rates:
                _log("debug", f"First rate: {rates[0]}")
            
            return rates
        except Exception as e:
            _log("error", f"Failed to get tariffs: {e}")
            return []
    
    def set_battery_grid_charge_limit(self, eur_per_kwh: float) -> bool:
        """Setzt das Batterie-Netzlade-Limit in EUR/kWh."""
        self._login()
        try:
            # evcc erwartet den Wert als Pfad-Parameter
            url = f"{self.base_url}/api/batterygridchargelimit/{eur_per_kwh:.4f}"
            _log("debug", f"Setting battery limit: POST {url}")
            r = self.sess.post(url, timeout=10)
            _log("debug", f"Response: {r.status_code} - {r.text[:200] if r.text else 'empty'}")
            if r.status_code == 200:
                _log("info", f"✓ Battery grid charge limit set to {eur_per_kwh*100:.1f} ct/kWh")
                return True
            else:
                _log("warning", f"✗ Failed to set battery limit: {r.status_code}")
                return False
        except Exception as e:
            _log("error", f"✗ Exception setting battery limit: {e}")
            return False
    
    def clear_battery_grid_charge_limit(self) -> bool:
        """Löscht das Batterie-Netzlade-Limit."""
        self._login()
        try:
            url = f"{self.base_url}/api/batterygridchargelimit"
            _log("debug", f"Clearing battery limit: DELETE {url}")
            r = self.sess.delete(url, timeout=10)
            _log("debug", f"Response: {r.status_code}")
            return r.status_code in [200, 204]
        except Exception as e:
            _log("error", f"✗ Exception clearing battery limit: {e}")
            return False
    
    def set_smart_cost_limit(self, eur_per_kwh: float) -> bool:
        """Setzt das Smart Cost Limit für EV in EUR/kWh."""
        self._login()
        try:
            url = f"{self.base_url}/api/smartcostlimit/{eur_per_kwh:.4f}"
            _log("debug", f"Setting EV limit: POST {url}")
            r = self.sess.post(url, timeout=10)
            _log("debug", f"Response: {r.status_code}")
            if r.status_code == 200:
                _log("info", f"✓ EV smart cost limit set to {eur_per_kwh*100:.1f} ct/kWh")
                return True
            else:
                _log("warning", f"✗ Failed to set EV limit: {r.status_code}")
                return False
        except Exception as e:
            _log("error", f"✗ Exception setting EV limit: {e}")
            return False


# =============================================================================
# STATE REPRESENTATION
# =============================================================================

@dataclass
class SystemState:
    """Zustand des Systems für Entscheidungen."""
    timestamp: datetime
    
    # Battery
    battery_soc: float  # 0-100
    battery_power: float  # W, + = charging
    
    # Grid
    grid_power: float  # W, + = import
    current_price: float  # EUR/kWh
    
    # PV
    pv_power: float  # W
    
    # House
    home_power: float  # W (real, ohne Batterie/Wallbox)
    
    # EV (erweitert!)
    ev_connected: bool
    ev_soc: float  # 0-100
    ev_power: float  # W
    ev_name: str = ""  # Fahrzeugname aus evcc
    ev_capacity_kwh: float = 0  # Kapazität aus evcc
    ev_charge_power_kw: float = 11  # Max Ladeleistung
    
    # Forecast (nächste 6 Stunden)
    price_forecast: List[float] = field(default_factory=list)  # EUR/kWh
    pv_forecast: List[float] = field(default_factory=list)  # W
    
    def to_vector(self) -> np.ndarray:
        """Konvertiert State zu RL-Input-Vektor."""
        hour = self.timestamp.hour
        weekday = self.timestamp.weekday()
        
        # Normalisierte Features
        features = [
            self.battery_soc / 100,
            np.clip(self.battery_power / 5000, -1, 1),
            np.clip(self.grid_power / 10000, -1, 1),
            self.current_price / 0.5,  # Normiert auf ~50ct max
            np.clip(self.pv_power / 10000, 0, 1),
            np.clip(self.home_power / 5000, 0, 1),
            float(self.ev_connected),
            self.ev_soc / 100 if self.ev_connected else 0,
            np.clip(self.ev_power / 11000, 0, 1),
            np.sin(2 * np.pi * hour / 24),  # Zyklische Stunde
            np.cos(2 * np.pi * hour / 24),
            np.sin(2 * np.pi * weekday / 7),  # Zyklischer Wochentag
            np.cos(2 * np.pi * weekday / 7),
        ]
        
        # Preis-Forecast (nächste 6h, gepadded)
        prices = self.price_forecast[:6] + [0] * (6 - len(self.price_forecast[:6]))
        features.extend([p / 0.5 for p in prices])
        
        # PV-Forecast (nächste 6h, gepadded)
        pv = self.pv_forecast[:6] + [0] * (6 - len(self.pv_forecast[:6]))
        features.extend([p / 10000 for p in pv])
        
        return np.array(features, dtype=np.float32)


@dataclass
class Action:
    """Mögliche Aktionen."""
    battery_action: int  # 0=hold, 1=charge_grid, 2=charge_pv_only, 3=discharge
    ev_action: int  # 0=no_charge, 1=charge_cheap, 2=charge_now, 3=charge_pv_only
    
    # Berechnete Limits
    battery_limit_eur: Optional[float] = None
    ev_limit_eur: Optional[float] = None


# =============================================================================
# EVENT DETECTOR
# =============================================================================

class EventDetector:
    """Erkennt wichtige Events für beschleunigtes Lernen."""
    
    def __init__(self):
        self.last_state: Optional[SystemState] = None
        self.ev_history: deque = deque(maxlen=100)
        self.price_history: deque = deque(maxlen=100)
    
    def detect(self, state: SystemState) -> List[str]:
        """Erkennt Events basierend auf Zustandsänderungen."""
        events = []
        
        if self.last_state:
            # EV Events
            if not self.last_state.ev_connected and state.ev_connected:
                events.append("EV_CONNECTED")
            if self.last_state.ev_connected and not state.ev_connected:
                if state.ev_soc > self.last_state.ev_soc + 5:
                    events.append("EV_CHARGED_EXTERNALLY")
                else:
                    events.append("EV_DISCONNECTED")
            
            # Preis Events
            if state.current_price < self.last_state.current_price * 0.8:
                events.append("PRICE_DROP")
            if state.current_price > self.last_state.current_price * 1.2:
                events.append("PRICE_SPIKE")
            
            # Battery Events
            if state.battery_soc < 15 and self.last_state.battery_soc >= 15:
                events.append("BATTERY_LOW")
            if state.battery_soc > 85 and self.last_state.battery_soc <= 85:
                events.append("BATTERY_FULL")
            
            # PV Events
            if state.pv_power > 1000 and self.last_state.pv_power < 500:
                events.append("PV_SURGE")
            if state.pv_power < 200 and self.last_state.pv_power > 1000:
                events.append("PV_DROP")
            
            # Grid Events
            if state.grid_power < -1000:  # Einspeisung
                events.append("GRID_EXPORT")
        
        self.last_state = state
        return events


# =============================================================================
# HOLISTIC OPTIMIZER (Ganzheitliche Optimierung)
# =============================================================================

@dataclass
class ChargePlan:
    """Ladeplan für die nächsten Stunden."""
    battery_threshold_eur: Optional[float] = None
    ev_threshold_eur: Optional[float] = None
    battery_hours: List[datetime] = field(default_factory=list)
    ev_hours: List[datetime] = field(default_factory=list)
    reason_battery: str = ""
    reason_ev: str = ""
    total_cost_estimate: float = 0.0


class HolisticOptimizer:
    """
    Ganzheitlicher Optimizer der Batterie, EV, PV und Hauslast gemeinsam betrachtet.
    
    Prinzipien:
    1. Berechne Gesamtbedarf (Batterie + EV + Haus)
    2. Berechne verfügbare Quellen (PV + Netz)
    3. Priorisiere: PV nutzen > Günstige Netzstunden > Teure Stunden vermeiden
    4. EV hat Deadline (muss bis X Uhr voll sein)
    5. Batterie ist flexibler (kein hartes Deadline)
    6. Vermeide Netzüberlastung (max ~20kW)
    """
    
    def __init__(self, cfg: Config):
        self.cfg = cfg
    
    def optimize(self, state: SystemState, tariffs: List[Dict]) -> Action:
        """Ganzheitliche Optimierung für Batterie und EV."""
        
        action = Action(battery_action=0, ev_action=0)
        now = state.timestamp
        
        # Parse Tarife
        hourly = self._tariffs_to_hourly(tariffs, now)
        if not hourly:
            _log("warning", "No hourly prices available - cannot optimize!")
            return action
        
        _log("debug", f"Optimize: battery_soc={state.battery_soc}%, ev_connected={state.ev_connected}, ev_soc={state.ev_soc}%")
        
        # =====================================================================
        # 1. BEDARFSANALYSE
        # =====================================================================
        
        # Batterie-Bedarf
        battery_current_soc = state.battery_soc
        battery_target_soc = self.cfg.battery_max_soc
        battery_need_kwh = max(0, (battery_target_soc - battery_current_soc) / 100 * self.cfg.battery_capacity_kwh)
        battery_charge_power = self.cfg.battery_charge_power_kw
        battery_hours_needed = int(battery_need_kwh / battery_charge_power) + 1 if battery_need_kwh > 0.5 else 0
        
        # EV-Bedarf (aus evcc State - FAHRZEUGSPEZIFISCH!)
        ev_need_kwh = 0
        ev_hours_needed = 0
        ev_current_soc = 0
        ev_capacity = state.ev_capacity_kwh if state.ev_capacity_kwh > 0 else self.cfg.ev_default_energy_kwh
        ev_charge_power = state.ev_charge_power_kw if state.ev_charge_power_kw > 0 else 11
        ev_name = state.ev_name
        
        if state.ev_connected:
            ev_current_soc = state.ev_soc
            ev_target_soc = self.cfg.ev_target_soc
            
            # Berechne Bedarf
            ev_need_kwh = max(0, (ev_target_soc - ev_current_soc) / 100 * ev_capacity)
            
            # Sicherheitspuffer: +20% mehr Stunden einplanen
            # (für Ladeverluste, ungenaue SoC-Anzeige, Varianz)
            ev_hours_raw = ev_need_kwh / ev_charge_power
            ev_hours_needed = int(ev_hours_raw * 1.2) + 1 if ev_need_kwh > 1 else 0
            
            _log("info", f"EV {ev_name}: {ev_current_soc}% → {ev_target_soc}%, "
                        f"capacity={ev_capacity}kWh, need={ev_need_kwh:.1f}kWh, "
                        f"hours={ev_hours_needed} (inkl. 20% Puffer)")
        
        # Hauslast (aus gelerntem Profil oder Fallback)
        house_hourly_kwh = state.home_power / 1000  # Aktuelle Last als Schätzung
        
        _log("debug", f"Demand: Battery={battery_need_kwh:.1f}kWh ({battery_hours_needed}h), "
                     f"EV={ev_need_kwh:.1f}kWh ({ev_hours_needed}h), House={house_hourly_kwh:.1f}kW")
        
        # =====================================================================
        # 2. ZEITFENSTER & CONSTRAINTS
        # =====================================================================
        
        # EV Deadline
        deadline_hour = self.cfg.ev_charge_deadline_hour
        if now.hour < deadline_hour:
            ev_deadline = now.replace(hour=deadline_hour, minute=0, second=0, microsecond=0)
        else:
            ev_deadline = (now + timedelta(days=1)).replace(hour=deadline_hour, minute=0, second=0, microsecond=0)
        
        hours_until_ev_deadline = (ev_deadline - now).total_seconds() / 3600
        
        # Batterie Deadline (flexibler - z.B. 24h)
        battery_deadline = now + timedelta(hours=24)
        
        # Preislimits
        max_battery_price = self.cfg.battery_max_price_ct / 100
        max_ev_price = self.cfg.ev_max_price_ct / 100
        feed_in_price = self.cfg.feed_in_tariff_ct / 100
        
        # Preisanalyse
        prices_24h = [p for _, p in hourly[:24]]
        if not prices_24h:
            prices_24h = [state.current_price]
        
        min_price = min(prices_24h)
        max_price = max(prices_24h)
        avg_price = sum(prices_24h) / len(prices_24h)
        current_price = state.current_price
        
        _log("debug", f"Prices: current={current_price*100:.1f}ct, min={min_price*100:.1f}ct, "
                     f"avg={avg_price*100:.1f}ct, max={max_price*100:.1f}ct")
        
        # =====================================================================
        # 3. PV-ANALYSE
        # =====================================================================
        
        pv_power = state.pv_power
        home_power = state.home_power
        pv_surplus = max(0, pv_power - home_power)
        
        has_significant_pv = pv_power > 500
        has_pv_surplus = pv_surplus > 500
        
        _log("debug", f"PV: {pv_power:.0f}W, Home: {home_power:.0f}W, Surplus: {pv_surplus:.0f}W")
        
        # =====================================================================
        # 4. GANZHEITLICHE OPTIMIERUNG
        # =====================================================================
        
        # Strategie basierend auf Situation:
        
        # FALL A: PV-Überschuss vorhanden → Nutze PV zuerst!
        if has_pv_surplus:
            if pv_surplus > 2000 and state.ev_connected and ev_need_kwh > 1:
                # Genug PV für EV
                action.ev_action = 3  # charge_pv_only
                action.ev_limit_eur = 0
                _log("info", f"EV: Charging from PV surplus ({pv_surplus:.0f}W)")
            
            if pv_surplus > 500 and battery_need_kwh > 0.5:
                # PV für Batterie
                action.battery_action = 2  # charge_pv_only
                action.battery_limit_eur = 0
                _log("info", f"Battery: Charging from PV surplus")
            
            # Wenn beide versorgt, fertig
            if action.ev_action != 0 or action.battery_action != 0:
                return action
        
        # FALL B: Nachtladen - Kein PV, aber günstiger Strom
        
        # Berechne gemeinsamen optimalen Ladeplan
        plan = self._create_holistic_plan(
            hourly=hourly,
            now=now,
            battery_need_kwh=battery_need_kwh,
            battery_hours_needed=battery_hours_needed,
            battery_power_kw=battery_charge_power,
            max_battery_price=max_battery_price,
            ev_need_kwh=ev_need_kwh,
            ev_hours_needed=ev_hours_needed,
            ev_power_kw=ev_charge_power,
            max_ev_price=max_ev_price,
            ev_deadline=ev_deadline,
            hours_until_ev_deadline=hours_until_ev_deadline,
            current_price=current_price,
            min_price=min_price
        )
        
        # Wende Plan an
        if plan.battery_threshold_eur is not None and battery_need_kwh > 0.5:
            action.battery_action = 1
            action.battery_limit_eur = plan.battery_threshold_eur
            _log("info", f"Battery: {plan.reason_battery}")
        
        if plan.ev_threshold_eur is not None and ev_need_kwh > 1 and state.ev_connected:
            action.ev_action = 1
            action.ev_limit_eur = plan.ev_threshold_eur
            _log("info", f"EV: {plan.reason_ev}")
        
        # =====================================================================
        # 5. NOTFALL-CHECKS
        # =====================================================================
        
        # EV Notfall: Deadline naht!
        if state.ev_connected and ev_need_kwh > 1:
            if hours_until_ev_deadline < ev_hours_needed * 1.2:
                # Kritisch! Muss jetzt laden, egal wie teuer
                action.ev_action = 2  # charge_now
                action.ev_limit_eur = max_ev_price
                _log("warning", f"EV URGENT: Only {hours_until_ev_deadline:.1f}h until deadline, "
                              f"need {ev_hours_needed}h! Charging at max {max_ev_price*100:.0f}ct")
        
        # Batterie Notfall: Sehr niedrig
        if battery_current_soc < 15 and battery_need_kwh > 0:
            if action.battery_action == 0:
                action.battery_action = 1
                action.battery_limit_eur = min(current_price + 0.02, max_battery_price)
                _log("warning", f"Battery LOW ({battery_current_soc}%)! Emergency charging")
        
        # =====================================================================
        # 6. ENTLADE-LOGIK (wenn Batterie voll und Preis hoch)
        # =====================================================================
        
        if battery_current_soc > 50 and battery_need_kwh < 1:
            # Batterie gut gefüllt, prüfe ob Entladen sinnvoll
            price_is_high = current_price > avg_price * 1.15
            price_above_feedin = current_price > feed_in_price * 1.3
            home_needs_power = home_power > pv_power
            
            if price_is_high and price_above_feedin and home_needs_power:
                action.battery_action = 3  # discharge
                _log("info", f"Battery: Discharging at {current_price*100:.1f}ct (above avg {avg_price*100:.1f}ct)")
        
        return action
    
    def _create_holistic_plan(
        self,
        hourly: List[Tuple[datetime, float]],
        now: datetime,
        battery_need_kwh: float,
        battery_hours_needed: int,
        battery_power_kw: float,
        max_battery_price: float,
        ev_need_kwh: float,
        ev_hours_needed: int,
        ev_power_kw: float,
        max_ev_price: float,
        ev_deadline: datetime,
        hours_until_ev_deadline: float,
        current_price: float,
        min_price: float
    ) -> ChargePlan:
        """
        Erstellt einen ganzheitlichen Ladeplan.
        
        Strategie:
        1. EV hat Priorität (harte Deadline)
        2. Finde günstigste Stunden für EV vor Deadline
        3. Finde günstigste verbleibende Stunden für Batterie
        4. Beachte: Paralleles Laden ist OK (max ~15kW zusammen)
        """
        
        plan = ChargePlan()
        
        # Sortiere Tarife nach Zeit
        sorted_hourly = sorted(hourly, key=lambda x: x[0])
        
        # =====================================================================
        # EV-PLANUNG (Priorität, weil Deadline)
        # =====================================================================
        
        if ev_hours_needed > 0:
            # Nur Stunden bis Deadline betrachten
            ev_eligible = [(h, p) for h, p in sorted_hourly 
                          if h.timestamp() < ev_deadline.timestamp() and p <= max_ev_price]
            
            if ev_eligible:
                # Sortiere nach Preis
                ev_by_price = sorted(ev_eligible, key=lambda x: x[1])
                
                # Nimm die N günstigsten Stunden
                ev_chosen = ev_by_price[:ev_hours_needed]
                
                if len(ev_chosen) >= ev_hours_needed:
                    # Genug günstige Stunden!
                    ev_max_chosen_price = max(p for _, p in ev_chosen)
                    plan.ev_threshold_eur = ev_max_chosen_price + 0.001  # Kleiner Puffer
                    plan.ev_hours = [h for h, _ in ev_chosen]
                    
                    avg_ev_price = sum(p for _, p in ev_chosen) / len(ev_chosen)
                    plan.reason_ev = (f"Lade {ev_need_kwh:.1f}kWh in {len(ev_chosen)} besten Stunden "
                                     f"vor {ev_deadline.strftime('%H:%M')} @ max {plan.ev_threshold_eur*100:.1f}ct "
                                     f"(avg {avg_ev_price*100:.1f}ct)")
                else:
                    # Nicht genug günstige Stunden, nehme alle verfügbaren
                    plan.ev_threshold_eur = max_ev_price
                    plan.ev_hours = [h for h, _ in ev_eligible]
                    plan.reason_ev = (f"Nur {len(ev_eligible)} Stunden unter {max_ev_price*100:.0f}ct "
                                     f"vor Deadline - lade alle!")
            else:
                # Keine Stunden unter Maximum - Notfall!
                plan.ev_threshold_eur = max_ev_price
                plan.reason_ev = f"Keine günstigen Stunden - lade zum Maximum {max_ev_price*100:.0f}ct"
        
        # =====================================================================
        # BATTERIE-PLANUNG (flexibler, kein hartes Deadline)
        # =====================================================================
        
        if battery_hours_needed > 0:
            # Batterie kann die nächsten 24h nutzen
            battery_eligible = [(h, p) for h, p in sorted_hourly[:24] if p <= max_battery_price]
            
            if battery_eligible:
                # Sortiere nach Preis
                battery_by_price = sorted(battery_eligible, key=lambda x: x[1])
                
                # Berücksichtige EV-Stunden (Parallelladen ist OK, aber priorisiere Trennung wenn möglich)
                ev_hour_set = set(h.hour for h in plan.ev_hours) if plan.ev_hours else set()
                
                # Bevorzuge Stunden wo EV nicht lädt (für bessere Lastverteilung)
                battery_preferred = [x for x in battery_by_price if x[0].hour not in ev_hour_set]
                battery_overlap = [x for x in battery_by_price if x[0].hour in ev_hour_set]
                
                # Kombiniere: erst nicht-überlappende, dann überlappende
                battery_sorted = battery_preferred + battery_overlap
                
                # Nimm die N günstigsten
                battery_chosen = battery_sorted[:battery_hours_needed]
                
                if len(battery_chosen) >= battery_hours_needed:
                    battery_max_chosen_price = max(p for _, p in battery_chosen)
                    plan.battery_threshold_eur = battery_max_chosen_price + 0.001
                    plan.battery_hours = [h for h, _ in battery_chosen]
                    
                    avg_battery_price = sum(p for _, p in battery_chosen) / len(battery_chosen)
                    overlap_count = len([h for h in plan.battery_hours if h.hour in ev_hour_set])
                    
                    plan.reason_battery = (f"Lade {battery_need_kwh:.1f}kWh in {len(battery_chosen)} "
                                          f"günstigsten Stunden @ max {plan.battery_threshold_eur*100:.1f}ct "
                                          f"(avg {avg_battery_price*100:.1f}ct, {overlap_count}h parallel mit EV)")
                else:
                    # Nicht genug, aber nimm was da ist
                    if battery_chosen:
                        plan.battery_threshold_eur = max(p for _, p in battery_chosen) + 0.001
                        plan.battery_hours = [h for h, _ in battery_chosen]
                        plan.reason_battery = f"Nur {len(battery_chosen)} Stunden verfügbar"
            else:
                # Keine Stunden unter Maximum
                _log("debug", f"Battery: No prices under {max_battery_price*100:.0f}ct")
        
        return plan
    
    def _tariffs_to_hourly(self, tariffs: List[Dict], now: datetime) -> List[Tuple[datetime, float]]:
        """Konvertiert evcc Tarife zu stündlichen Preisen."""
        if not tariffs:
            _log("warning", "No tariffs received from evcc!")
            return []
        
        _log("debug", f"Processing {len(tariffs)} tariff entries")
        
        buckets = defaultdict(list)
        now_hour = now.replace(minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        
        for t in tariffs:
            try:
                start_str = t.get("start", "")
                val = float(t.get("value", 0))
                
                # Parse datetime
                if start_str.endswith("Z"):
                    start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                elif "+" in start_str or start_str.count("-") > 2:
                    start = datetime.fromisoformat(start_str)
                else:
                    start = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
                
                hour = start.replace(minute=0, second=0, microsecond=0)
                
                # Vergleiche ohne Timezone-Probleme
                if hour.timestamp() >= now_hour.timestamp() - 3600:  # 1h Toleranz
                    buckets[hour].append(val)
            except Exception as e:
                _log("debug", f"Failed to parse tariff: {t} - {e}")
                continue
        
        result = [(h, sum(v)/len(v)) for h, v in sorted(buckets.items())]
        _log("debug", f"Parsed {len(result)} hourly prices, first 5: {[(str(h)[-14:-6], round(p*100,1)) for h,p in result[:5]]}")
        return result


# =============================================================================
# DQN AGENT (SHADOW RL)
# =============================================================================

class ReplayMemory:
    """Prioritized Experience Replay."""
    
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.memory: List[Tuple] = []
        self.priorities: List[float] = []
        self.position = 0
    
    def push(self, state, action, reward, next_state, done, priority: float = 1.0):
        if len(self.memory) < self.capacity:
            self.memory.append(None)
            self.priorities.append(None)
        
        self.memory[self.position] = (state, action, reward, next_state, done)
        self.priorities[self.position] = priority
        self.position = (self.position + 1) % self.capacity
    
    def sample(self, batch_size: int) -> List[Tuple]:
        if len(self.memory) < batch_size:
            return list(self.memory)
        
        # Prioritized sampling
        probs = np.array(self.priorities[:len(self.memory)], dtype=np.float32)
        probs = probs / probs.sum()
        indices = np.random.choice(len(self.memory), batch_size, p=probs, replace=False)
        return [self.memory[i] for i in indices]
    
    def __len__(self):
        return len(self.memory)
    
    def save(self, path: str):
        try:
            data = {
                "memory": [(s.tolist() if isinstance(s, np.ndarray) else s,
                           a, r, 
                           ns.tolist() if isinstance(ns, np.ndarray) else ns, 
                           d) for s, a, r, ns, d in self.memory if s is not None],
                "priorities": [p for p in self.priorities if p is not None],
                "position": self.position
            }
            with open(path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            _log("warning", f"Could not save replay memory: {e}")
    
    def load(self, path: str):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            self.memory = [(np.array(s), a, r, np.array(ns), d) 
                          for s, a, r, ns, d in data.get("memory", [])]
            self.priorities = data.get("priorities", [1.0] * len(self.memory))
            self.position = data.get("position", 0)
        except:
            pass


class DQNAgent:
    """Deep Q-Network Agent mit Imitation Learning."""
    
    # Action space: 4 battery actions x 4 EV actions = 16 total
    N_BATTERY_ACTIONS = 4
    N_EV_ACTIONS = 4
    N_ACTIONS = N_BATTERY_ACTIONS * N_EV_ACTIONS
    
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state_size = 25  # Size of state vector
        
        # Q-Table (vereinfacht, später durch Neural Network ersetzen)
        # Für schnelleres Lernen: Diskretisierter State-Space
        self.q_table: Dict[Tuple, np.ndarray] = defaultdict(
            lambda: np.zeros(self.N_ACTIONS)
        )
        
        self.memory = ReplayMemory(cfg.rl_memory_size)
        self.epsilon = cfg.rl_epsilon_start
        self.learning_rate = cfg.rl_learning_rate
        self.gamma = cfg.rl_discount_factor
        
        self.total_steps = 0
        self.training_episodes = 0
        
        self.load()
    
    def _discretize_state(self, state_vec: np.ndarray) -> Tuple:
        """Diskretisiert kontinuierlichen State für Q-Table."""
        # Grobe Diskretisierung für schnelleres Lernen
        discretized = []
        bins = [5, 3, 3, 5, 3, 3, 2, 3, 3, 4, 4, 4, 4]  # Bins pro Feature
        
        for i, (val, n_bins) in enumerate(zip(state_vec[:13], bins)):
            bin_idx = int(np.clip(val * n_bins, 0, n_bins - 1))
            discretized.append(bin_idx)
        
        # Preis-Forecast (vereinfacht: nur Durchschnitt)
        price_avg = np.mean(state_vec[13:19])
        discretized.append(int(np.clip(price_avg * 5, 0, 4)))
        
        # PV-Forecast (vereinfacht: nur Durchschnitt)
        pv_avg = np.mean(state_vec[19:25])
        discretized.append(int(np.clip(pv_avg * 3, 0, 2)))
        
        return tuple(discretized)
    
    def _action_to_tuple(self, action_idx: int) -> Tuple[int, int]:
        """Konvertiert Action-Index zu (battery_action, ev_action)."""
        battery = action_idx // self.N_EV_ACTIONS
        ev = action_idx % self.N_EV_ACTIONS
        return battery, ev
    
    def _tuple_to_action(self, battery: int, ev: int) -> int:
        """Konvertiert (battery_action, ev_action) zu Action-Index."""
        return battery * self.N_EV_ACTIONS + ev
    
    def select_action(self, state: SystemState, explore: bool = True) -> Action:
        """Wählt Aktion mit Epsilon-Greedy."""
        state_vec = state.to_vector()
        state_key = self._discretize_state(state_vec)
        
        if explore and random.random() < self.epsilon:
            # Exploration: zufällige Aktion
            action_idx = random.randint(0, self.N_ACTIONS - 1)
        else:
            # Exploitation: beste bekannte Aktion
            q_values = self.q_table[state_key]
            action_idx = int(np.argmax(q_values))
        
        battery_action, ev_action = self._action_to_tuple(action_idx)
        
        action = Action(battery_action=battery_action, ev_action=ev_action)
        self._compute_limits(action, state)
        
        return action
    
    def _compute_limits(self, action: Action, state: SystemState):
        """Berechnet EUR-Limits basierend auf Action."""
        if action.battery_action == 1:  # charge_grid
            action.battery_limit_eur = min(
                state.current_price + 0.02,
                self.cfg.battery_max_price_ct / 100
            )
        elif action.battery_action == 2:  # charge_pv_only
            action.battery_limit_eur = 0
        else:
            action.battery_limit_eur = None
        
        if action.ev_action == 1:  # charge_cheap
            action.ev_limit_eur = min(
                state.current_price + 0.02,
                self.cfg.ev_max_price_ct / 100
            )
        elif action.ev_action == 3:  # charge_pv_only
            action.ev_limit_eur = 0
        else:
            action.ev_limit_eur = None
    
    def imitation_learn(self, state: SystemState, expert_action: Action):
        """Lernt von LP-Entscheidung (Imitation Learning)."""
        state_vec = state.to_vector()
        state_key = self._discretize_state(state_vec)
        
        expert_idx = self._tuple_to_action(
            expert_action.battery_action,
            expert_action.ev_action
        )
        
        # Erhöhe Q-Wert für Experten-Aktion
        self.q_table[state_key][expert_idx] += self.learning_rate * 2
        
        self.total_steps += 1
    
    def learn(self, state: SystemState, action: Action, reward: float,
              next_state: SystemState, done: bool, priority: float = 1.0):
        """Lernt aus Erfahrung (Standard RL)."""
        state_vec = state.to_vector()
        next_state_vec = next_state.to_vector()
        
        action_idx = self._tuple_to_action(action.battery_action, action.ev_action)
        
        # Store in memory
        self.memory.push(state_vec, action_idx, reward, next_state_vec, done, priority)
        
        # Q-Learning Update
        state_key = self._discretize_state(state_vec)
        next_state_key = self._discretize_state(next_state_vec)
        
        current_q = self.q_table[state_key][action_idx]
        
        if done:
            target_q = reward
        else:
            target_q = reward + self.gamma * np.max(self.q_table[next_state_key])
        
        # Update Q-Value
        self.q_table[state_key][action_idx] += self.learning_rate * (target_q - current_q)
        
        # Decay epsilon
        self.epsilon = max(self.cfg.rl_epsilon_min, self.epsilon * self.cfg.rl_epsilon_decay)
        
        self.total_steps += 1
        
        # Batch learning from memory
        if len(self.memory) >= self.cfg.rl_batch_size and self.total_steps % 10 == 0:
            self._replay_learn()
    
    def _replay_learn(self):
        """Lernt aus Replay Memory."""
        batch = self.memory.sample(self.cfg.rl_batch_size)
        
        for state_vec, action_idx, reward, next_state_vec, done in batch:
            state_key = self._discretize_state(state_vec)
            next_state_key = self._discretize_state(next_state_vec)
            
            current_q = self.q_table[state_key][action_idx]
            
            if done:
                target_q = reward
            else:
                target_q = reward + self.gamma * np.max(self.q_table[next_state_key])
            
            self.q_table[state_key][action_idx] += self.learning_rate * 0.5 * (target_q - current_q)
    
    def save(self):
        """Speichert Modell."""
        try:
            # Konvertiere q_table keys zu strings
            q_table_serializable = {}
            for k, v in self.q_table.items():
                key_str = ",".join(map(str, k))  # Tuple zu "1,2,3,4,..."
                q_table_serializable[key_str] = v.tolist()
            
            data = {
                "q_table": q_table_serializable,
                "epsilon": self.epsilon,
                "total_steps": self.total_steps,
                "training_episodes": self.training_episodes,
                "saved_at": datetime.now().isoformat()
            }
            with open(RL_MODEL_PATH, 'w') as f:
                json.dump(data, f, indent=2)
            self.memory.save(RL_MEMORY_PATH)
            _log("info", f"RL model saved (steps: {self.total_steps}, q_states: {len(self.q_table)}, ε: {self.epsilon:.3f})")
        except Exception as e:
            _log("error", f"Could not save RL model: {e}")
            import traceback
            traceback.print_exc()
    
    def load(self):
        """Lädt Modell."""
        try:
            if not os.path.exists(RL_MODEL_PATH):
                _log("info", "No existing RL model found, starting fresh")
                return False
            
            with open(RL_MODEL_PATH, 'r') as f:
                data = json.load(f)
            
            self.q_table = defaultdict(lambda: np.zeros(self.N_ACTIONS))
            
            for key_str, v in data.get("q_table", {}).items():
                # Parse key zurück zu Tuple
                try:
                    key_tuple = tuple(map(int, key_str.split(",")))
                    self.q_table[key_tuple] = np.array(v)
                except:
                    continue
            
            self.epsilon = data.get("epsilon", self.cfg.rl_epsilon_start)
            self.total_steps = data.get("total_steps", 0)
            self.training_episodes = data.get("training_episodes", 0)
            
            # Lade Memory
            self.memory.load(RL_MEMORY_PATH)
            
            saved_at = data.get("saved_at", "unknown")
            _log("info", f"✓ RL model loaded (steps: {self.total_steps}, q_states: {len(self.q_table)}, "
                        f"memory: {len(self.memory)}, ε: {self.epsilon:.3f}, saved: {saved_at})")
            return True
            
        except Exception as e:
            _log("warning", f"Could not load RL model: {e}, starting fresh")
            return False
    
    def bootstrap_from_influxdb(self, influx: 'InfluxDBClient', hours: int = 168):
        """
        Bootstrapped das RL-Modell aus InfluxDB-Historie.
        Lädt die letzten X Stunden und simuliert daraus Lernerfahrungen.
        """
        _log("info", f"Bootstrapping RL from InfluxDB (last {hours}h)...")
        
        try:
            # Query historische Daten
            result = influx.get_history_hours(hours)
            
            if not result:
                _log("warning", "No historical data found in InfluxDB")
                return 0
            
            _log("info", f"Found {len(result)} historical data points")
            
            # Simuliere Lernerfahrungen
            learned = 0
            prev_point = None
            
            for point in result:
                try:
                    battery_soc = point.get("battery_soc", 50) or 50
                    price = point.get("price", 0.30) or 0.30
                    pv_power = point.get("pv_power", 0) or 0
                    home_power = point.get("home_power", 1000) or 1000
                    ev_soc = point.get("ev_soc", 0) or 0
                    ev_connected = point.get("ev_connected", 0) or 0
                    
                    # Erstelle State-Vektor
                    state_vec = np.zeros(25)
                    state_vec[0] = battery_soc / 100
                    state_vec[1] = price
                    state_vec[2] = pv_power / 10000
                    state_vec[3] = home_power / 5000
                    state_vec[4] = ev_soc / 100
                    state_vec[5] = float(ev_connected)
                    
                    if prev_point is not None:
                        prev_price = prev_point.get("price", 0.30) or 0.30
                        prev_battery = prev_point.get("battery_soc", 50) or 50
                        
                        # Ermittle was wahrscheinlich passiert ist
                        battery_changed = battery_soc - prev_battery
                        
                        # Erzeuge "Experten-Aktion" basierend auf was passiert ist
                        if battery_changed > 2 and prev_price < 0.32:
                            # Batterie wurde geladen bei günstigem Preis → gut!
                            action_idx = self._tuple_to_action(1, 0)  # charge
                            reward = 0.5  # Positive Belohnung
                        elif battery_changed < -2 and prev_price > 0.32:
                            # Batterie wurde entladen bei teurem Preis → gut!
                            action_idx = self._tuple_to_action(3, 0)  # discharge
                            reward = 0.3
                        elif battery_changed > 2 and prev_price > 0.35:
                            # Batterie wurde bei teurem Preis geladen → schlecht!
                            action_idx = self._tuple_to_action(1, 0)
                            reward = -0.3
                        else:
                            action_idx = self._tuple_to_action(0, 0)  # hold
                            reward = 0
                        
                        # Q-Learning Update
                        prev_state_vec = np.zeros(25)
                        prev_state_vec[0] = prev_battery / 100
                        prev_state_vec[1] = prev_price
                        
                        state_key = self._discretize_state(prev_state_vec)
                        next_state_key = self._discretize_state(state_vec)
                        
                        current_q = self.q_table[state_key][action_idx]
                        target_q = reward + self.gamma * np.max(self.q_table[next_state_key])
                        self.q_table[state_key][action_idx] += self.learning_rate * 0.3 * (target_q - current_q)
                        
                        learned += 1
                    
                    prev_point = point
                    
                except Exception as e:
                    continue
            
            if learned > 0:
                _log("info", f"✓ Bootstrapped {learned} experiences from InfluxDB, "
                           f"Q-table now has {len(self.q_table)} states")
            
            return learned
            
        except Exception as e:
            _log("warning", f"Bootstrap from InfluxDB failed: {e}")
            import traceback
            traceback.print_exc()
            return 0


# =============================================================================
# COMPARATOR & REWARD CALCULATOR
# =============================================================================

class Comparator:
    """Vergleicht LP und RL Entscheidungen."""
    
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.comparisons: List[Dict] = []
        self.lp_total_cost = 0.0
        self.rl_total_cost = 0.0
        self.rl_wins = 0
        self.rl_ready = False
        
        # Pro-Device Tracking (v3.0)
        self.device_comparisons: Dict[str, int] = defaultdict(int)
        self.device_wins: Dict[str, int] = defaultdict(int)
        self.device_costs_lp: Dict[str, float] = defaultdict(float)
        self.device_costs_rl: Dict[str, float] = defaultdict(float)
        
        self.load()
    
    def calculate_reward(self, state: SystemState, action: Action, 
                        next_state: SystemState, events: List[str]) -> float:
        """Berechnet Reward für RL-Lernen."""
        reward = 0.0
        
        # 1. Kostenbasierter Reward
        # Kosten = Grid-Import * Preis - Grid-Export * FeedIn
        if state.grid_power > 0:  # Import
            cost = state.grid_power / 1000 * state.current_price / 4  # pro 15 min
            reward -= cost * 10  # Skaliert
        else:  # Export
            revenue = abs(state.grid_power) / 1000 * (self.cfg.feed_in_tariff_ct / 100) / 4
            reward += revenue * 5
        
        # 2. Reward Shaping: Batterie-SoC
        if next_state.battery_soc > state.battery_soc and state.current_price < 0.15:
            reward += 0.5  # Gut: Laden bei niedrigem Preis
        if next_state.battery_soc < state.battery_soc and state.current_price > 0.25:
            reward += 0.3  # Gut: Entladen bei hohem Preis
        
        # 3. Reward Shaping: EV
        if state.ev_connected and next_state.ev_soc > state.ev_soc:
            if state.current_price < 0.20:
                reward += 0.5  # Gut: EV laden bei günstigem Preis
            elif state.pv_power > 3000:
                reward += 0.8  # Sehr gut: EV laden mit PV
        
        # 4. Event-basierte Rewards
        for event in events:
            if event == "EV_CHARGED_EXTERNALLY":
                # Wir haben nicht geladen, aber EV ist voll - neutral/leicht negativ
                reward -= 0.2
            elif event == "PRICE_DROP" and action.battery_action == 1:
                reward += 0.5  # Gut: Laden bei Preiseinbruch
            elif event == "PRICE_SPIKE" and action.battery_action == 3:
                reward += 0.5  # Gut: Entladen bei Preisspitze
            elif event == "PV_SURGE" and action.battery_action == 2:
                reward += 0.3  # Gut: PV nutzen
        
        # 5. Penalty für schlechte Aktionen
        if action.battery_action == 1 and state.current_price > self.cfg.battery_max_price_ct / 100:
            reward -= 2.0  # Schlecht: Laden über Maximum
        if state.battery_soc < 15 and action.battery_action == 3:
            reward -= 1.0  # Schlecht: Entladen bei niedrigem SoC
        
        return reward
    
    def compare(self, state: SystemState, lp_action: Action, rl_action: Action,
                actual_cost: float):
        """Vergleicht LP und RL für diese Entscheidung."""
        
        # Simulierte Kosten für RL-Aktion (vereinfacht)
        rl_simulated_cost = actual_cost  # Basis: gleich wie LP
        
        # Anpassung basierend auf Aktionsunterschied
        if rl_action.battery_action != lp_action.battery_action:
            if rl_action.battery_action == 1 and state.current_price < 0.15:
                rl_simulated_cost -= 0.05  # RL hätte billiger geladen
            elif rl_action.battery_action == 0 and state.current_price > 0.20:
                rl_simulated_cost -= 0.03  # RL hätte teures Laden vermieden
        
        comparison = {
            "timestamp": state.timestamp.isoformat(),
            "lp_action": (lp_action.battery_action, lp_action.ev_action),
            "rl_action": (rl_action.battery_action, rl_action.ev_action),
            "price": state.current_price,
            "battery_soc": state.battery_soc,
            "lp_cost": actual_cost,
            "rl_simulated_cost": rl_simulated_cost,
            "rl_better": rl_simulated_cost <= actual_cost
        }
        
        self.comparisons.append(comparison)
        self.lp_total_cost += actual_cost
        self.rl_total_cost += rl_simulated_cost
        
        if rl_simulated_cost <= actual_cost:
            self.rl_wins += 1
        
        # Check if RL is ready
        if len(self.comparisons) >= self.cfg.rl_ready_min_comparisons:
            win_rate = self.rl_wins / len(self.comparisons)
            if win_rate >= self.cfg.rl_ready_threshold and not self.rl_ready:
                self.rl_ready = True
                _log("info", "=" * 60)
                _log("info", "🎉 RL READY! Agent hat ausreichend gelernt.")
                _log("info", f"   Win-Rate: {win_rate*100:.1f}% ({self.rl_wins}/{len(self.comparisons)})")
                _log("info", f"   LP Gesamtkosten: €{self.lp_total_cost:.2f}")
                _log("info", f"   RL Gesamtkosten: €{self.rl_total_cost:.2f}")
                _log("info", f"   Ersparnis: €{self.lp_total_cost - self.rl_total_cost:.2f}")
                _log("info", "=" * 60)
        
        # Periodic logging
        if len(self.comparisons) % 50 == 0:
            win_rate = self.rl_wins / len(self.comparisons)
            _log("info", f"RL Progress: {len(self.comparisons)} comparisons, "
                        f"win rate {win_rate*100:.1f}%, "
                        f"ε={self.cfg.rl_epsilon_start:.3f}")
        
        self.save()
    
    def compare_per_device(self, state: SystemState, lp_action: Action, rl_action: Action, 
                          actual_cost: float, rl_device_controller: 'RLDeviceController'):
        """
        Vergleicht LP vs RL pro Gerät und updated RLDeviceController.
        v3.0 Feature.
        """
        # Battery Comparison
        battery_lp_cost = self._eval_battery_cost(state, lp_action)
        battery_rl_cost = self._eval_battery_cost(state, rl_action)
        
        self.device_comparisons["battery"] += 1
        if battery_rl_cost <= battery_lp_cost:
            self.device_wins["battery"] += 1
        
        self.device_costs_lp["battery"] += battery_lp_cost
        self.device_costs_rl["battery"] += battery_rl_cost
        
        # Berechne Win-Rate
        battery_win_rate = self.device_wins["battery"] / max(1, self.device_comparisons["battery"])
        battery_saved_ct = (battery_lp_cost - battery_rl_cost) * 100
        
        # Update RLDeviceController
        rl_device_controller.update_performance(
            "battery",
            battery_win_rate,
            self.device_comparisons["battery"],
            battery_saved_ct
        )
        
        # EV Comparison (wenn verbunden)
        if state.ev_connected and state.ev_name:
            ev_name = state.ev_name
            ev_lp_cost = self._eval_ev_cost(state, lp_action)
            ev_rl_cost = self._eval_ev_cost(state, rl_action)
            
            self.device_comparisons[ev_name] += 1
            if ev_rl_cost <= ev_lp_cost:
                self.device_wins[ev_name] += 1
            
            self.device_costs_lp[ev_name] += ev_lp_cost
            self.device_costs_rl[ev_name] += ev_rl_cost
            
            ev_win_rate = self.device_wins[ev_name] / max(1, self.device_comparisons[ev_name])
            ev_saved_ct = (ev_lp_cost - ev_rl_cost) * 100
            
            rl_device_controller.update_performance(
                ev_name,
                ev_win_rate,
                self.device_comparisons[ev_name],
                ev_saved_ct
            )
    
    def _eval_battery_cost(self, state: SystemState, action: Action) -> float:
        """Evaluiert Kosten für Batterie-Aktion (vereinfacht)."""
        cost = 0.0
        if action.battery_action == 1:  # charge_grid
            # Laden aus Netz
            cost = state.current_price * 0.25  # Vereinfacht: 0.25 kWh pro 15min
        elif action.battery_action == 3:  # discharge
            # Entladen (negative Kosten = Einnahmen)
            cost = -state.current_price * 0.20
        return cost
    
    def _eval_ev_cost(self, state: SystemState, action: Action) -> float:
        """Evaluiert Kosten für EV-Aktion (vereinfacht)."""
        cost = 0.0
        if action.ev_action in [1, 2]:  # charge_cheap oder charge_now
            cost = state.current_price * 2.0  # EV lädt mehr: ~2 kWh pro 15min
        return cost
    
    def get_status(self) -> Dict:
        """Gibt aktuellen Status zurück."""
        n = len(self.comparisons)
        return {
            "comparisons": n,
            "rl_wins": self.rl_wins,
            "win_rate": self.rl_wins / n if n > 0 else 0,
            "lp_total_cost": self.lp_total_cost,
            "rl_total_cost": self.rl_total_cost,
            "rl_ready": self.rl_ready,
            "ready_threshold": self.cfg.rl_ready_threshold,
            "ready_min_comparisons": self.cfg.rl_ready_min_comparisons
        }
    
    def save(self):
        try:
            data = {
                "comparisons": self.comparisons[-1000:],  # Letzte 1000
                "lp_total_cost": self.lp_total_cost,
                "rl_total_cost": self.rl_total_cost,
                "rl_wins": self.rl_wins,
                "rl_ready": self.rl_ready
            }
            with open(COMPARISON_LOG_PATH, 'w') as f:
                json.dump(data, f)
        except:
            pass
    
    def load(self):
        try:
            with open(COMPARISON_LOG_PATH, 'r') as f:
                data = json.load(f)
            self.comparisons = data.get("comparisons", [])
            self.lp_total_cost = data.get("lp_total_cost", 0)
            self.rl_total_cost = data.get("rl_total_cost", 0)
            self.rl_wins = data.get("rl_wins", 0)
            self.rl_ready = data.get("rl_ready", False)
            _log("info", f"Comparator loaded: {len(self.comparisons)} comparisons, "
                        f"win rate {self.rl_wins/max(1,len(self.comparisons))*100:.1f}%")
        except:
            pass


# =============================================================================
# RL DEVICE CONTROLLER (v2.6.8 - Pro-Device RL Management)
# =============================================================================

class RLDeviceController:
    """
    Verwaltet RL-Modi pro Gerät mit SQLite-Persistenz.
    
    Modi:
    - lp: Immer LP nutzen
    - rl: Immer RL nutzen  
    - auto: Automatisch basierend auf Performance
    
    Overrides (persistent):
    - manual_lp: User forciert LP (bleibt auch bei RL-Ready)
    - manual_rl: User forciert RL (nur wenn ready!)
    - None: Kein Override, folge auto-Logik
    """
    
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db_path = "/data/smartprice_device_control.db"
        self._init_database()
        
    def _init_database(self):
        """Erstellt SQLite-Datenbank wenn nicht vorhanden."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS device_control (
                device_name TEXT PRIMARY KEY,
                current_mode TEXT NOT NULL,
                override_mode TEXT,
                win_rate REAL DEFAULT 0.0,
                comparisons INTEGER DEFAULT 0,
                cost_saved_total_ct REAL DEFAULT 0.0,
                last_switch TIMESTAMP,
                switch_reason TEXT
            )
        ''')
        conn.commit()
        conn.close()
        _log("debug", f"RLDeviceController database initialized at {self.db_path}")
    
    def get_device_mode(self, device_name: str) -> str:
        """
        Gibt aktuellen Mode für Gerät zurück: 'lp' oder 'rl'
        Berücksichtigt Override und Auto-Switching-Logik.
        """
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT current_mode, override_mode, win_rate, comparisons FROM device_control WHERE device_name = ?', 
                  (device_name,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            # Neues Gerät → Initialisiere mit LP
            self._init_device(device_name, "lp", None)
            return "lp"
        
        current_mode, override_mode, win_rate, comparisons = row
        
        # Override hat höchste Priorität
        if override_mode:
            if override_mode == "manual_lp":
                return "lp"
            elif override_mode == "manual_rl":
                return "rl"
        
        # Kein Override → Auto-Logik wenn enabled
        if self.cfg.rl_auto_switch:
            # RL Ready? → Wechsel zu RL
            if win_rate >= self.cfg.rl_ready_threshold and comparisons >= self.cfg.rl_ready_min_comparisons:
                if current_mode == "lp":
                    self._switch_mode(device_name, "rl", "auto_ready")
                    _log("info", f"🎉 {device_name}: Auto-Switch LP → RL (Win-Rate {win_rate:.1%})")
                return "rl"
            
            # RL Performance schlecht? → Fallback zu LP
            elif win_rate < self.cfg.rl_fallback_threshold and comparisons >= 50:
                if current_mode == "rl":
                    self._switch_mode(device_name, "lp", "auto_fallback")
                    _log("warning", f"⚠️ {device_name}: Auto-Fallback RL → LP (Win-Rate {win_rate:.1%})")
                return "lp"
        
        # Default: Aktueller Mode
        return current_mode
    
    def set_override(self, device_name: str, override_mode: Optional[str]) -> dict:
        """
        Setzt manuellen Override für Gerät.
        override_mode: 'manual_lp', 'manual_rl', 'auto' (=None)
        """
        import sqlite3
        
        if override_mode == "auto":
            override_mode = None
        
        if override_mode == "manual_rl":
            # Prüfe ob RL ready ist
            status = self.get_device_status(device_name)
            if not status.get("is_ready", False):
                return {
                    "error": "RL not ready yet",
                    "message": f"Device '{device_name}' needs {self.cfg.rl_ready_min_comparisons} comparisons and {self.cfg.rl_ready_threshold*100}% win-rate"
                }
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Bestimme neuen current_mode
        new_mode = "rl" if override_mode == "manual_rl" else "lp"
        old_mode = self.get_device_mode(device_name)
        
        c.execute('''
            UPDATE device_control 
            SET current_mode = ?, override_mode = ?, last_switch = ?, switch_reason = ?
            WHERE device_name = ?
        ''', (new_mode, override_mode, datetime.now(timezone.utc).isoformat(), "manual_override", device_name))
        
        conn.commit()
        conn.close()
        
        _log("info", f"🔧 {device_name}: Manual override → {override_mode or 'auto'} (mode: {new_mode})")
        
        return {
            "status": "ok",
            "device": device_name,
            "old_mode": old_mode,
            "new_mode": new_mode,
            "override": override_mode
        }
    
    def update_performance(self, device_name: str, win_rate: float, comparisons: int, cost_saved_ct: float = 0):
        """Aktualisiert Performance-Metriken für Gerät."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Hole aktuellen Gesamt-Saved
        c.execute('SELECT cost_saved_total_ct FROM device_control WHERE device_name = ?', (device_name,))
        row = c.fetchone()
        total_saved = (row[0] if row else 0) + cost_saved_ct
        
        c.execute('''
            UPDATE device_control 
            SET win_rate = ?, comparisons = ?, cost_saved_total_ct = ?
            WHERE device_name = ?
        ''', (win_rate, comparisons, total_saved, device_name))
        
        conn.commit()
        conn.close()
    
    def get_device_status(self, device_name: str) -> dict:
        """Gibt kompletten Status für Gerät zurück."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT * FROM device_control WHERE device_name = ?', (device_name,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            return {
                "device": device_name,
                "current_mode": "lp",
                "override_mode": None,
                "win_rate": 0.0,
                "comparisons": 0,
                "is_ready": False,
                "cost_saved_total_ct": 0.0,
                "last_switch": None,
                "switch_reason": None
            }
        
        _, current_mode, override_mode, win_rate, comparisons, cost_saved, last_switch, reason = row
        
        is_ready = (win_rate >= self.cfg.rl_ready_threshold and 
                    comparisons >= self.cfg.rl_ready_min_comparisons)
        
        return {
            "device": device_name,
            "current_mode": current_mode,
            "override_mode": override_mode,
            "win_rate": win_rate,
            "comparisons": comparisons,
            "is_ready": is_ready,
            "cost_saved_total_ct": cost_saved,
            "last_switch": last_switch,
            "switch_reason": reason
        }
    
    def get_all_devices(self) -> dict:
        """Gibt Status aller Geräte zurück."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT device_name FROM device_control')
        devices = {}
        for row in c.fetchall():
            device_name = row[0]
            devices[device_name] = self.get_device_status(device_name)
        conn.close()
        return devices
    
    def _init_device(self, device_name: str, initial_mode: str = "lp", override_mode: Optional[str] = None):
        """Initialisiert neues Gerät in Datenbank."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT OR IGNORE INTO device_control 
            (device_name, current_mode, override_mode)
            VALUES (?, ?, ?)
        ''', (device_name, initial_mode, override_mode))
        conn.commit()
        conn.close()
        _log("debug", f"Initialized device '{device_name}' with mode '{initial_mode}'")
    
    def _switch_mode(self, device_name: str, new_mode: str, reason: str):
        """Interner Mode-Switch (für Auto-Logic)."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            UPDATE device_control 
            SET current_mode = ?, last_switch = ?, switch_reason = ?
            WHERE device_name = ?
        ''', (new_mode, datetime.now(timezone.utc).isoformat(), reason, device_name))
        conn.commit()
        conn.close()


# =============================================================================
# CONTROLLER (APPLIES ACTIONS)
# =============================================================================

class Controller:
    """Wendet Aktionen auf evcc an."""
    
    def __init__(self, evcc: EvccClient, cfg: Config):
        self.evcc = evcc
        self.cfg = cfg
        self.last_action: Optional[Action] = None
    
    def apply(self, action: Action) -> float:
        """Wendet Aktion an und gibt geschätzte Kosten zurück."""
        
        # Battery
        if action.battery_limit_eur is not None:
            if action.battery_limit_eur > 0:
                self.evcc.set_battery_grid_charge_limit(action.battery_limit_eur)
                _log("info", f"Battery: charge @ max {action.battery_limit_eur*100:.1f} ct/kWh")
            else:
                self.evcc.clear_battery_grid_charge_limit()
                _log("info", "Battery: PV-only mode")
        else:
            self.evcc.clear_battery_grid_charge_limit()
            _log("debug", "Battery: hold/discharge")
        
        # EV
        if action.ev_limit_eur is not None:
            if action.ev_limit_eur > 0:
                self.evcc.set_smart_cost_limit(action.ev_limit_eur)
                _log("info", f"EV: charge @ max {action.ev_limit_eur*100:.1f} ct/kWh")
            else:
                self.evcc.set_smart_cost_limit(0)
                _log("info", "EV: PV-only mode")
        
        self.last_action = action
        
        # Geschätzte Kosten (wird später mit echten Kosten verglichen)
        return 0.0


# =============================================================================
# VEHICLE MONITOR (Polling aller Fahrzeuge)
# =============================================================================

@dataclass
class VehicleStatus:
    """Status eines Fahrzeugs (auch wenn nicht verbunden)."""
    name: str
    soc: float
    capacity_kwh: float
    range_km: float
    last_update: datetime
    connected_to_wallbox: bool = False
    charging: bool = False
    data_source: str = "evcc"  # 'evcc', 'direct_api', 'cache', 'unknown'
    provider_type: str = "evcc"  # 'kia', 'renault', 'evcc', 'manual'


class VehicleMonitor:
    """
    Überwacht alle konfigurierten Fahrzeuge.
    
    Nutzt das modulare Vehicle-Provider-System wenn konfiguriert,
    ansonsten Fallback auf evcc API.
    """
    
    def __init__(self, evcc: 'EvccClient', cfg: Config):
        self.evcc = evcc
        self.cfg = cfg
        self.vehicles: Dict[str, VehicleStatus] = {}
        self.poll_interval_minutes = cfg.vehicle_poll_interval_minutes
        self._running = False
        self._last_poll = None
        
        # Modulares Vehicle Manager System
        self._vehicle_manager = None
        self._init_vehicle_manager()
    
    def _init_vehicle_manager(self):
        """Initialisiert den modularen VehicleManager wenn konfiguriert."""
        if not HAS_VEHICLE_MODULE:
            _log("info", "Vehicle module not available, using evcc-only mode")
            return
        
        if not self.cfg.vehicle_providers:
            _log("info", "No vehicle providers configured, using evcc-only mode")
            return
        
        try:
            # Parse evcc URL für Host/Port
            evcc_host = "192.168.1.66"
            evcc_port = 7070
            if self.cfg.evcc_url:
                from urllib.parse import urlparse
                parsed = urlparse(self.cfg.evcc_url)
                evcc_host = parsed.hostname or evcc_host
                evcc_port = parsed.port or evcc_port
            
            vehicle_config = {
                "poll_interval_minutes": self.poll_interval_minutes,
                "providers": self.cfg.vehicle_providers
            }
            
            self._vehicle_manager = VehicleManager(
                config=vehicle_config,
                evcc_host=evcc_host,
                evcc_port=evcc_port
            )
            
            _log("info", f"Vehicle Manager initialized with {len(self.cfg.vehicle_providers)} providers")
            
        except Exception as e:
            _log("error", f"Failed to init VehicleManager: {e}")
            self._vehicle_manager = None
    
    def start_polling(self):
        """Startet das Hintergrund-Polling."""
        self._running = True
        
        # Wenn VehicleManager vorhanden, nutze dessen Polling
        if self._vehicle_manager:
            self._vehicle_manager.start_polling()
        
        def poll_loop():
            while self._running:
                try:
                    self._poll_vehicles()
                except Exception as e:
                    _log("error", f"Vehicle polling error: {e}")
                # Poll alle 60 Sekunden um frische Daten vom VehicleManager zu holen
                # (Der VehicleManager selbst pollt die APIs nur alle 30 min)
                time.sleep(60)
        
        # Warte kurz damit VehicleManager starten kann
        time.sleep(2)
        
        # Initialer Poll
        self._poll_vehicles()
        
        threading.Thread(target=poll_loop, daemon=True).start()
        _log("info", f"Vehicle monitor started (polling every {self.poll_interval_minutes} min)")
    
    def _refresh_vehicle_soc(self, vehicle_name: str) -> bool:
        """
        Fordert evcc auf, den SoC eines Fahrzeugs zu aktualisieren.
        evcc pollt dann die Fahrzeug-API (KIA Connect, etc.)
        """
        try:
            # evcc hat einen Endpoint um Vehicle-Daten zu refreshen
            url = f"{self.evcc.base_url}/api/vehicles/{vehicle_name}/soc"
            r = self.evcc.sess.post(url, timeout=30)
            if r.status_code == 200:
                _log("debug", f"Triggered SoC refresh for {vehicle_name}")
                return True
            else:
                _log("debug", f"SoC refresh for {vehicle_name} returned {r.status_code}")
                return False
        except Exception as e:
            _log("debug", f"Could not refresh {vehicle_name}: {e}")
            return False
    
    def _poll_vehicles(self):
        """Pollt alle Fahrzeuge - zuerst vom VehicleManager, dann evcc."""
        now = datetime.now(timezone.utc)
        
        # 1. Hole Daten vom modularen VehicleManager (wenn vorhanden)
        if self._vehicle_manager:
            try:
                vm_states = self._vehicle_manager.get_all_vehicles()
                _log("debug", f"VehicleManager returned {len(vm_states)} vehicles")
                
                for name, state in vm_states.items():
                    _log("debug", f"  {name}: has_valid_soc={state.has_valid_soc}, soc={state.soc}, data_source={state.data_source}")
                    
                    if state.has_valid_soc:
                        old_status = self.vehicles.get(name)
                        
                        self.vehicles[name] = VehicleStatus(
                            name=name,
                            soc=state.soc or 0,
                            capacity_kwh=state.capacity_kwh,
                            range_km=state.data.range_km if state.data else 0,
                            last_update=state.data.timestamp if state.data else now,
                            connected_to_wallbox=state.evcc_connected,
                            charging=state.data.is_charging if state.data else False,
                            data_source=state.data_source,
                            provider_type=state.provider_type
                        )
                        
                        # Log bei Änderungen
                        if old_status and abs(old_status.soc - state.soc) > 2:
                            _log("info", f"🔋 {name}: SoC {old_status.soc}% → {state.soc}% (via {state.data_source})")
                        elif not old_status:
                            _log("info", f"🚙 {name}: SoC={state.soc}% via {state.provider_type}")
                            
            except Exception as e:
                _log("error", f"VehicleManager poll error: {e}")
        
        # 2. Ergänze/Überschreibe mit evcc Daten für verbundene Fahrzeuge
        state = self.evcc.get_state()
        if not state:
            return
        
        vehicles_data = state.get("vehicles", {})
        loadpoints = state.get("loadpoints", [])
        
        # Welche Fahrzeuge sind an Loadpoints?
        connected_vehicles = {}
        for lp in loadpoints:
            if lp.get("connected") and lp.get("vehicleName"):
                vname = lp["vehicleName"]
                connected_vehicles[vname] = {
                    "soc": lp.get("vehicleSoc", 0),
                    "charging": lp.get("charging", False),
                    "charge_power": lp.get("chargePower", 0)
                }
        
        # Für nicht im VehicleManager enthaltene Fahrzeuge: Trigger evcc refresh
        for name in vehicles_data.keys():
            if name not in self.vehicles and name not in connected_vehicles:
                self._refresh_vehicle_soc(name)
        
        # Fahrzeuge aus evcc vehicles hinzufügen (wenn nicht schon vom VehicleManager)
        for name, data in vehicles_data.items():
            # Wenn schon Daten vom VehicleManager mit validem SoC, nicht überschreiben
            if name in self.vehicles:
                existing = self.vehicles[name]
                
                # Wenn wir Daten von direct_api haben, behalte sie
                if existing.data_source == "direct_api" and existing.soc > 0:
                    # Nur connected-Status aktualisieren
                    if name in connected_vehicles:
                        existing.connected_to_wallbox = True
                        existing.charging = connected_vehicles[name].get("charging", False)
                    _log("debug", f"Keeping direct_api data for {name}: SoC={existing.soc}%")
                    continue
            
            soc = data.get("soc", 0)
            capacity = data.get("capacity", self.cfg.ev_default_energy_kwh)
            range_km = data.get("range", 0)
            charging = data.get("charging", False)
            
            # Wenn SoC 0, versuche aus connected loadpoint
            if soc == 0 and name in connected_vehicles:
                soc = connected_vehicles[name].get("soc", 0)
                charging = connected_vehicles[name].get("charging", False)
            
            # Wenn immer noch 0, versuche vehicleSoc
            if soc == 0:
                soc = data.get("vehicleSoc", 0)
            
            old_status = self.vehicles.get(name)
            
            self.vehicles[name] = VehicleStatus(
                name=name,
                soc=soc,
                capacity_kwh=capacity,
                range_km=range_km,
                last_update=now,
                connected_to_wallbox=name in connected_vehicles,
                charging=charging,
                data_source="evcc",
                provider_type="evcc"
            )
            
            # Log bei Änderungen
            if old_status:
                if abs(old_status.soc - soc) > 2:
                    if soc > old_status.soc and name not in connected_vehicles:
                        _log("info", f"🔌 {name}: SoC {old_status.soc}% → {soc}% (extern geladen!)")
                    elif soc < old_status.soc:
                        _log("info", f"🚗 {name}: SoC {old_status.soc}% → {soc}% (gefahren)")
            else:
                _log("info", f"🚙 Vehicle discovered: {name} ({capacity:.0f}kWh, SoC: {soc}%)")
        
        self._last_poll = now
        _log("debug", f"Polled {len(self.vehicles)} vehicles: " + 
                     ", ".join(f"{v.name}:{v.soc}%({v.data_source})" for v in self.vehicles.values()))
    
    def trigger_refresh(self, vehicle_name: str = None):
        """Trigger sofortigen Refresh (z.B. wenn Fahrzeug verbunden wird)."""
        if self._vehicle_manager:
            self._vehicle_manager.trigger_immediate_refresh(vehicle_name)
        self._poll_vehicles()
    
    def get_vehicle(self, name: str) -> Optional[VehicleStatus]:
        """Gibt Status eines Fahrzeugs zurück."""
        return self.vehicles.get(name)
    
    def get_all_vehicles(self) -> Dict[str, VehicleStatus]:
        """Gibt alle Fahrzeuge zurück."""
        return self.vehicles.copy()
    
    def get_total_charge_needed(self, target_soc: int = 80) -> float:
        """Berechnet Gesamtladebedarf aller Fahrzeuge."""
        total = 0
        for v in self.vehicles.values():
            if v.soc < target_soc:
                need = (target_soc - v.soc) / 100 * v.capacity_kwh
                total += need
        return total
    
    def predict_charge_need(self) -> Dict[str, float]:
        """
        Gibt geschätzten Ladebedarf pro Fahrzeug zurück.
        Könnte später mit historischen Daten erweitert werden.
        """
        needs = {}
        for name, v in self.vehicles.items():
            if v.soc < self.cfg.ev_target_soc:
                need = (self.cfg.ev_target_soc - v.soc) / 100 * v.capacity_kwh
                needs[name] = need
        return needs
    
    def to_dict(self) -> dict:
        """Status als Dict für API."""
        return {
            "poll_interval_minutes": self.poll_interval_minutes,
            "last_poll": self._last_poll.isoformat() if self._last_poll else None,
            "vehicle_manager_active": self._vehicle_manager is not None,
            "vehicles": {
                name: {
                    "soc": v.soc,
                    "capacity_kwh": v.capacity_kwh,
                    "range_km": v.range_km,
                    "connected": v.connected_to_wallbox,
                    "charging": v.charging,
                    "data_source": v.data_source,
                    "provider_type": v.provider_type,
                    "last_update": v.last_update.isoformat()
                }
                for name, v in self.vehicles.items()
            }
        }


# =============================================================================
# DATA COLLECTOR
# =============================================================================

class DataCollector:
    """Sammelt Daten und erstellt SystemState."""
    
    def __init__(self, evcc: EvccClient, influx: InfluxDBClient, cfg: Config):
        self.evcc = evcc
        self.influx = influx
        self.cfg = cfg
        self._running = False
    
    def get_current_state(self) -> Optional[SystemState]:
        """Holt aktuellen Systemzustand inkl. Fahrzeugdaten."""
        state_data = self.evcc.get_state()
        if not state_data:
            return None
        
        tariffs = self.evcc.get_tariff_grid()
        
        # Parse tariffs for forecast
        price_forecast = []
        now = datetime.now(timezone.utc)
        for t in sorted(tariffs, key=lambda x: x.get("start", "")):
            try:
                start = datetime.fromisoformat(t["start"].replace("Z", "+00:00"))
                if start >= now:
                    price_forecast.append(float(t["value"]))
                    if len(price_forecast) >= 6:
                        break
            except:
                continue
        
        # PV forecast (vereinfacht aus State)
        pv_forecast = [state_data.get("pvPower", 0)] * 6  # Konstant als Fallback
        
        # Loadpoints - ERWEITERT für Fahrzeugdaten!
        loadpoints = state_data.get("loadpoints", [])
        vehicles = state_data.get("vehicles", {})  # Fahrzeug-Details aus evcc
        
        ev_connected = False
        ev_soc = 0
        ev_name = ""
        ev_capacity = self.cfg.ev_default_energy_kwh  # Fallback
        ev_charge_power = 11  # Default Wallbox
        wallbox_power = 0
        
        for lp in loadpoints:
            if lp.get("connected", False):
                ev_connected = True
                ev_soc = lp.get("vehicleSoc", 0)
                ev_name = lp.get("vehicleName", "")
                wallbox_power = lp.get("chargePower", 0)
                
                # Ladeleistung aus Loadpoint (max kW)
                lp_max_power = lp.get("maxCurrent", 16) * 230 * 3 / 1000  # 3-phasig
                ev_charge_power = min(11, lp_max_power)  # Max 11kW
                
                # Fahrzeug-Kapazität aus vehicles Dict
                if ev_name and ev_name in vehicles:
                    vehicle_data = vehicles[ev_name]
                    ev_capacity = vehicle_data.get("capacity", self.cfg.ev_default_energy_kwh)
                    _log("debug", f"Vehicle {ev_name}: capacity={ev_capacity}kWh from evcc")
                else:
                    # Fallback: Bekannte Fahrzeuge
                    ev_capacity = self._get_known_vehicle_capacity(ev_name)
                    _log("debug", f"Vehicle {ev_name}: capacity={ev_capacity}kWh (lookup/default)")
                
                break  # Nur erstes verbundenes EV
        
        # Home power (real)
        home_power_raw = state_data.get("homePower", 0)
        battery_power = state_data.get("batteryPower", 0)
        home_power_real = max(0, home_power_raw - wallbox_power)
        
        return SystemState(
            timestamp=datetime.now(timezone.utc),
            battery_soc=state_data.get("batterySoc", 50),
            battery_power=battery_power,
            grid_power=state_data.get("grid", {}).get("power", 0),
            current_price=state_data.get("tariffGrid", 0.25),
            pv_power=state_data.get("pvPower", 0),
            home_power=home_power_real,
            ev_connected=ev_connected,
            ev_soc=ev_soc,
            ev_power=wallbox_power,
            ev_name=ev_name,
            ev_capacity_kwh=ev_capacity,
            ev_charge_power_kw=ev_charge_power,
            price_forecast=price_forecast,
            pv_forecast=pv_forecast
        )
    
    def _get_known_vehicle_capacity(self, name: str) -> float:
        """Gibt bekannte Fahrzeugkapazität zurück."""
        # Normalisiere Name (lowercase, ohne Leerzeichen)
        name_lower = name.lower().replace(" ", "").replace("_", "").replace("-", "")
        
        known_vehicles = {
            # Deine Fahrzeuge
            "kiaev9": 99.8,
            "kia_ev9": 99.8,
            "ev9": 99.8,
            "twingo": 22.0,  # Renault Twingo Electric
            "renaulttwingo": 22.0,
            "ora03": 63.0,
            "ora": 63.0,
            "gwmora": 63.0,
            
            # Andere häufige EVs
            "teslamodel3": 60.0,
            "model3": 60.0,
            "teslmodely": 75.0,
            "modely": 75.0,
            "id3": 58.0,
            "id4": 77.0,
            "ioniq5": 77.4,
            "ioniq6": 77.4,
            "ev6": 77.4,
            "niro": 64.8,
        }
        
        for key, capacity in known_vehicles.items():
            if key in name_lower:
                return capacity
        
        # Unbekannt - Default
        return self.cfg.ev_default_energy_kwh
    
    def start_background_collection(self):
        """Startet Hintergrund-Datensammlung für InfluxDB."""
        self._running = True
        
        def collect_loop():
            while self._running:
                try:
                    state = self.get_current_state()
                    if state:
                        self._write_to_influx(state)
                except Exception as e:
                    _log("error", f"Collection error: {e}")
                time.sleep(self.cfg.data_collect_interval_sec)
        
        threading.Thread(target=collect_loop, daemon=True).start()
        _log("info", "Background data collection started")
    
    def _write_to_influx(self, state: SystemState):
        """Schreibt State nach InfluxDB."""
        ns = int(state.timestamp.timestamp() * 1e9)
        
        lines = [
            f"energy,source=smartprice "
            f"battery_soc={state.battery_soc},"
            f"battery_power={state.battery_power},"
            f"grid_power={state.grid_power},"
            f"pv_power={state.pv_power},"
            f"home_power={state.home_power},"
            f"ev_connected={int(state.ev_connected)},"
            f"ev_soc={state.ev_soc},"
            f"ev_power={state.ev_power},"
            f"price={state.current_price} "
            f"{ns}"
        ]
        
        self.influx.write_batch(lines)


# =============================================================================
# API SERVER (Fixed)
# =============================================================================

class SimpleAPIServer:
    """Einfacher HTTP API Server ohne aiohttp-Abhängigkeit."""
    
    def __init__(self, cfg: Config, optimizer: HolisticOptimizer, rl_agent: 'DQNAgent',
                 comparator: 'Comparator', event_detector: EventDetector,
                 collector: 'DataCollector', vehicle_monitor: 'VehicleMonitor',
                 rl_device_controller: 'RLDeviceController'):  # NEU v2.6.8
        self.cfg = cfg
        self.lp = optimizer
        self.rl = rl_agent
        self.comparator = comparator
        self.events = event_detector
        self.collector = collector
        self.vehicle_monitor = vehicle_monitor
        self.rl_devices = rl_device_controller  # NEU v2.6.8
        self._last_state: Optional[SystemState] = None
        self._last_lp_action: Optional[Action] = None
        self._last_rl_action: Optional[Action] = None
    
    def update_state(self, state: SystemState, lp_action: Action, rl_action: Action):
        """Aktualisiert den letzten Zustand für die API."""
        self._last_state = state
        self._last_lp_action = lp_action
        self._last_rl_action = rl_action
    
    def _calculate_rl_maturity(self, comparison: dict) -> dict:
        """Berechnet den RL Reifegrad."""
        comparisons = comparison.get("comparisons", 0)
        win_rate = comparison.get("win_rate", 0)
        ready = comparison.get("rl_ready", False)
        
        min_comparisons = self.cfg.rl_ready_min_comparisons
        threshold = self.cfg.rl_ready_threshold
        
        if ready:
            return {
                "status": "🎉 READY",
                "percent": 100,
                "message": f"RL ist bereit! Win-Rate: {win_rate*100:.0f}%",
                "color": "green"
            }
        
        # Fortschritt basierend auf Vergleichen und Win-Rate
        comparison_progress = min(100, (comparisons / min_comparisons) * 100)
        win_rate_progress = min(100, (win_rate / threshold) * 100) if threshold > 0 else 0
        
        # Gesamtfortschritt (gewichtet)
        overall = (comparison_progress * 0.4 + win_rate_progress * 0.6)
        
        if comparisons < 10:
            status = "🌱 Lernphase"
            message = f"Sammle Erfahrungen... ({comparisons}/{min_comparisons})"
            color = "orange"
        elif comparisons < min_comparisons * 0.5:
            status = "📈 Fortschritt"
            message = f"{comparisons} Vergleiche, Win-Rate: {win_rate*100:.0f}%"
            color = "blue"
        elif win_rate < threshold * 0.8:
            status = "🔧 Optimierung"
            message = f"Win-Rate {win_rate*100:.0f}% (Ziel: {threshold*100:.0f}%)"
            color = "yellow"
        else:
            status = "⏳ Fast bereit"
            message = f"Noch {min_comparisons - comparisons} Vergleiche"
            color = "lightgreen"
        
        return {
            "status": status,
            "percent": round(overall, 1),
            "message": message,
            "color": color,
            "comparisons": comparisons,
            "comparisons_needed": min_comparisons,
            "win_rate": round(win_rate * 100, 1),
            "win_rate_needed": threshold * 100
        }
    
    def _calculate_charge_slots(self, tariffs: List[Dict]) -> dict:
        """
        Berechnet optimale Ladeslots für alle Fahrzeuge und die Batterie.
        Gibt detaillierte Slot-Informationen zurück.
        """
        from datetime import datetime, timezone, timedelta
        from collections import defaultdict
        
        now = datetime.now(timezone.utc)
        
        # Parse Tarife zu stündlichen Preisen
        hourly = []
        buckets = defaultdict(list)
        
        for t in tariffs:
            try:
                start_str = t.get("start", "")
                val = float(t.get("value", 0))
                
                if start_str.endswith("Z"):
                    start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                elif "+" in start_str:
                    start = datetime.fromisoformat(start_str)
                else:
                    start = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
                
                hour = start.replace(minute=0, second=0, microsecond=0)
                if hour >= now - timedelta(hours=1):
                    buckets[hour].append(val)
            except:
                continue
        
        hourly = [(h, sum(v)/len(v)) for h, v in sorted(buckets.items())]
        
        if not hourly:
            return {"error": "Keine Preisdaten verfügbar"}
        
        # Deadline für EV (Standard 6:00 Uhr)
        deadline_hour = self.cfg.ev_charge_deadline_hour
        if now.hour < deadline_hour:
            ev_deadline = now.replace(hour=deadline_hour, minute=0, second=0, microsecond=0)
        else:
            ev_deadline = (now + timedelta(days=1)).replace(hour=deadline_hour, minute=0, second=0, microsecond=0)
        
        # Batterie-Bedarf
        battery_soc = self._last_state.battery_soc if self._last_state else 50
        battery_need_kwh = max(0, (self.cfg.battery_max_soc - battery_soc) / 100 * self.cfg.battery_capacity_kwh)
        battery_hours = int(battery_need_kwh / self.cfg.battery_charge_power_kw) + 1 if battery_need_kwh > 0.5 else 0
        
        # Alle Fahrzeuge
        vehicles = self.vehicle_monitor.get_all_vehicles()
        
        result = {
            "timestamp": now.isoformat(),
            "deadline": ev_deadline.strftime("%H:%M"),
            "hours_until_deadline": round((ev_deadline - now).total_seconds() / 3600, 1),
            "current_price_ct": round(hourly[0][1] * 100, 1) if hourly else 0,
            "prices_24h": [
                {
                    "hour": h.strftime("%H:%M"),
                    "price_ct": round(p * 100, 1),
                    "is_cheap": p <= min(pr for _, pr in hourly[:24]) * 1.1
                }
                for h, p in hourly[:24]
            ],
            "battery": self._calculate_device_slots(
                name="Hausbatterie",
                capacity_kwh=self.cfg.battery_capacity_kwh,
                current_soc=battery_soc,
                target_soc=self.cfg.battery_max_soc,
                charge_power_kw=self.cfg.battery_charge_power_kw,
                max_price_ct=self.cfg.battery_max_price_ct,
                hourly=hourly,
                deadline=None,  # Batterie hat keine harte Deadline
                icon="🔋"
            ),
            "vehicles": {}
        }
        
        # Slots für jedes Fahrzeug berechnen
        for name, vehicle in vehicles.items():
            result["vehicles"][name] = self._calculate_device_slots(
                name=name,
                capacity_kwh=vehicle.capacity_kwh,
                current_soc=vehicle.soc,
                target_soc=self.cfg.ev_target_soc,
                charge_power_kw=11,  # Wallbox max
                max_price_ct=self.cfg.ev_max_price_ct,
                hourly=hourly,
                deadline=ev_deadline,
                icon="🚗" if not vehicle.connected_to_wallbox else "🔌",
                last_update=vehicle.last_update
            )
        
        return result
    
    def _calculate_device_slots(
        self,
        name: str,
        capacity_kwh: float,
        current_soc: float,
        target_soc: float,
        charge_power_kw: float,
        max_price_ct: float,
        hourly: List[tuple],
        deadline: Optional[datetime],
        icon: str = "🔋",
        last_update: Optional[datetime] = None
    ) -> dict:
        """Berechnet Ladeslots für ein einzelnes Gerät."""
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        
        # Bedarf berechnen
        need_kwh = max(0, (target_soc - current_soc) / 100 * capacity_kwh)
        hours_needed = int(need_kwh / charge_power_kw * 1.2) + 1 if need_kwh > 1 else 0  # +20% Puffer
        
        if hours_needed == 0:
            return {
                "name": name,
                "icon": icon,
                "current_soc": current_soc,
                "target_soc": target_soc,
                "capacity_kwh": capacity_kwh,
                "need_kwh": 0,
                "hours_needed": 0,
                "status": "✅ Vollständig geladen",
                "slots": [],
                "total_cost_eur": 0,
                "avg_price_ct": 0,
                "last_update": last_update.isoformat() if last_update else None
            }
        
        # Filtere nach Deadline wenn vorhanden
        if deadline:
            eligible = [(h, p) for h, p in hourly if h < deadline and p <= max_price_ct / 100]
        else:
            eligible = [(h, p) for h, p in hourly[:24] if p <= max_price_ct / 100]
        
        if not eligible:
            return {
                "name": name,
                "icon": icon,
                "current_soc": current_soc,
                "target_soc": target_soc,
                "capacity_kwh": capacity_kwh,
                "need_kwh": round(need_kwh, 1),
                "hours_needed": hours_needed,
                "status": f"⚠️ Keine Stunden unter {max_price_ct}ct verfügbar",
                "slots": [],
                "total_cost_eur": 0,
                "avg_price_ct": 0,
                "last_update": last_update.isoformat() if last_update else None
            }
        
        # Sortiere nach Preis und nimm die günstigsten
        by_price = sorted(eligible, key=lambda x: x[1])
        chosen = by_price[:hours_needed]
        
        # Sortiere gewählte Slots nach Zeit für Anzeige
        chosen_by_time = sorted(chosen, key=lambda x: x[0])
        
        # Berechne Kosten
        total_kwh = min(need_kwh, hours_needed * charge_power_kw)
        kwh_per_slot = total_kwh / len(chosen) if chosen else 0
        
        slots = []
        total_cost = 0
        for h, p in chosen_by_time:
            slot_cost = kwh_per_slot * p
            total_cost += slot_cost
            slots.append({
                "hour": h.strftime("%H:%M"),
                "hour_end": (h + timedelta(hours=1)).strftime("%H:%M"),
                "price_ct": round(p * 100, 1),
                "power_kw": charge_power_kw,
                "energy_kwh": round(kwh_per_slot, 1),
                "cost_eur": round(slot_cost, 2),
                "is_now": h.hour == now.hour and h.date() == now.date()
            })
        
        avg_price = sum(p for _, p in chosen) / len(chosen) * 100 if chosen else 0
        
        # Status bestimmen
        if len(chosen) >= hours_needed:
            status = f"✅ {len(chosen)} Stunden geplant"
        else:
            status = f"⚠️ Nur {len(chosen)}/{hours_needed} Stunden verfügbar"
        
        return {
            "name": name,
            "icon": icon,
            "current_soc": current_soc,
            "target_soc": target_soc,
            "capacity_kwh": capacity_kwh,
            "need_kwh": round(need_kwh, 1),
            "hours_needed": hours_needed,
            "status": status,
            "slots": slots,
            "total_cost_eur": round(total_cost, 2),
            "avg_price_ct": round(avg_price, 1),
            "max_price_ct": max_price_ct,
            "threshold_ct": round(max(p for _, p in chosen) * 100, 1) if chosen else 0,
            "last_update": last_update.isoformat() if last_update else None
        }
    
    def _generate_dashboard_html(self) -> str:
        """Generiert ein HTML Dashboard mit detaillierten Ladeslots."""
        state = self._last_state
        comparison = self.comparator.get_status()
        maturity = self._calculate_rl_maturity(comparison)
        
        battery_soc = state.battery_soc if state else 0
        ev_soc = state.ev_soc if state else 0
        ev_connected = state.ev_connected if state else False
        ev_name = state.ev_name if state else ""
        ev_capacity = state.ev_capacity_kwh if state else 0
        price = state.current_price * 100 if state else 0
        pv = state.pv_power if state else 0
        home = state.home_power if state else 0
        
        bat_limit = self._last_lp_action.battery_limit_eur * 100 if self._last_lp_action and self._last_lp_action.battery_limit_eur else None
        ev_limit = self._last_lp_action.ev_limit_eur * 100 if self._last_lp_action and self._last_lp_action.ev_limit_eur else None
        
        # EV Info String
        if ev_connected:
            ev_label = f"{ev_name or 'EV'} 🔌"
            ev_detail = f"{ev_capacity:.0f}kWh" if ev_capacity else ""
        else:
            ev_label = "EV ⭕"
            ev_detail = ""
        
        # Hole Tarife für Slot-Berechnung
        tariffs = self.collector.evcc.get_tariff_grid() if self.collector else []
        charge_slots = self._calculate_charge_slots(tariffs) if tariffs else {}
        
        # Generiere HTML für Ladeslots
        slots_html = self._generate_slots_html(charge_slots)
        
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>EVCC-Smartload Dashboard</title>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="60">
    <style>
        body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; }}
        .card {{ background: #16213e; border-radius: 12px; padding: 20px; margin: 15px 0; }}
        .card h2 {{ margin-top: 0; color: #00d4ff; font-size: 1.1em; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; }}
        .metric {{ text-align: center; }}
        .metric .value {{ font-size: 2em; font-weight: bold; }}
        .metric .label {{ color: #888; font-size: 0.9em; }}
        .green {{ color: #00ff88; }}
        .orange {{ color: #ffaa00; }}
        .red {{ color: #ff4444; }}
        .blue {{ color: #00d4ff; }}
        .progress {{ background: #0f3460; border-radius: 10px; height: 20px; overflow: hidden; }}
        .progress-bar {{ height: 100%; background: linear-gradient(90deg, #00d4ff, #00ff88); transition: width 0.5s; }}
        .status-badge {{ display: inline-block; padding: 5px 15px; border-radius: 20px; font-weight: bold; }}
        .limits {{ display: flex; justify-content: space-around; text-align: center; }}
        .limit-item {{ padding: 10px; }}
        .limit-value {{ font-size: 1.5em; color: #00ff88; }}
        table {{ width: 100%; border-collapse: collapse; }}
        td, th {{ padding: 8px; text-align: left; border-bottom: 1px solid #333; }}
        
        /* Ladeslot Styles */
        .device-card {{ background: #0f3460; border-radius: 8px; padding: 15px; margin: 10px 0; }}
        .device-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
        .device-name {{ font-size: 1.2em; font-weight: bold; }}
        .device-status {{ font-size: 0.9em; }}
        .soc-bar {{ background: #1a1a2e; border-radius: 5px; height: 8px; margin: 5px 0; }}
        .soc-fill {{ height: 100%; border-radius: 5px; background: linear-gradient(90deg, #ff4444, #ffaa00, #00ff88); }}
        .slots-container {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
        .slot {{ background: #16213e; border-radius: 6px; padding: 8px 12px; text-align: center; min-width: 70px; border: 2px solid transparent; }}
        .slot.active {{ border-color: #00ff88; animation: pulse 2s infinite; }}
        .slot .time {{ font-weight: bold; color: #00d4ff; }}
        .slot .price {{ font-size: 1.1em; }}
        .slot .cost {{ font-size: 0.8em; color: #888; }}
        .slot.cheap {{ background: #0a2e1a; }}
        .slot.medium {{ background: #2e2a0a; }}
        .slot.expensive {{ background: #2e0a0a; }}
        .summary {{ display: flex; justify-content: space-around; margin-top: 15px; padding-top: 15px; border-top: 1px solid #333; }}
        .summary-item {{ text-align: center; }}
        .summary-value {{ font-size: 1.3em; font-weight: bold; color: #00ff88; }}
        .summary-label {{ font-size: 0.8em; color: #888; }}
        
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.7; }}
        }}
        
        /* Timeline */
        .timeline {{ display: flex; overflow-x: auto; padding: 10px 0; gap: 2px; }}
        .timeline-hour {{ min-width: 40px; text-align: center; padding: 5px; border-radius: 4px; font-size: 0.8em; }}
        .timeline-hour.past {{ opacity: 0.4; }}
        .timeline-hour.now {{ border: 2px solid #00d4ff; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ EVCC-Smartload v{VERSION}</h1>
        
        <div class="card">
            <h2>📊 Aktueller Status</h2>
            <div class="grid">
                <div class="metric">
                    <div class="value {'green' if battery_soc > 50 else 'orange'}">{battery_soc}%</div>
                    <div class="label">Batterie</div>
                </div>
                <div class="metric">
                    <div class="value {'green' if ev_connected else 'red'}">{ev_soc}%</div>
                    <div class="label">{ev_label}</div>
                    <div style="font-size: 0.8em; color: #666;">{ev_detail}</div>
                </div>
                <div class="metric">
                    <div class="value {'green' if price < 30 else 'orange' if price < 35 else 'red'}">{price:.1f}ct</div>
                    <div class="label">Strompreis</div>
                </div>
                <div class="metric">
                    <div class="value {'green' if pv > 500 else ''}">{pv:.0f}W</div>
                    <div class="label">PV</div>
                </div>
                <div class="metric">
                    <div class="value blue">{home:.0f}W</div>
                    <div class="label">Hausverbrauch</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>📅 Ladeplanung bis {charge_slots.get('deadline', '06:00')} Uhr ({charge_slots.get('hours_until_deadline', 0):.0f}h)</h2>
            {slots_html}
        </div>
        
        <div class="card">
            <h2>🤖 RL Reifegrad</h2>
            <div style="display: flex; align-items: center; gap: 20px;">
                <span class="status-badge" style="background: {maturity['color']}; color: #000;">
                    {maturity['status']}
                </span>
                <span style="font-size: 1.5em;">{maturity['percent']:.0f}%</span>
            </div>
            <div class="progress" style="margin-top: 15px;">
                <div class="progress-bar" style="width: {maturity['percent']}%;"></div>
            </div>
            <p style="color: #888; margin-top: 10px;">{maturity['message']}</p>
        </div>
        
        <div class="card">
            <h2>⚙️ Konfiguration</h2>
            <table>
                <tr><td>Batterie max</td><td>{self.cfg.battery_max_price_ct}ct</td></tr>
                <tr><td>EV max</td><td>{self.cfg.ev_max_price_ct}ct</td></tr>
                <tr><td>EV Deadline</td><td>{self.cfg.ev_charge_deadline_hour}:00 Uhr</td></tr>
            </table>
        </div>
        
        <p style="color: #555; text-align: center; margin-top: 30px;">
            <a href="/docs" style="color: #00d4ff; font-weight: bold;">📚 Dokumentation</a>
            <br><br>
            API: <a href="/status" style="color: #00d4ff;">/status</a> | 
            <a href="/slots" style="color: #00d4ff;">/slots</a> | 
            <a href="/vehicles" style="color: #00d4ff;">/vehicles</a> |
            <a href="/rl-devices" style="color: #00d4ff;">/rl-devices</a> |
            <a href="/config" style="color: #00d4ff;">/config</a>
            <br>Auto-refresh alle 60 Sekunden
        </p>
    </div>
</body>
</html>'''
    
    def _generate_slots_html(self, charge_slots: dict) -> str:
        """Generiert HTML für die Ladeslot-Anzeige."""
        if not charge_slots or "error" in charge_slots:
            return "<p style='color: #888;'>Keine Preisdaten verfügbar</p>"
        
        html_parts = []
        
        # Batterie
        battery = charge_slots.get("battery", {})
        if battery:
            html_parts.append(self._generate_device_html(battery, "battery"))
        
        # Fahrzeuge
        vehicles = charge_slots.get("vehicles", {})
        for name, vehicle in vehicles.items():
            html_parts.append(self._generate_device_html(vehicle, name))
        
        # Parallele Slots Warnung
        all_slots = []
        if battery.get("slots"):
            for s in battery["slots"]:
                all_slots.append((s["hour"], "Batterie", s["power_kw"]))
        for name, v in vehicles.items():
            if v.get("slots"):
                for s in v["slots"]:
                    all_slots.append((s["hour"], name, s["power_kw"]))
        
        # Finde Überlappungen
        from collections import defaultdict
        by_hour = defaultdict(list)
        for hour, device, power in all_slots:
            by_hour[hour].append((device, power))
        
        overlaps = [(h, devices) for h, devices in by_hour.items() if len(devices) > 1]
        
        if overlaps:
            html_parts.append('<div class="card" style="background: #2e2a0a; margin-top: 15px;">')
            html_parts.append('<h3 style="color: #ffaa00; margin-top: 0;">⚡ Parallele Ladung möglich</h3>')
            html_parts.append('<p style="font-size: 0.9em;">In diesen Stunden können mehrere Geräte gleichzeitig laden:</p>')
            html_parts.append('<ul style="margin: 10px 0;">')
            for hour, devices in sorted(overlaps):
                total_power = sum(p for _, p in devices)
                device_list = ", ".join(f"{d} ({p}kW)" for d, p in devices)
                html_parts.append(f'<li><strong>{hour}</strong>: {device_list} = <span class="orange">{total_power}kW</span></li>')
            html_parts.append('</ul>')
            html_parts.append('</div>')
        
        return "\n".join(html_parts)
    
    def _generate_device_html(self, device: dict, device_id: str) -> str:
        """Generiert HTML für ein einzelnes Gerät."""
        from datetime import datetime
        
        icon = device.get("icon", "🔋")
        name = device.get("name", device_id)
        soc = device.get("current_soc", 0)
        target = device.get("target_soc", 80)
        capacity = device.get("capacity_kwh", 0)
        need = device.get("need_kwh", 0)
        status = device.get("status", "")
        slots = device.get("slots", [])
        total_cost = device.get("total_cost_eur", 0)
        avg_price = device.get("avg_price_ct", 0)
        hours = device.get("hours_needed", 0)
        last_update_str = device.get("last_update")
        
        # Berechne "Alter" der Information
        age_text = ""
        if last_update_str:
            try:
                last_update = datetime.fromisoformat(last_update_str.replace('Z', '+00:00'))
                now = datetime.now(last_update.tzinfo)
                age_seconds = (now - last_update).total_seconds()
                
                if age_seconds < 120:  # < 2 Minuten
                    age_text = f"<span style='color: #00ff88;'>🕐 vor {int(age_seconds/60)}min</span>"
                elif age_seconds < 3600:  # < 1 Stunde
                    age_text = f"<span style='color: #ffaa00;'>🕐 vor {int(age_seconds/60)}min</span>"
                else:  # > 1 Stunde
                    hours_ago = int(age_seconds / 3600)
                    age_text = f"<span style='color: #ff4444;'>🕐 vor {hours_ago}h</span>"
            except:
                age_text = ""
        
        # SOC Farbe
        if soc >= 80:
            soc_color = "#00ff88"
        elif soc >= 50:
            soc_color = "#ffaa00"
        else:
            soc_color = "#ff4444"
        
        html = f'''
        <div class="device-card">
            <div class="device-header">
                <div>
                    <span class="device-name">{icon} {name}</span>
                    <span style="color: #888; margin-left: 10px;">{capacity:.0f} kWh</span>
                    {f'<span style="margin-left: 10px; font-size: 0.85em;">{age_text}</span>' if age_text else ''}
                </div>
                <div class="device-status">{status}</div>
            </div>
            
            <div style="display: flex; align-items: center; gap: 10px;">
                <span style="color: {soc_color}; font-size: 1.5em; font-weight: bold;">{soc}%</span>
                <div style="flex: 1;">
                    <div class="soc-bar">
                        <div class="soc-fill" style="width: {soc}%; background: {soc_color};"></div>
                    </div>
                </div>
                <span style="color: #888;">→ {target}%</span>
            </div>
        '''
        
        if need > 0 and slots:
            html += f'''
            <div style="margin-top: 10px; color: #888; font-size: 0.9em;">
                Bedarf: <strong>{need:.1f} kWh</strong> in <strong>{hours} Stunden</strong>
            </div>
            
            <div class="slots-container">
            '''
            
            for slot in slots:
                price = slot.get("price_ct", 0)
                if price < 30:
                    price_class = "cheap"
                elif price < 35:
                    price_class = "medium"
                else:
                    price_class = "expensive"
                
                active_class = "active" if slot.get("is_now") else ""
                
                html += f'''
                <div class="slot {price_class} {active_class}">
                    <div class="time">{slot.get("hour", "")}</div>
                    <div class="price" style="color: {'#00ff88' if price < 30 else '#ffaa00' if price < 35 else '#ff4444'};">{price:.1f}ct</div>
                    <div class="cost">{slot.get("energy_kwh", 0):.1f}kWh</div>
                    <div class="cost">€{slot.get("cost_eur", 0):.2f}</div>
                </div>
                '''
            
            html += '</div>'
            
            html += f'''
            <div class="summary">
                <div class="summary-item">
                    <div class="summary-value">{len(slots)}h</div>
                    <div class="summary-label">Ladedauer</div>
                </div>
                <div class="summary-item">
                    <div class="summary-value">{avg_price:.1f}ct</div>
                    <div class="summary-label">⌀ Preis</div>
                </div>
                <div class="summary-item">
                    <div class="summary-value">€{total_cost:.2f}</div>
                    <div class="summary-label">Gesamtkosten</div>
                </div>
            </div>
            '''
        elif need <= 0:
            html += '<p style="color: #00ff88; margin-top: 10px;">✅ Kein Ladebedarf</p>'
        else:
            html += f'<p style="color: #ffaa00; margin-top: 10px;">⚠️ {need:.1f} kWh Bedarf, aber keine passenden Slots</p>'
        
        html += '</div>'
        return html
    
    def _generate_docs_html(self) -> str:
        """Generiert Dokumentations-Index."""
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>EVCC-Smartload Dokumentation</title>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, sans-serif; margin: 40px; background: #1a1a2e; color: #eee; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; }}
        .doc-card {{ background: #16213e; padding: 20px; margin: 20px 0; border-radius: 8px; cursor: pointer; }}
        .doc-card:hover {{ background: #1e2d50; }}
        .doc-card h2 {{ margin-top: 0; color: #00ff88; }}
        a {{ color: #00d4ff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📚 EVCC-Smartload v{VERSION} Dokumentation</h1>
        <p style="color: #888;">Vollständige Dokumentation für Nutzer und Entwickler</p>
        
        <a href="/docs/readme">
            <div class="doc-card">
                <h2>📖 README - Benutzer-Handbuch</h2>
                <p>Vollständige Anleitung: Installation, Konfiguration, Features, API, FAQ</p>
            </div>
        </a>
        
        <a href="/docs/changelog">
            <div class="doc-card">
                <h2>📝 Changelog v3.0.0</h2>
                <p>Was ist neu? Breaking Changes, neue Features, Bugfixes</p>
            </div>
        </a>
        
        <a href="/docs/api">
            <div class="doc-card">
                <h2>🔌 API Dokumentation</h2>
                <p>Alle Endpoints mit Beispielen und Response-Formaten</p>
            </div>
        </a>
        
        <div class="doc-card" onclick="window.location.href='https://github.com/Krinco1/HA_Addon_EVCC-Smartload'">
            <h2>💾 GitHub Repository</h2>
            <p>Source Code, Issues, Discussions</p>
        </div>
        
        <p style="text-align: center; margin-top: 50px;">
            <a href="/">← Zurück zum Dashboard</a>
        </p>
    </div>
</body>
</html>'''
    
    def _generate_markdown_viewer(self, filename: str) -> str:
        """Liest Markdown-Datei und rendert als HTML."""
        try:
            # Versuche vom lokalen Dateisystem
            local_path = Path("/app") / filename
            if not local_path.exists():
                local_path = Path(__file__).parent.parent.parent / filename
            
            with open(local_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            content = f"# Fehler\n\nDokument konnte nicht geladen werden: {e}\n\nAlternativ siehe: https://github.com/Krinco1/HA_Addon_EVCC-Smartload"
        
        # Sehr einfaches Markdown → HTML (für basic formatting)
        html_content = content
        html_content = html_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Headers
        import re
        html_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)
        
        # Code blocks
        html_content = re.sub(r'```(\w+)?\n(.*?)\n```', r'<pre><code>\2</code></pre>', html_content, flags=re.DOTALL)
        html_content = re.sub(r'`([^`]+)`', r'<code>\1</code>', html_content)
        
        # Links
        html_content = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', html_content)
        
        # Bold/Italic
        html_content = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', html_content)
        html_content = re.sub(r'\*([^\*]+)\*', r'<em>\1</em>', html_content)
        
        # Lists
        html_content = re.sub(r'^\- (.+)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'(<li>.*</li>)', r'<ul>\1</ul>', html_content, flags=re.DOTALL)
        
        # Paragraphs
        html_content = '<p>' + html_content.replace('\n\n', '</p><p>') + '</p>'
        
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>{filename} - EVCC-Smartload Docs</title>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; line-height: 1.6; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; border-bottom: 2px solid #00d4ff; padding-bottom: 10px; }}
        h2 {{ color: #00ff88; margin-top: 30px; }}
        h3 {{ color: #ffaa00; }}
        code {{ background: #0f3460; padding: 2px 6px; border-radius: 3px; color: #00ff88; }}
        pre {{ background: #0f3460; padding: 15px; border-radius: 8px; overflow-x: auto; }}
        pre code {{ background: none; padding: 0; }}
        a {{ color: #00d4ff; }}
        ul {{ list-style: none; padding-left: 20px; }}
        li {{ margin: 8px 0; }}
        li:before {{ content: "▸ "; color: #00ff88; font-weight: bold; }}
        .back-link {{ margin: 30px 0; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        {html_content}
        <div class="back-link">
            <a href="/docs">← Zurück zur Dokumentation</a> | 
            <a href="/">Dashboard</a>
        </div>
    </div>
</body>
</html>'''
    
    def _generate_api_docs_html(self) -> str:
        """Generiert API-Dokumentations-Seite."""
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>API Dokumentation - EVCC-Smartload</title>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; }}
        .endpoint {{ background: #16213e; padding: 20px; margin: 20px 0; border-radius: 8px; }}
        .method {{ display: inline-block; padding: 4px 12px; border-radius: 4px; font-weight: bold; color: #000; }}
        .get {{ background: #00ff88; }}
        .post {{ background: #00d4ff; }}
        .path {{ font-family: monospace; color: #ffaa00; font-size: 1.1em; }}
        pre {{ background: #0f3460; padding: 15px; border-radius: 6px; overflow-x: auto; }}
        code {{ color: #00ff88; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔌 EVCC-Smartload API v{VERSION}</h1>
        <p>Basis-URL: <code>http://homeassistant:8099</code></p>
        
        <div class="endpoint">
            <span class="method get">GET</span>
            <span class="path">/health</span>
            <p>Health-Check für Monitoring</p>
            <pre><code>{{"status": "ok", "version": "{VERSION}"}}</code></pre>
        </div>
        
        <div class="endpoint">
            <span class="method get">GET</span>
            <span class="path">/status</span>
            <p>Vollständiger System-Status inkl. RL-Metriken</p>
        </div>
        
        <div class="endpoint">
            <span class="method get">GET</span>
            <span class="path">/vehicles</span>
            <p>Alle konfigurierten Fahrzeuge mit aktuellem Status</p>
        </div>
        
        <div class="endpoint">
            <span class="method get">GET</span>
            <span class="path">/slots</span>
            <p>Detaillierte Ladeslots für alle Geräte</p>
        </div>
        
        <div class="endpoint">
            <span class="method get">GET</span>
            <span class="path">/rl-devices</span>
            <p><strong>NEU v3.0:</strong> RL Device Control Status pro Gerät</p>
            <pre><code>{{
  "devices": {{
    "battery": {{
      "current_mode": "rl",
      "win_rate": 0.873,
      "comparisons": 341
    }}
  }}
}}</code></pre>
        </div>
        
        <div class="endpoint">
            <span class="method post">POST</span>
            <span class="path">/rl-override</span>
            <p><strong>NEU v3.0:</strong> Manueller Override für RL-Mode</p>
            <p>Request:</p>
            <pre><code>{{
  "device": "battery",
  "mode": "manual_lp"  // oder: manual_rl, auto
}}</code></pre>
        </div>
        
        <p style="text-align: center; margin-top: 50px;">
            <a href="/docs">← Zurück zur Dokumentation</a>
        </p>
    </div>
</body>
</html>'''
    
    def start(self):
        """Startet den API Server."""
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import json
        
        api = self
        
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress default logging
            
            def _send_json(self, data: dict, status: int = 200):
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data, indent=2, default=str).encode())
            
            def _send_html(self, html: str, status: int = 200):
                self.send_response(status)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode())
            
            def do_GET(self):
                if self.path == '/health':
                    self._send_json({"status": "ok", "version": "2.2.0"})
                
                elif self.path == '/':
                    # HTML Dashboard
                    self._send_html(api._generate_dashboard_html())
                
                elif self.path == '/status':
                    state = api._last_state
                    comparison = api.comparator.get_status()
                    
                    # RL Reifegrad berechnen
                    rl_maturity = api._calculate_rl_maturity(comparison)
                    
                    self._send_json({
                        "timestamp": datetime.now().isoformat(),
                        "version": "2.2.0",
                        
                        # ===== RL REIFEGRAD (NEU) =====
                        "rl_maturity": rl_maturity,
                        
                        # ===== AKTUELLER ZUSTAND =====
                        "current": {
                            "battery_soc": state.battery_soc if state else None,
                            "ev_connected": state.ev_connected if state else None,
                            "ev_name": state.ev_name if state else None,
                            "ev_soc": state.ev_soc if state else None,
                            "ev_capacity_kwh": state.ev_capacity_kwh if state else None,
                            "ev_charge_power_kw": state.ev_charge_power_kw if state else None,
                            "price_ct": round(state.current_price * 100, 1) if state else None,
                            "pv_w": state.pv_power if state else None,
                            "home_w": state.home_power if state else None,
                        } if state else None,
                        
                        # ===== AKTIVE LIMITS =====
                        "active_limits": {
                            "battery_ct": round(api._last_lp_action.battery_limit_eur * 100, 1) if api._last_lp_action and api._last_lp_action.battery_limit_eur else None,
                            "ev_ct": round(api._last_lp_action.ev_limit_eur * 100, 1) if api._last_lp_action and api._last_lp_action.ev_limit_eur else None,
                        },
                        
                        # ===== RL DETAILS =====
                        "rl": {
                            "enabled": api.cfg.rl_enabled,
                            "epsilon": round(api.rl.epsilon, 4),
                            "total_steps": api.rl.total_steps,
                            "memory_size": len(api.rl.memory),
                            "q_table_states": len(api.rl.q_table),
                            "comparisons": comparison.get("comparisons", 0),
                            "win_rate": round(comparison.get("win_rate", 0) * 100, 1),
                            "ready": comparison.get("rl_ready", False),
                            "ready_threshold": api.cfg.rl_ready_threshold * 100,
                            "ready_min_comparisons": api.cfg.rl_ready_min_comparisons,
                        },
                        
                        # ===== KOSTEN =====
                        "costs": {
                            "optimizer_total_eur": round(comparison.get("lp_total_cost", 0), 2),
                            "rl_simulated_eur": round(comparison.get("rl_total_cost", 0), 2),
                            "rl_would_save_eur": round(comparison.get("lp_total_cost", 0) - comparison.get("rl_total_cost", 0), 2),
                        },
                        
                        # ===== CONFIG =====
                        "config": {
                            "battery_max_ct": api.cfg.battery_max_price_ct,
                            "ev_max_ct": api.cfg.ev_max_price_ct,
                            "ev_deadline": f"{api.cfg.ev_charge_deadline_hour}:00",
                        }
                    })
                
                elif self.path == '/summary':
                    # Kurzübersicht für schnellen Check
                    comparison = api.comparator.get_status()
                    rl_maturity = api._calculate_rl_maturity(comparison)
                    state = api._last_state
                    
                    self._send_json({
                        "rl_ready": comparison.get("rl_ready", False),
                        "rl_maturity_percent": rl_maturity["percent"],
                        "rl_maturity_status": rl_maturity["status"],
                        "comparisons": comparison.get("comparisons", 0),
                        "win_rate_percent": round(comparison.get("win_rate", 0) * 100, 1),
                        "battery_soc": state.battery_soc if state else None,
                        "ev_soc": state.ev_soc if state else None,
                        "current_price_ct": round(state.current_price * 100, 1) if state else None,
                        "battery_limit_ct": round(api._last_lp_action.battery_limit_eur * 100, 1) if api._last_lp_action and api._last_lp_action.battery_limit_eur else None,
                        "ev_limit_ct": round(api._last_lp_action.ev_limit_eur * 100, 1) if api._last_lp_action and api._last_lp_action.ev_limit_eur else None,
                    })
                
                elif self.path == '/comparisons':
                    self._send_json({
                        "recent": api.comparator.comparisons[-50:],
                        "summary": api.comparator.get_status()
                    })
                
                elif self.path == '/config':
                    self._send_json({
                        "battery_capacity_kwh": api.cfg.battery_capacity_kwh,
                        "battery_charge_power_kw": api.cfg.battery_charge_power_kw,
                        "battery_max_price_ct": api.cfg.battery_max_price_ct,
                        "battery_price_corridor_ct": api.cfg.battery_price_corridor_ct,
                        "ev_max_price_ct": api.cfg.ev_max_price_ct,
                        "ev_price_corridor_ct": api.cfg.ev_price_corridor_ct,
                        "ev_charge_deadline_hour": api.cfg.ev_charge_deadline_hour,
                        "decision_interval_minutes": api.cfg.decision_interval_minutes,
                        "rl_ready_threshold": api.cfg.rl_ready_threshold,
                        "rl_ready_min_comparisons": api.cfg.rl_ready_min_comparisons,
                    })
                
                elif self.path == '/vehicles':
                    # Alle Fahrzeuge (auch nicht verbundene!)
                    vehicles = api.vehicle_monitor.get_all_vehicles()
                    charge_needs = api.vehicle_monitor.predict_charge_need()
                    
                    self._send_json({
                        "timestamp": datetime.now().isoformat(),
                        "vehicles": {
                            name: {
                                "soc": v.soc,
                                "capacity_kwh": v.capacity_kwh,
                                "range_km": v.range_km,
                                "connected": v.connected_to_wallbox,
                                "charging": v.charging,
                                "charge_needed_kwh": charge_needs.get(name, 0),
                                "last_update": v.last_update.isoformat()
                            }
                            for name, v in vehicles.items()
                        },
                        "total_charge_needed_kwh": sum(charge_needs.values()),
                        "poll_interval_minutes": api.vehicle_monitor.poll_interval_minutes
                    })
                
                elif self.path == '/slots':
                    # Detaillierte Ladeslots für alle Geräte
                    tariffs = api.collector.evcc.get_tariff_grid() if api.collector else []
                    charge_slots = api._calculate_charge_slots(tariffs) if tariffs else {"error": "Keine Tarife"}
                    self._send_json(charge_slots)
                
                elif self.path == '/rl-devices':
                    # RL Device Control Status (v3.0)
                    devices = api.rl_devices.get_all_devices()
                    self._send_json({
                        "timestamp": datetime.now().isoformat(),
                        "devices": devices,
                        "global_config": {
                            "auto_switch_enabled": api.cfg.rl_auto_switch,
                            "ready_threshold": api.cfg.rl_ready_threshold,
                            "fallback_threshold": api.cfg.rl_fallback_threshold,
                            "min_comparisons": api.cfg.rl_ready_min_comparisons
                        }
                    })
                
                elif self.path == '/docs':
                    # Dokumentations-Viewer
                    self._send_html(api._generate_docs_html())
                
                elif self.path == '/docs/readme':
                    # README als HTML
                    self._send_html(api._generate_markdown_viewer("README.md"))
                
                elif self.path == '/docs/changelog':
                    # Changelog
                    self._send_html(api._generate_markdown_viewer("CHANGELOG_v3.0.0.md"))
                
                elif self.path == '/docs/api':
                    # API Dokumentation
                    self._send_html(api._generate_api_docs_html())
                
                else:
                    self._send_json({"error": "not found", "endpoints": [
                        "/", "/health", "/status", "/summary", "/comparisons", "/config", 
                        "/vehicles", "/slots", "/rl-devices", "/docs"
                    ]}, 404)
            
            def do_POST(self):
                if self.path == '/save':
                    api.rl.save()
                    api.comparator.save()
                    self._send_json({"status": "saved"})
                
                elif self.path == '/rl-override':
                    # Manual RL Mode Override (v3.0)
                    try:
                        length = int(self.headers.get('Content-Length', 0))
                        body = json.loads(self.rfile.read(length).decode())
                        
                        device = body.get('device')
                        mode = body.get('mode')  # manual_lp, manual_rl, auto
                        
                        if not device or not mode:
                            self._send_json({"error": "Missing device or mode"}, 400)
                            return
                        
                        result = api.rl_devices.set_override(device, mode)
                        self._send_json(result)
                    except Exception as e:
                        self._send_json({"error": str(e)}, 500)
                
                else:
                    self._send_json({"error": "not found"}, 404)
        
        def run_server():
            server = HTTPServer(('0.0.0.0', self.cfg.api_port), Handler)
            _log("info", f"API server running on http://0.0.0.0:{self.cfg.api_port}")
            _log("info", f"  Endpoints: /health, /status, /comparisons, /config")
            server.serve_forever()
        
        threading.Thread(target=run_server, daemon=True).start()


# =============================================================================
# MAIN LOOP
# =============================================================================

def main():
    _log("info", "=" * 70)
    _log("info", f"  EVCC-Smartload v{VERSION} - Hybrid LP + Shadow RL")
    _log("info", "=" * 70)
    _log("info", "  LP Optimizer:  PRODUCTION (steuert evcc)")
    _log("info", "  Shadow RL:     LEARNING (beobachtet, vergleicht)")
    _log("info", "  Pro-Device RL: Jedes Gerät hat eigenen Agent")
    _log("info", "=" * 70)
    
    cfg = load_config()
    
    _log("info", f"Config: Battery max={cfg.battery_max_price_ct}ct, corridor={cfg.battery_price_corridor_ct}ct")
    _log("info", f"Config: EV max={cfg.ev_max_price_ct}ct, corridor={cfg.ev_price_corridor_ct}ct")
    _log("info", f"Config: RL Auto-Switch={cfg.rl_auto_switch}, Threshold={cfg.rl_ready_threshold*100}%")
    
    # Initialize components
    evcc = EvccClient(cfg)
    influx = InfluxDBClient(cfg)
    
    collector = DataCollector(evcc, influx, cfg)
    optimizer = HolisticOptimizer(cfg)
    rl_agent = DQNAgent(cfg)
    event_detector = EventDetector()
    comparator = Comparator(cfg)
    controller = Controller(evcc, cfg)
    vehicle_monitor = VehicleMonitor(evcc, cfg)
    rl_device_controller = RLDeviceController(cfg)  # NEU in v2.6.8
    
    # RL: Versuche Modell zu laden, sonst Bootstrap aus InfluxDB
    model_loaded = rl_agent.load()
    if not model_loaded:
        # Kein gespeichertes Modell → Bootstrap aus historischen Daten
        bootstrapped = rl_agent.bootstrap_from_influxdb(influx, hours=168)  # 1 Woche
        if bootstrapped > 0:
            rl_agent.save()  # Speichere gebootstrapptes Modell
    
    # Start background services
    collector.start_background_collection()
    vehicle_monitor.start_polling()
    
    # Start API with reference to all components
    api_server = SimpleAPIServer(cfg, optimizer, rl_agent, comparator, event_detector, collector, vehicle_monitor, rl_device_controller)
    api_server.start()
    
    # Persistent state für RL-Learning (überlebt Fehler im Loop)
    last_state: Optional[SystemState] = None
    last_rl_action: Optional[Action] = None
    last_lp_action: Optional[Action] = None
    learning_step_count = 0
    
    _log("info", "Starting main decision loop...")
    
    while True:
        try:
            # Get current state
            state = collector.get_current_state()
            if not state:
                _log("warning", "Could not get system state")
                time.sleep(60)
                continue
            
            # Detect events
            events = event_detector.detect(state)
            if events:
                _log("info", f"Events detected: {events}")
            
            # Check for externally charged vehicles (from VehicleMonitor)
            for name, vehicle in vehicle_monitor.get_all_vehicles().items():
                if not vehicle.connected_to_wallbox and vehicle.soc > 20:
                    # Fahrzeug hat SoC > 20% aber ist nicht an Wallbox
                    # Könnte extern geladen worden sein
                    pass  # Event wird bereits vom VehicleMonitor geloggt
            
            # Get tariffs for LP
            tariffs = evcc.get_tariff_grid()
            
            # === LP DECISION (PRODUCTION) ===
            lp_action = optimizer.optimize(state, tariffs)
            
            # === RL DECISION (SHADOW) ===
            rl_action = rl_agent.select_action(state, explore=True)
            
            # === UPDATE API STATE ===
            api_server.update_state(state, lp_action, rl_action)
            
            # === IMITATION LEARNING ===
            rl_agent.imitation_learn(state, lp_action)
            
            # === PRO-DEVICE MODE SELECTION (v3.0) ===
            # Bestimme welcher Mode für welches Gerät
            battery_mode = rl_device_controller.get_device_mode("battery")
            ev_mode = "lp"  # Default
            if state.ev_connected and state.ev_name:
                ev_mode = rl_device_controller.get_device_mode(state.ev_name)
            
            # Erstelle finale Action basierend auf Device Modes
            final_action = Action(
                battery_action=rl_action.battery_action if battery_mode == "rl" else lp_action.battery_action,
                battery_limit_eur=rl_action.battery_limit_eur if battery_mode == "rl" else lp_action.battery_limit_eur,
                ev_action=rl_action.ev_action if ev_mode == "rl" else lp_action.ev_action,
                ev_limit_eur=rl_action.ev_limit_eur if ev_mode == "rl" else lp_action.ev_limit_eur
            )
            
            # Log welcher Mode aktiv ist
            battery_icon = "🟢" if battery_mode == "rl" else "🔵"
            ev_icon = "🟢" if ev_mode == "rl" else "🔵"
            _log("debug", f"Modes: Battery={battery_icon}{battery_mode.upper()} | EV={ev_icon}{ev_mode.upper()}")
            
            # === APPLY FINAL ACTION ===
            actual_cost = controller.apply(final_action)
            
            # === RL LEARNING (FIXED!) ===
            if last_state is not None and last_rl_action is not None:
                # Calculate reward for RL
                reward = comparator.calculate_reward(last_state, last_rl_action, state, events)
                
                # Event-based priority for replay
                priority = 2.0 if events else 1.0
                
                # RL learns from experience
                rl_agent.learn(last_state, last_rl_action, reward, state, False, priority)
                learning_step_count += 1
                
                if learning_step_count % 50 == 0:
                    _log("info", f"RL Learning: {learning_step_count} steps, "
                                f"memory={len(rl_agent.memory)}, "
                                f"ε={rl_agent.epsilon:.3f}")
            
            # === COMPARISON ===
            comparator.compare(state, lp_action, rl_action, actual_cost)
            
            # === PRO-DEVICE COMPARISON (v3.0) ===
            comparator.compare_per_device(state, lp_action, rl_action, actual_cost, rl_device_controller)
            
            # Store for next iteration (WICHTIG für Learning!)
            last_state = state
            last_rl_action = rl_action
            last_lp_action = lp_action
            
            # Log
            lp_bat_limit = f"{lp_action.battery_limit_eur*100:.1f}ct" if lp_action.battery_limit_eur else "none"
            lp_ev_limit = f"{lp_action.ev_limit_eur*100:.1f}ct" if lp_action.ev_limit_eur else "none"
            _log("info", 
                f"LP: bat={lp_action.battery_action}({lp_bat_limit}) ev={lp_action.ev_action}({lp_ev_limit}) | "
                f"RL: bat={rl_action.battery_action} ev={rl_action.ev_action} | "
                f"price={state.current_price*100:.1f}ct | "
                f"ε={rl_agent.epsilon:.3f}")
            
            # Save periodically
            if rl_agent.total_steps % 50 == 0 and rl_agent.total_steps > 0:
                rl_agent.save()
                comparator.save()
                _log("debug", f"Saved RL model and comparisons")
            
            # Wait for next decision interval
            time.sleep(cfg.decision_interval_minutes * 60)
            
        except Exception as e:
            _log("error", f"Main loop error: {e}")
            import traceback
            traceback.print_exc()
            # WICHTIG: last_state etc. bleiben erhalten!
            time.sleep(60)


if __name__ == "__main__":
    main()
