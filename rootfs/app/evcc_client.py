"""
evcc REST API client — v5.0 (unchanged from v4.3.11)

Handles authentication and all communication with evcc
via its REST API. All methods required by v5 (limitSoc,
loadpoint mode/targetsoc) were already present in v4.
"""

from typing import Dict, List, Optional

import requests

from config import Config
from logging_util import log


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
            r = self.sess.post(
                f"{self.base_url}/api/auth/login",
                json={"password": self.password},
                timeout=10,
            )
            self._logged_in = r.status_code == 200
        except Exception:
            pass

    def get_state(self) -> Optional[Dict]:
        self._login()
        try:
            r = self.sess.get(f"{self.base_url}/api/state", timeout=15)
            data = r.json()
            return data.get("result", data)
        except Exception:
            return None

    def get_current_tariff(self) -> Optional[float]:
        """Return the current grid price in EUR/kWh (first rate in the tariff list)."""
        from datetime import datetime, timezone
        rates = self.get_tariff_grid()
        if not rates:
            return None
        now = datetime.now(timezone.utc)
        # Find the rate slot covering right now
        for rate in rates:
            start = rate.get("start") or rate.get("startsAt") or ""
            end = rate.get("end") or rate.get("endsAt") or ""
            price = rate.get("price") or rate.get("value")
            if price is None:
                continue
            try:
                from datetime import datetime as dt
                import re as _re
                # ISO8601 parse (basic)
                ts = dt.fromisoformat(start.replace("Z", "+00:00")) if start else None
                te = dt.fromisoformat(end.replace("Z", "+00:00")) if end else None
                if ts and te and ts <= now < te:
                    return float(price)
            except Exception:
                pass
        # Fallback: return price of first rate
        first = rates[0]
        price = first.get("price") or first.get("value")
        return float(price) if price is not None else None

    def get_tariff_grid(self) -> List[Dict]:
        return self._get_tariff("grid")

    def get_tariff_solar(self) -> List[Dict]:
        return self._get_tariff("solar")

    def _get_tariff(self, kind: str) -> List[Dict]:
        self._login()
        try:
            r = self.sess.get(f"{self.base_url}/api/tariff/{kind}", timeout=15)
            if r.status_code != 200:
                log("warning", f"Tariff {kind} API returned {r.status_code}")
                return []
            data = r.json()
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

    def set_battery_grid_charge_limit(self, eur_per_kwh: float) -> bool:
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/batterygridchargelimit/{eur_per_kwh:.4f}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ Battery grid charge limit → {eur_per_kwh * 100:.1f} ct/kWh")
                return True
            log("warning", f"✗ Battery limit: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ Battery limit: {e}")
            return False

    def clear_battery_grid_charge_limit(self) -> bool:
        self._login()
        try:
            r = self.sess.delete(f"{self.base_url}/api/batterygridchargelimit", timeout=10)
            return r.status_code in [200, 204]
        except Exception as e:
            log("error", f"✗ Clear battery limit: {e}")
            return False

    def set_smart_cost_limit(self, eur_per_kwh: float) -> bool:
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/smartcostlimit/{eur_per_kwh:.4f}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ EV smart cost limit → {eur_per_kwh * 100:.1f} ct/kWh")
                return True
            log("warning", f"✗ EV limit: {r.status_code}")
            return False
        except Exception as e:
            log("error", f"✗ EV limit: {e}")
            return False

    def set_battery_mode(self, mode: str) -> bool:
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/batterymode/{mode}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ Battery mode → '{mode}'")
                return True
            return False
        except Exception as e:
            log("error", f"✗ Battery mode: {e}")
            return False

    def set_battery_discharge_control(self, enabled: bool) -> bool:
        self._login()
        try:
            val = "true" if enabled else "false"
            r = self.sess.post(f"{self.base_url}/api/batterydischargecontrol/{val}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ Battery discharge control: {val}")
                return True
            return False
        except Exception as e:
            log("error", f"✗ Discharge control: {e}")
            return False

    def set_loadpoint_mode(self, lp_id: int, mode: str) -> bool:
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/loadpoints/{lp_id}/mode/{mode}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ Loadpoint {lp_id} mode → '{mode}'")
                return True
            return False
        except Exception as e:
            log("error", f"✗ Loadpoint mode: {e}")
            return False

    def set_loadpoint_minsoc(self, lp_id: int, soc: int) -> bool:
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/loadpoints/{lp_id}/minsoc/{soc}", timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    def set_loadpoint_targetsoc(self, lp_id: int, soc: int) -> bool:
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/loadpoints/{lp_id}/targetsoc/{soc}", timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    def set_buffer_soc(self, soc: int) -> bool:
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/buffersoc/{soc}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ bufferSoc → {soc}%")
                return True
            return False
        except Exception as e:
            log("error", f"✗ bufferSoc: {e}")
            return False

    def set_buffer_start_soc(self, soc: int) -> bool:
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/bufferstartsoc/{soc}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ bufferStartSoc → {soc}%")
                return True
            return False
        except Exception as e:
            log("error", f"✗ bufferStartSoc: {e}")
            return False

    def set_priority_soc(self, soc: int) -> bool:
        self._login()
        try:
            r = self.sess.post(f"{self.base_url}/api/prioritysoc/{soc}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ prioritySoc → {soc}%")
                return True
            return False
        except Exception as e:
            log("error", f"✗ prioritySoc: {e}")
            return False

    def set_battery_boost(self, lp_id: int, enabled: bool) -> bool:
        self._login()
        try:
            val = "true" if enabled else "false"
            r = self.sess.post(f"{self.base_url}/api/loadpoints/{lp_id}/batteryboost/{val}", timeout=10)
            if r.status_code == 200:
                log("info", f"✓ Battery boost LP{lp_id}: {val}")
                return True
            return False
        except Exception as e:
            log("error", f"✗ Battery boost: {e}")
            return False
