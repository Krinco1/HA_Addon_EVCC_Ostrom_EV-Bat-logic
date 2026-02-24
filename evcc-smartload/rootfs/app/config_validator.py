"""
Config validation for EVCC-Smartload.

Validates the Config dataclass and returns a list of ValidationResult items.
Critical errors block startup (optimization loop does not run).
Non-critical warnings use safe defaults with logged messages.

All error messages are in German using plain ASCII to ensure compatibility
with container log pipelines.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class ValidationResult:
    """Describes a single config validation issue."""

    field: str        # Config field name, e.g. "evcc_url"
    value: object     # Actual value found in the config
    severity: str     # "critical" or "warning"
    message: str      # Human-readable German description of the problem
    suggestion: str = ""  # How the user can fix it


class ConfigValidator:
    """Validates a Config object and returns a list of ValidationResult items.

    Uses hasattr() checks before accessing fields that may not exist on the
    current Config shape — the validator must not crash on any Config version.
    """

    def validate(self, cfg) -> List[ValidationResult]:
        """Run all validation rules on cfg and return the results."""
        results: List[ValidationResult] = []

        # --- Critical validations ---
        self._check_evcc_url(cfg, results)
        self._check_soc_bounds(cfg, results)
        self._check_efficiency(cfg, "battery_charge_efficiency", results)
        self._check_efficiency(cfg, "battery_discharge_efficiency", results)
        self._check_battery_capacity(cfg, results)

        # --- Non-critical validations ---
        self._check_max_price(cfg, "battery_max_price_ct", results)
        self._check_max_price(cfg, "ev_max_price_ct", results)
        self._check_ev_target_soc(cfg, results)
        self._check_decision_interval(cfg, results)
        self._check_influxdb_optional(cfg, results)

        return results

    # ------------------------------------------------------------------
    # Critical checks
    # ------------------------------------------------------------------

    def _check_evcc_url(self, cfg, results: List[ValidationResult]) -> None:
        if not hasattr(cfg, "evcc_url"):
            return
        val = cfg.evcc_url
        if not val or not str(val).startswith("http"):
            results.append(ValidationResult(
                field="evcc_url",
                value=val,
                severity="critical",
                message=(
                    "evcc_url muss eine gueltige HTTP-URL sein "
                    "(z.B. http://evcc.local:7070)"
                ),
                suggestion=(
                    "Pruefe die IP-Adresse und Port deines evcc-Servers"
                ),
            ))

    def _check_soc_bounds(self, cfg, results: List[ValidationResult]) -> None:
        if not hasattr(cfg, "battery_min_soc") or not hasattr(cfg, "battery_max_soc"):
            return
        min_soc = cfg.battery_min_soc
        max_soc = cfg.battery_max_soc
        if min_soc >= max_soc:
            results.append(ValidationResult(
                field="battery_min_soc",
                value=min_soc,
                severity="critical",
                message=(
                    f"battery_min_soc ({min_soc}) muss kleiner als "
                    f"battery_max_soc ({max_soc}) sein"
                ),
                suggestion="Setze z.B. battery_min_soc=10, battery_max_soc=90",
            ))

    def _check_efficiency(
        self, cfg, field: str, results: List[ValidationResult]
    ) -> None:
        if not hasattr(cfg, field):
            return
        val = getattr(cfg, field)
        if not isinstance(val, (int, float)) or val <= 0 or val > 1.0:
            results.append(ValidationResult(
                field=field,
                value=val,
                severity="critical",
                message=(
                    f"{field} muss zwischen 0 (exklusiv) und 1.0 liegen, "
                    f"ist aber {val}"
                ),
                suggestion="Typischer Wert: 0.92",
            ))

    def _check_battery_capacity(self, cfg, results: List[ValidationResult]) -> None:
        if not hasattr(cfg, "battery_capacity_kwh"):
            return
        val = cfg.battery_capacity_kwh
        if not isinstance(val, (int, float)) or val <= 0:
            results.append(ValidationResult(
                field="battery_capacity_kwh",
                value=val,
                severity="critical",
                message="battery_capacity_kwh muss groesser als 0 sein",
                suggestion=(
                    "Trage die Bruttokapazitaet deiner Batterie in kWh ein "
                    "(z.B. 33.1)"
                ),
            ))

    # ------------------------------------------------------------------
    # Non-critical checks (warnings only, safe defaults applied by caller)
    # ------------------------------------------------------------------

    def _check_max_price(
        self, cfg, field: str, results: List[ValidationResult]
    ) -> None:
        if not hasattr(cfg, field):
            return
        val = getattr(cfg, field)
        if not isinstance(val, (int, float)) or val <= 0:
            defaults = {
                "battery_max_price_ct": 25.0,
                "ev_max_price_ct": 30.0,
            }
            default = defaults.get(field, 30.0)
            results.append(ValidationResult(
                field=field,
                value=val,
                severity="warning",
                message=(
                    f"{field} ist {val}ct - wird auf sicheren Default "
                    f"gesetzt ({default}ct)"
                ),
                suggestion=(
                    "Typische Werte: battery_max_price_ct=25.0, "
                    "ev_max_price_ct=30.0"
                ),
            ))

    def _check_ev_target_soc(self, cfg, results: List[ValidationResult]) -> None:
        if not hasattr(cfg, "ev_target_soc"):
            return
        val = cfg.ev_target_soc
        if not isinstance(val, (int, float)) or val < 0 or val > 100:
            results.append(ValidationResult(
                field="ev_target_soc",
                value=val,
                severity="warning",
                message=(
                    f"ev_target_soc ({val}) liegt ausserhalb des gueltigen "
                    "Bereichs 0-100%"
                ),
                suggestion="Typischer Wert: ev_target_soc=80",
            ))

    def _check_decision_interval(
        self, cfg, results: List[ValidationResult]
    ) -> None:
        if not hasattr(cfg, "decision_interval_minutes"):
            return
        val = cfg.decision_interval_minutes
        if not isinstance(val, (int, float)) or val < 1 or val > 60:
            results.append(ValidationResult(
                field="decision_interval_minutes",
                value=val,
                severity="warning",
                message=(
                    f"decision_interval_minutes ({val}) liegt ausserhalb "
                    "des empfohlenen Bereichs 1-60 - wird auf 15 gesetzt"
                ),
                suggestion="Empfohlener Wert: decision_interval_minutes=15",
            ))

    def _check_influxdb_optional(
        self, cfg, results: List[ValidationResult]
    ) -> None:
        """Warn if InfluxDB host looks unconfigured but other InfluxDB fields are set."""
        # InfluxDB is entirely optional — only warn, never critical
        if not hasattr(cfg, "influxdb_host"):
            return
        host = cfg.influxdb_host
        db = getattr(cfg, "influxdb_database", "") if hasattr(cfg, "influxdb_database") else ""
        # If host is the default placeholder but database was customised,
        # the user may have partially configured InfluxDB.
        if host == "influxdb.local" and db and db != "smartload":
            results.append(ValidationResult(
                field="influxdb_host",
                value=host,
                severity="warning",
                message=(
                    "influxdb_host ist noch der Standard-Platzhalterwert "
                    f"({host}), aber influxdb_database wurde geaendert "
                    f"({db}). InfluxDB-Integration moeglicherweise "
                    "fehlkonfiguriert."
                ),
                suggestion=(
                    "Trage die tatsaechliche IP-Adresse deines "
                    "InfluxDB-Servers ein oder lasse alle InfluxDB-Felder "
                    "auf den Standardwerten."
                ),
            ))

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def has_critical(results: List[ValidationResult]) -> bool:
        """Return True if any result has severity 'critical'."""
        return any(r.severity == "critical" for r in results)
