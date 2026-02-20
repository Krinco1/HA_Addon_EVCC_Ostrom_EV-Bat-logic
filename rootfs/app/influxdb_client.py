"""
InfluxDB 1.x client for EVCC-Smartload.

Writes energy metrics to InfluxDB for historical analysis.
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
        self._base_url = f"http://{self.host}:{self.port}"

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
            url = f"{self._base_url}/write?db={urllib.parse.quote(self.database)}&precision=s"

            req = urllib.request.Request(
                url,
                data=line.encode(),
                method="POST",
            )
            if self.username:
                import base64
                cred = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
                req.add_header("Authorization", f"Basic {cred}")

            with urllib.request.urlopen(req, timeout=5) as resp:
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
