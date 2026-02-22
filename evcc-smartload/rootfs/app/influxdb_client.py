"""
InfluxDB 1.x client for EVCC-Smartload.

Writes energy metrics to InfluxDB for historical analysis.
Uses the requests library for reliable HTTPS + auth handling.
"""

import requests
import urllib3

from logging_util import log

# Suppress InsecureRequestWarning for self-signed certs on local network
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class InfluxDBClient:
    """Simple InfluxDB v1 HTTP writer using requests."""

    def __init__(self, cfg):
        self.host = cfg.influxdb_host
        self.port = cfg.influxdb_port
        self.database = cfg.influxdb_database
        self.username = cfg.influxdb_username
        self.password = cfg.influxdb_password
        self._enabled = bool(self.host)
        self._ssl = getattr(cfg, "influxdb_ssl", False)
        scheme = "https" if self._ssl else "http"
        self._base_url = f"{scheme}://{self.host}:{self.port}"
        # For self-signed certs on local network: don't verify
        self._verify = False if self._ssl else True
        self._auth = (self.username, self.password) if self.username else None

        if self._enabled:
            log("info", f"InfluxDB: {self._base_url} "
                        f"(SSL={'on' if self._ssl else 'off'}, "
                        f"user={self.username or 'none'})")

    def write(self, measurement: str, fields: dict, tags: dict = None):
        """Write a data point to InfluxDB."""
        if not self._enabled:
            return
        try:
            tag_str = ""
            if tags:
                tag_str = "," + ",".join(f"{k}={v}" for k, v in tags.items())

            field_str = ",".join(
                f"{k}={v}i" if isinstance(v, int) else
                f'{k}="{v}"' if isinstance(v, str) else
                f"{k}={v}"
                for k, v in fields.items()
            )

            line = f"{measurement}{tag_str} {field_str}"

            resp = requests.post(
                f"{self._base_url}/write",
                params={"db": self.database, "precision": "s"},
                data=line.encode(),
                auth=self._auth,
                verify=self._verify,
                timeout=5,
            )

            if resp.status_code == 401:
                log("warning", f"InfluxDB auth failed (401) — check username/password "
                               f"for {self._base_url}")
            elif resp.status_code not in (200, 204):
                log("warning", f"InfluxDB write returned {resp.status_code}: "
                               f"{resp.text[:200]}")

        except requests.exceptions.ConnectionError as e:
            log("warning", f"InfluxDB connection error: {e}")
        except Exception as e:
            log("warning", f"InfluxDB write error: {e}")

    def write_state(self, state, action=None):
        """Write system state snapshot to InfluxDB."""
        if not self._enabled or not state:
            return

        fields = {
            "battery_soc": float(state.battery_soc),
            "battery_power": float(state.battery_power),
            "pv_power": float(state.pv_power),
            "home_power": float(state.home_power),
            "grid_power": float(state.grid_power),
            "price_ct": round(state.current_price * 100, 2),
        }

        if state.ev_connected:
            fields["ev_soc"] = float(state.ev_soc or 0)

        if state.price_percentiles:
            for pct, val in state.price_percentiles.items():
                fields[f"p{pct}_ct"] = round(val * 100, 2)

        if action:
            fields["battery_action"] = int(action.battery_action)
            fields["ev_action"] = int(action.ev_action)

        self.write("Smartprice", fields)

    def get_history_hours(self, hours: int = 24) -> list:
        """Return recent state history from InfluxDB (for RL bootstrap).
        Returns list of dicts with price_ct, battery_soc, pv_power fields."""
        if not self._enabled:
            return []
        try:
            query = (f"SELECT mean(price_ct), mean(battery_soc), mean(pv_power) "
                     f"FROM Smartprice "
                     f"WHERE time > now() - {hours}h "
                     f"GROUP BY time(1h) fill(none)")

            resp = requests.get(
                f"{self._base_url}/query",
                params={"db": self.database, "q": query},
                auth=self._auth,
                verify=self._verify,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for series in data.get("results", [{}])[0].get("series", []):
                for row in series.get("values", []):
                    if row[1] is not None:
                        results.append({
                            "price_ct": row[1],
                            "battery_soc": row[2] or 0,
                            "pv_power": row[3] or 0,
                        })
            return results
        except Exception as e:
            log("warning", f"InfluxDB get_history_hours error: {e}")
            return []
