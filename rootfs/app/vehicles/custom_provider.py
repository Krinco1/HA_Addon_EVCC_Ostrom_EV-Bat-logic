"""
Custom Vehicle Provider — v4 unchanged in v5.

Generic HTTP-based SoC provider.
Calls a configurable URL and extracts SoC via a JSON path or regex.

config.yaml example:
  vehicles:
    - name: my_car
      type: custom
      url: "http://192.168.1.100/api/battery"
      soc_path: "battery.soc"     # dot-notation JSON path
      capacity_kwh: 60
"""

import json
import re
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from logging_util import log
from vehicles.base import VehicleData


def _json_path(data: dict, path: str):
    """Resolve a dot-notation path in a nested dict."""
    keys = path.split(".")
    cur = data
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur


class CustomProvider:
    """HTTP-based SoC poll for custom vehicle integrations."""

    def __init__(self, config: dict):
        self.evcc_name = config.get("evcc_name") or config.get("name", "custom")
        self.url = config.get("url", "")
        self.soc_path = config.get("soc_path", "soc")
        self.soc_regex = config.get("soc_regex")
        self.capacity_kwh = float(config.get("capacity_kwh", config.get("capacity", 30)))
        self.charge_power_kw = float(config.get("charge_power_kw", 11))
        self.headers = config.get("headers", {})
        log("info", f"CustomProvider: {self.evcc_name} — url={self.url}")

    def poll(self) -> Optional[VehicleData]:
        """Fetch SoC from custom URL."""
        if not self.url:
            return None
        try:
            req = urllib.request.Request(self.url)
            for k, v in self.headers.items():
                req.add_header(k, v)

            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode()

            soc = None
            if self.soc_regex:
                m = re.search(self.soc_regex, body)
                if m:
                    soc = float(m.group(1))
            else:
                try:
                    data = json.loads(body)
                    raw = _json_path(data, self.soc_path)
                    if raw is not None:
                        soc = float(raw)
                except Exception:
                    pass

            if soc is None:
                log("warning", f"CustomProvider {self.evcc_name}: could not extract SoC")
                return None

            v = VehicleData(
                name=self.evcc_name,
                capacity_kwh=self.capacity_kwh,
                charge_power_kw=self.charge_power_kw,
                provider_type="custom",
            )
            v.update_from_api(soc)
            log("debug", f"CustomProvider {self.evcc_name}: SoC={soc:.1f}%")
            return v

        except Exception as e:
            log("warning", f"CustomProvider {self.evcc_name} poll error: {e}")
            return None

    @property
    def supports_active_poll(self) -> bool:
        return bool(self.url)
