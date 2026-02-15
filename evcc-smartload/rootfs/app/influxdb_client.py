"""
InfluxDB client for energy data storage and history retrieval.
"""

from typing import Dict, List

import requests

from config import Config
from logging_util import log


class InfluxDBClient:
    """Simple InfluxDB v1 HTTP client."""

    def __init__(self, cfg: Config):
        self.base_url = f"http://{cfg.influxdb_host}:{cfg.influxdb_port}"
        self.db = cfg.influxdb_database
        self.auth = (cfg.influxdb_username, cfg.influxdb_password)

    def write_batch(self, lines: List[str]) -> bool:
        """Write line-protocol data to InfluxDB."""
        try:
            r = requests.post(
                f"{self.base_url}/write",
                params={"db": self.db, "precision": "ns"},
                auth=self.auth,
                data="\n".join(lines),
                timeout=10,
            )
            return r.status_code == 204
        except Exception as e:
            log("error", f"InfluxDB write failed: {e}")
            return False

    def query(self, q: str) -> List[Dict]:
        """Execute a query and return a flat list of data points."""
        try:
            r = requests.get(
                f"{self.base_url}/query",
                params={"db": self.db, "q": q},
                auth=self.auth,
                timeout=30,
            )
            if r.status_code != 200:
                return []

            data = r.json()
            results = []
            for result in data.get("results", []):
                for series in result.get("series", []):
                    columns = series.get("columns", [])
                    for row in series.get("values", []):
                        results.append(dict(zip(columns, row)))
            return results
        except Exception as e:
            log("error", f"InfluxDB query failed: {e}")
            return []

    def get_history_hours(self, hours: int = 168) -> List[Dict]:
        """Fetch aggregated hourly data for the last *hours* hours."""
        query = f"""
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
        """
        return self.query(query)
