"""
PlanSnapshotter — Phase 6 (TRAN-04): Plan vs. Actual comparison storage.

Writes a slot-0 plan snapshot each decision cycle to InfluxDB measurement
'smartload_plan_snapshot', and queries the stored data for the /history endpoint.

Design principles:
- write_snapshot() never raises — all errors are caught and logged as warnings
- query_comparison() returns [] on any failure or when InfluxDB is disabled
- Both methods are no-ops when InfluxDB is not configured (_enabled is False)
"""

import requests
from logging_util import log


class PlanSnapshotter:
    """Stores plan snapshots and retrieves planned-vs-actual comparisons."""

    def __init__(self, influx_client):
        """Store reference to the shared InfluxDBClient instance."""
        self._influx = influx_client

    def write_snapshot(self, plan, actual_state: dict):
        """Write slot-0 plan data + current actual state to InfluxDB.

        Called each decision cycle AFTER store.update_plan(plan).
        Never raises — all errors are caught as warnings.

        Args:
            plan: PlanHorizon from HorizonPlanner (has .slots, .solver_fun)
            actual_state: dict with keys 'battery_power', 'ev_power', 'current_price'
        """
        if plan is None:
            return
        if not self._influx._enabled:
            return

        try:
            slot0 = plan.slots[0]
            actual_price_eur = actual_state.get("current_price", 0.0) or 0.0

            fields = {
                "planned_bat_charge_kw":    float(slot0.bat_charge_kw),
                "planned_bat_discharge_kw": float(slot0.bat_discharge_kw),
                "planned_ev_charge_kw":     float(slot0.ev_charge_kw),
                "planned_price_ct":         round(slot0.price_eur_kwh * 100, 2),
                "planned_total_cost_eur":   float(plan.solver_fun),
                "actual_bat_power_w":       float(actual_state.get("battery_power", 0.0) or 0.0),
                "actual_ev_power_w":        float(actual_state.get("ev_power", 0.0) or 0.0),
                "actual_price_ct":          round(actual_price_eur * 100, 2),
            }

            self._influx.write(measurement="smartload_plan_snapshot", fields=fields)

        except Exception as e:
            log("warning", f"PlanSnapshotter.write_snapshot failed: {e}")

    def query_comparison(self, hours: int = 24) -> list:
        """Query planned-vs-actual snapshots for the last N hours.

        Returns a list of row dicts with all snapshot fields plus computed
        cost_delta_eur (positive = more expensive than planned, negative = saved).

        Returns [] when InfluxDB is disabled or any error occurs.

        Args:
            hours: Look-back window in hours (24 or 168 for 7-day view).

        Returns:
            List of dicts, ordered ASC by time:
            {
                "time": str (ISO),
                "planned_bat_charge_kw": float,
                "planned_bat_discharge_kw": float,
                "planned_ev_charge_kw": float,
                "planned_price_ct": float,
                "planned_total_cost_eur": float,
                "actual_bat_power_kw": float,  (converted from W)
                "actual_ev_power_kw": float,   (converted from W)
                "actual_price_ct": float,
                "cost_delta_eur": float,        (actual - planned cost, 15-min slot approximation)
            }
        """
        if not self._influx._enabled:
            return []

        try:
            query = (
                "SELECT planned_bat_charge_kw, planned_bat_discharge_kw, "
                "planned_ev_charge_kw, planned_price_ct, planned_total_cost_eur, "
                "actual_bat_power_w, actual_ev_power_w, actual_price_ct "
                "FROM smartload_plan_snapshot "
                "WHERE time > now() - {}h "
                "ORDER BY time ASC"
            ).format(hours)

            resp = requests.get(
                "{}/query".format(self._influx._base_url),
                params={"db": self._influx.database, "q": query},
                auth=self._influx._auth,
                verify=self._influx._verify,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for series in data.get("results", [{}])[0].get("series", []):
                columns = series.get("columns", [])
                for row in series.get("values", []):
                    if row[0] is None:
                        continue
                    row_dict = {}
                    for idx, col in enumerate(columns):
                        row_dict[col] = row[idx]

                    # Convert actual W -> kW for consistent units with planned kW
                    actual_bat_kw = float(row_dict.get("actual_bat_power_w") or 0.0) / 1000.0
                    actual_ev_kw  = float(row_dict.get("actual_ev_power_w") or 0.0) / 1000.0

                    planned_price_ct = float(row_dict.get("planned_price_ct") or 0.0)
                    actual_price_ct  = float(row_dict.get("actual_price_ct") or 0.0)
                    planned_bat_kw   = float(row_dict.get("planned_bat_charge_kw") or 0.0)

                    # Approximate 15-min slot cost difference:
                    # cost = price_ct/100 * kW * 0.25h  (energy = power * time)
                    cost_delta_eur = (actual_price_ct - planned_price_ct) / 100.0 * planned_bat_kw * 0.25

                    results.append({
                        "time":                      row_dict.get("time", ""),
                        "planned_bat_charge_kw":     float(row_dict.get("planned_bat_charge_kw") or 0.0),
                        "planned_bat_discharge_kw":  float(row_dict.get("planned_bat_discharge_kw") or 0.0),
                        "planned_ev_charge_kw":      float(row_dict.get("planned_ev_charge_kw") or 0.0),
                        "planned_price_ct":          planned_price_ct,
                        "planned_total_cost_eur":    float(row_dict.get("planned_total_cost_eur") or 0.0),
                        "actual_bat_power_kw":       round(actual_bat_kw, 3),
                        "actual_ev_power_kw":        round(actual_ev_kw, 3),
                        "actual_price_ct":           actual_price_ct,
                        "cost_delta_eur":            round(cost_delta_eur, 4),
                    })

            return results

        except Exception as e:
            log("warning", f"PlanSnapshotter.query_comparison failed: {e}")
            return []
