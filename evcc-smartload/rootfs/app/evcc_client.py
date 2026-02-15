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
        self._login()
        try:
            r = self.sess.get(f"{self.base_url}/api/tariff/grid", timeout=15)
            if r.status_code != 200:
                log("warning", f"Tariff API returned {r.status_code}")
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

            log("debug", f"Found {len(rates)} tariff rates")
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
