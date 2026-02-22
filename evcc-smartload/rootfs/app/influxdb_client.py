"""
InfluxDB 1.x client for EVCC-Smartload.

Writes energy metrics to InfluxDB for historical analysis.

v5.0.2: Added SSL support (influxdb_ssl config option).
        Handles self-signed certificates on local networks.
"""

from datetime import datetime, timezone
from typing import Optional

from logging_util import log


class InfluxDBClient:
    """Simple InfluxDB v1 HTTP writer."""

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

        if self._enabled:
            log("info", f"InfluxDB: {self._base_url} (SSL={'on' if self._ssl else 'off'})")

    def _get_ssl_context(self):
        """Create SSL context that accepts self-signed certificates (local network)."""
        if not self._ssl:
            return None
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _auth_params(self) -> str:
        """Return URL query string for InfluxDB authentication."""
        if not self.username:
            return ""
        import urllib.parse
        return f"&u={urllib.parse.quote(self.username)}&p={urllib.parse.quote(self.password)}"

    def write(self, measurement: str, fields: dict, tags: dict = None):
        """Write a data point to InfluxDB."""
        if not self._enabled:
            return
        try:
            import urllib.request
            import urllib.parse

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
            url = (f"{self._base_url}/write"
                   f"?db={urllib.parse.quote(self.database)}"
                   f"&precision=s{self._auth_params()}")

            req = urllib.request.Request(
                url,
                data=line.encode(),
                method="POST",
            )

            ssl_ctx = self._get_ssl_context()
            with urllib.request.urlopen(req, timeout=5, context=ssl_ctx) as resp:
                if resp.status not in (200, 204):
                    log("warning", f"InfluxDB write returned {resp.status}")

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

        self.write("smartload_state", fields)

    def get_history_hours(self, hours: int = 24) -> list:
        """Return recent state history from InfluxDB (for RL bootstrap).
        Returns list of dicts with price_ct, battery_soc, pv_power fields."""
        if not self._enabled:
            return []
        try:
            import urllib.request, urllib.parse, json as _json
            query = (f"SELECT mean(price_ct), mean(battery_soc), mean(pv_power) "
                     f"FROM smartload_state "
                     f"WHERE time > now() - {hours}h "
                     f"GROUP BY time(1h) fill(none)")
            url = (f"{self._base_url}/query"
                   f"?db={urllib.parse.quote(self.database)}"
                   f"&q={urllib.parse.quote(query)}"
                   f"{self._auth_params()}")
            req = urllib.request.Request(url)
            ssl_ctx = self._get_ssl_context()
            with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
                data = _json.loads(resp.read())
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
