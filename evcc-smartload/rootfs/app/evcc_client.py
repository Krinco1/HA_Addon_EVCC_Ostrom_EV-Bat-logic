"""
evcc REST API client.

Handles authentication and all communication with evcc
(Electric Vehicle Charge Controller) via its REST API.
"""

from typing import Dict, List, Optional

import requests

from config import Config
from logging_util import log


class EvccClient:
    """Thin wrapper around the evcc REST API."""

    def __init__(self, cfg: Config):
        self.base_url = cfg.evcc_url.rstrip("/")
        self.password = cfg.evcc_password
        self.sess = requests.Session()
        self._logged_in = False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _login(self) -> None:
        if self._logged_in or not self.password:
            return
        try:
            r = self.sess.post(
                f"{self.base_url}/api/auth/login",
                json={"password": self.password},
                timeout=10,
            )
            self._logged_in = r.status_code == 200
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Read state
    # ------------------------------------------------------------------

    def get_state(self) -> Optional[Dict]:
        """Fetch full evcc system state."""
        self._login()
        try:
            r = self.sess.get(f"{self.base_url}/api/state", timeout=15)
            data = r.json()
            return data.get("result", data)
        except Exception:
            return None

    def get_tariff_grid(self) -> List[Dict]:
        """Fetch grid tariff rates from evcc."""
        return self._get_tariff("grid")

    def get_tariff_solar(self) -> List[Dict]:
        """Fetch solar/PV forecast from evcc (kWh per slot)."""
        return self._get_tariff("solar")

    def _get_tariff(self, kind: str) -> List[Dict]:
        """Fetch tariff data from evcc. kind = 'grid' or 'solar'."""
        self._login()
        try:
            r = self.sess.get(f"{self.base_url}/api/tariff/{kind}", timeout=15)
            if r.status_code != 200:
                log("warning", f"Tariff {kind} API returned {r.status_code}")
                return []

            data = r.json()

            # evcc returns varying shapes – normalise to a flat list of rate dicts
            if isinstance(data, dict):
                result = data.get("result", data)
                if isinstance(result, dict) and "rates" in result:
                    rates = result["rates"]
                elif isinstance(result, list):
                    rates = result
                elif "rates" in data:
                    rates = data["rates"]
                else:
                    rates = []
            elif isinstance(data, list):
                rates = data
            else:
                rates = []

            log("debug", f"Found {len(rates)} {kind} tariff rates")
            return rates
        except Exception as e:
            log("error", f"Failed to get tariffs: {e}")
            return []

    # ------------------------------------------------------------------
    # Battery control
    # ------------------------------------------------------------------

    def set_battery_grid_charge_limit(self, eur_per_kwh: float) -> bool:
        """Set battery grid-charge price limit (EUR/kWh)."""
        self._login()
        try:
            url = f"{self.base_url}/api/batterygridchargelimit/{eur_per_kwh:.4f}"
            r = self.sess.post(url, timeout=10)
            if r.status_code == 200:
                log("info", f"✓ Battery grid charge limit set to {eur_per_kwh * 100:.1f} ct/kWh")
                return True
            log("warning", f"✗ Failed to set battery limit: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ Exception setting battery limit: {e}")
            return False

    def clear_battery_grid_charge_limit(self) -> bool:
        """Remove battery grid-charge price limit."""
        self._login()
        try:
            r = self.sess.delete(f"{self.base_url}/api/batterygridchargelimit", timeout=10)
            return r.status_code in [200, 204]
        except Exception as e:
            log("error", f"✗ Exception clearing battery limit: {e}")
            return False

    # ------------------------------------------------------------------
    # EV / smart cost control
    # ------------------------------------------------------------------

    def set_smart_cost_limit(self, eur_per_kwh: float) -> bool:
        """Set smart cost limit for EV charging (EUR/kWh)."""
        self._login()
        try:
            url = f"{self.base_url}/api/smartcostlimit/{eur_per_kwh:.4f}"
            r = self.sess.post(url, timeout=10)
            if r.status_code == 200:
                log("info", f"✓ EV smart cost limit set to {eur_per_kwh * 100:.1f} ct/kWh")
                return True
            log("warning", f"✗ Failed to set EV limit: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ Exception setting EV limit: {e}")
            return False

    # ------------------------------------------------------------------
    # Battery mode control
    # ------------------------------------------------------------------

    def set_battery_mode(self, mode: str) -> bool:
        """Set battery mode: 'normal', 'hold', 'charge'."""
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/batterymode/{mode}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ Battery mode set to '{mode}'")
                return True
            log("warning", f"✗ Failed to set battery mode: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ Battery mode error: {e}")
            return False

    def set_battery_discharge_control(self, enabled: bool) -> bool:
        """Enable/disable battery discharge control."""
        self._login()
        try:
            val = "true" if enabled else "false"
            r = self.sess.post(f"{self.base_url}/api/batterydischargecontrol/{val}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ Battery discharge control: {val}")
                return True
            log("warning", f"✗ Failed to set discharge control: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ Discharge control error: {e}")
            return False

    # ------------------------------------------------------------------
    # Loadpoint control
    # ------------------------------------------------------------------

    def set_loadpoint_mode(self, lp_id: int, mode: str) -> bool:
        """Set loadpoint charging mode: 'off', 'now', 'minpv', 'pv'."""
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/loadpoints/{lp_id}/mode/{mode}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ Loadpoint {lp_id} mode set to '{mode}'")
                return True
            log("warning", f"✗ Failed to set loadpoint mode: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ Loadpoint mode error: {e}")
            return False

    def set_loadpoint_minsoc(self, lp_id: int, soc: int) -> bool:
        """Set loadpoint minimum SoC %."""
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/loadpoints/{lp_id}/minsoc/{soc}", timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    def set_loadpoint_targetsoc(self, lp_id: int, soc: int) -> bool:
        """Set loadpoint target SoC %."""
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/loadpoints/{lp_id}/targetsoc/{soc}", timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Battery buffer / priority SoC (dynamic discharge limits)
    # ------------------------------------------------------------------

    def set_buffer_soc(self, soc: int) -> bool:
        """Set bufferSoc: above this SoC, battery may power the EV (PV mode)."""
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/buffersoc/{soc}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ bufferSoc set to {soc}%")
                return True
            log("warning", f"✗ Failed to set bufferSoc: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ bufferSoc error: {e}")
            return False

    def set_buffer_start_soc(self, soc: int) -> bool:
        """Set bufferStartSoc: above this SoC, EV charging may start without PV surplus."""
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/bufferstartsoc/{soc}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ bufferStartSoc set to {soc}%")
                return True
            log("warning", f"✗ Failed to set bufferStartSoc: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ bufferStartSoc error: {e}")
            return False

    def set_priority_soc(self, soc: int) -> bool:
        """Set prioritySoc: below this SoC, battery has priority over EV charging."""
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/prioritysoc/{soc}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ prioritySoc set to {soc}%")
                return True
            log("warning", f"✗ Failed to set prioritySoc: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ prioritySoc error: {e}")
            return False

    def set_battery_boost(self, lp_id: int, enabled: bool) -> bool:
        """Enable/disable battery boost on loadpoint (charge with PV + max battery)."""
        self._login()
        try:
            val = "true" if enabled else "false"
            r = self.sess.post(f"{self.base_url}/api/loadpoints/{lp_id}/batteryboost/{val}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ Battery boost LP{lp_id}: {val}")
                return True
            log("warning", f"✗ Battery boost failed: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ Battery boost error: {e}")
            return False
