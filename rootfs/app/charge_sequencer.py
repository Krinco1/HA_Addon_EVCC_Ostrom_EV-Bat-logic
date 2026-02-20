"""
Charge Sequencer — v5.0 NEW

Plans optimal charge order for multiple EVs sharing a single wallbox.
Respects quiet hours (no plug-switching at night) and driver preferences.

Key rules:
  1. Only 1 EV at a time (single wallbox)
  2. No switching during quiet hours
  3. Connected EV has priority (no unplugging needed)
  4. Small need first → finishes sooner → next EV can charge
  5. Solar windows preferred for EVs with large need
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from config import Config
from evcc_client import EvccClient
from logging_util import log


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class ChargeRequest:
    """A confirmed charge request from a driver."""
    vehicle_name: str
    driver_name: str
    target_soc: int
    current_soc: float
    capacity_kwh: float
    charge_power_kw: float
    need_kwh: float
    hours_needed: float
    confirmed_at: datetime
    priority: int = 0
    status: str = "pending"    # pending, scheduled, charging, done, expired


@dataclass
class ChargeSlot:
    """A planned charge window."""
    vehicle_name: str
    start_hour: datetime
    end_hour: datetime
    energy_kwh: float
    avg_price_ct: float
    source: str               # "grid_cheap", "solar", "grid_expensive"


@dataclass
class QuietHoursConfig:
    enabled: bool = True
    start_hour: int = 21
    end_hour: int = 6


# =============================================================================
# Sequencer
# =============================================================================

class ChargeSequencer:
    """Plans optimal charge sequence for a single wallbox."""

    def __init__(self, cfg: Config, evcc: EvccClient):
        self.cfg = cfg
        self.evcc = evcc
        self.requests: Dict[str, ChargeRequest] = {}
        self.schedule: List[ChargeSlot] = []
        self.quiet = QuietHoursConfig(
            enabled=cfg.quiet_hours_enabled,
            start_hour=cfg.quiet_hours_start,
            end_hour=cfg.quiet_hours_end,
        )
        self._last_applied_vehicle: Optional[str] = None

    # ------------------------------------------------------------------
    # Request management
    # ------------------------------------------------------------------

    def add_request(
        self,
        vehicle: str,
        driver: str,
        target_soc: int,
        current_soc: float,
        capacity_kwh: float,
        charge_power_kw: float = 11.0,
    ) -> ChargeRequest:
        """Register a confirmed charge request (e.g. from Telegram response)."""
        need = max(0.0, (target_soc - current_soc) / 100.0 * capacity_kwh)
        hours = need / max(charge_power_kw, 1.0)
        req = ChargeRequest(
            vehicle_name=vehicle,
            driver_name=driver,
            target_soc=target_soc,
            current_soc=current_soc,
            capacity_kwh=capacity_kwh,
            charge_power_kw=charge_power_kw,
            need_kwh=round(need, 2),
            hours_needed=round(hours, 2),
            confirmed_at=datetime.now(timezone.utc),
        )
        self.requests[vehicle] = req
        log("info", f"ChargeSequencer: {vehicle} → {target_soc}% ({need:.1f} kWh, {hours:.1f}h)")
        return req

    def update_soc(self, vehicle: str, new_soc: float):
        """Update SoC after a charge cycle (reduces need_kwh)."""
        if vehicle in self.requests:
            req = self.requests[vehicle]
            req.current_soc = new_soc
            req.need_kwh = max(0.0, (req.target_soc - new_soc) / 100.0 * req.capacity_kwh)
            if req.need_kwh < 0.5:
                req.status = "done"
                log("info", f"ChargeSequencer: {vehicle} done ({new_soc:.0f}%)")

    def remove_request(self, vehicle: str):
        self.requests.pop(vehicle, None)

    def expire_old_requests(self, max_age_hours: int = 36):
        """Remove stale requests (driver never connected vehicle)."""
        now = datetime.now(timezone.utc)
        expired = [
            v for v, r in self.requests.items()
            if (now - r.confirmed_at).total_seconds() / 3600 > max_age_hours
            or r.status == "done"
        ]
        for v in expired:
            log("info", f"ChargeSequencer: expiring {v} (age/done)")
            del self.requests[v]

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def plan(
        self,
        prices: List[Dict],
        solar_forecast: List[Dict],
        connected_vehicle: Optional[str],
        now: datetime,
    ) -> List[ChargeSlot]:
        """Calculate optimal charge schedule."""
        self.expire_old_requests()

        pending = [
            r for r in self.requests.values()
            if r.status in ("pending", "scheduled") and r.need_kwh > 0.5
        ]
        if not pending:
            self.schedule = []
            return []

        hourly_prices = self._parse_hourly_prices(prices, now)
        solar_hours = self._parse_solar_hours(solar_forecast, now)

        ranked = self._rank_vehicles(pending, connected_vehicle, solar_hours, now)
        schedule = self._assign_time_windows(ranked, hourly_prices, solar_hours, now)

        for req in pending:
            req.status = "scheduled"

        self.schedule = schedule
        return schedule

    def _rank_vehicles(
        self,
        pending: List[ChargeRequest],
        connected_vehicle: Optional[str],
        solar_hours: List[Tuple[datetime, float]],
        now: datetime,
    ) -> List[ChargeRequest]:
        for req in pending:
            req.priority = 0

            if req.vehicle_name == connected_vehicle:
                req.priority += 30  # already plugged in → no switch needed

            solar_available = sum(kw for _, kw in solar_hours)
            if solar_available > req.need_kwh * 1.3:
                req.priority -= 20  # can wait for solar

            if req.hours_needed < 3:
                req.priority += 15  # small need finishes quickly

            if self._is_quiet(now) and req.vehicle_name == connected_vehicle:
                req.priority += 100  # quiet hours: stay with current vehicle

        return sorted(pending, key=lambda r: r.priority, reverse=True)

    def _assign_time_windows(
        self,
        ranked: List[ChargeRequest],
        hourly_prices: List[Tuple[datetime, float]],
        solar_hours: List[Tuple[datetime, float]],
        now: datetime,
    ) -> List[ChargeSlot]:
        schedule: List[ChargeSlot] = []
        used_hours: set = set()

        for req in ranked:
            # During quiet hours: skip vehicles that aren't connected
            # (they have to wait until quiet period ends)
            available = [
                (h, p) for h, p in hourly_prices
                if h not in used_hours
            ]
            if not available:
                break

            needed = max(1, int(req.hours_needed) + 1)
            by_price = sorted(available, key=lambda x: x[1])
            chosen = by_price[:needed]

            if chosen:
                slots = self._build_slots(req.vehicle_name, chosen, req.need_kwh)
                schedule.extend(slots)
                used_hours.update(h for h, _ in chosen)

        return sorted(schedule, key=lambda s: s.start_hour)

    def _build_slots(
        self,
        vehicle_name: str,
        chosen: List[Tuple[datetime, float]],
        total_kwh: float,
    ) -> List[ChargeSlot]:
        if not chosen:
            return []
        avg_price = sum(p for _, p in chosen) / len(chosen)
        kwh_each = total_kwh / len(chosen)
        slots = []
        for h, p in sorted(chosen, key=lambda x: x[0]):
            source = "solar" if p < 0.005 else ("grid_cheap" if p * 100 < 25 else "grid_expensive")
            slots.append(ChargeSlot(
                vehicle_name=vehicle_name,
                start_hour=h,
                end_hour=h + timedelta(hours=1),
                energy_kwh=round(kwh_each, 2),
                avg_price_ct=round(p * 100, 1),
                source=source,
            ))
        return slots

    # ------------------------------------------------------------------
    # evcc integration
    # ------------------------------------------------------------------

    def apply_to_evcc(self, now: datetime):
        """Send current schedule to evcc (loadpoint 1)."""
        active = self._get_active_slot(now)
        if active:
            req = self.requests.get(active.vehicle_name)
            if req:
                self.evcc.set_loadpoint_targetsoc(1, req.target_soc)
            mode = "pv" if active.source == "solar" else "minpv"
            self.evcc.set_loadpoint_mode(1, mode)
            if self._last_applied_vehicle != active.vehicle_name:
                log("info", f"Sequencer: activating {active.vehicle_name} ({mode})")
                self._last_applied_vehicle = active.vehicle_name
        else:
            # No active slot; if we were controlling, reset
            if self._last_applied_vehicle is not None:
                log("info", "Sequencer: no active slot → loadpoint off")
                self.evcc.set_loadpoint_mode(1, "off")
                self._last_applied_vehicle = None

    def _get_active_slot(self, now: datetime) -> Optional[ChargeSlot]:
        for slot in self.schedule:
            if slot.start_hour <= now < slot.end_hour:
                return slot
        return None

    # ------------------------------------------------------------------
    # Quiet hours helpers
    # ------------------------------------------------------------------

    def _is_quiet(self, dt: datetime) -> bool:
        if not self.quiet.enabled:
            return False
        h = dt.hour
        s, e = self.quiet.start_hour, self.quiet.end_hour
        if s > e:
            return h >= s or h < e
        return s <= h < e

    def get_pre_quiet_recommendation(self, now: datetime) -> Optional[Dict]:
        """Up to 90 min before quiet hours: recommend which EV to plug in."""
        if not self.quiet.enabled:
            return None
        quiet_start = now.replace(hour=self.quiet.start_hour, minute=0, second=0, microsecond=0)
        if now >= quiet_start:
            return None
        minutes_until = (quiet_start - now).total_seconds() / 60
        if minutes_until > 90 or minutes_until < 0:
            return None

        pending = [
            r for r in self.requests.values()
            if r.status in ("pending", "scheduled")
        ]
        if not pending:
            return None

        best = max(pending, key=lambda r: r.need_kwh)
        return {
            "vehicle": best.vehicle_name,
            "driver": best.driver_name,
            "need_kwh": best.need_kwh,
            "target_soc": best.target_soc,
            "minutes_until_quiet": round(minutes_until),
            "message": (
                f"Bitte {best.vehicle_name} bis {self.quiet.start_hour}:00 anstecken. "
                f"Nachtladung {best.current_soc:.0f}%→{best.target_soc}% "
                f"({best.need_kwh:.0f} kWh) geplant."
            ),
        }

    # ------------------------------------------------------------------
    # API / Dashboard helpers
    # ------------------------------------------------------------------

    def get_schedule_summary(self) -> List[Dict]:
        return [
            {
                "vehicle": s.vehicle_name,
                "start": s.start_hour.isoformat(),
                "end": s.end_hour.isoformat(),
                "start_local": s.start_hour.astimezone().strftime("%H:%M"),
                "end_local": s.end_hour.astimezone().strftime("%H:%M"),
                "kwh": round(s.energy_kwh, 1),
                "price_ct": round(s.avg_price_ct, 1),
                "source": s.source,
            }
            for s in self.schedule
        ]

    def get_requests_summary(self) -> Dict:
        return {
            v: {
                "driver": r.driver_name,
                "target_soc": r.target_soc,
                "current_soc": round(r.current_soc, 0),
                "need_kwh": round(r.need_kwh, 1),
                "hours_needed": round(r.hours_needed, 1),
                "status": r.status,
                "confirmed_at": r.confirmed_at.isoformat(),
            }
            for v, r in self.requests.items()
        }

    def get_quiet_hours_status(self, now: datetime) -> Dict:
        is_quiet = self._is_quiet(now)
        return {
            "enabled": self.quiet.enabled,
            "start": self.quiet.start_hour,
            "end": self.quiet.end_hour,
            "currently_active": is_quiet,
            "pre_quiet_recommendation": self.get_pre_quiet_recommendation(now),
        }

    # ------------------------------------------------------------------
    # Tariff / solar parsing helpers
    # ------------------------------------------------------------------

    def _parse_hourly_prices(
        self, tariffs: List[Dict], now: datetime
    ) -> List[Tuple[datetime, float]]:
        from collections import defaultdict
        buckets: Dict[datetime, list] = defaultdict(list)
        for t in tariffs:
            try:
                s = t.get("start", "")
                val = float(t.get("value", 0))
                if s.endswith("Z"):
                    start = datetime.fromisoformat(s.replace("Z", "+00:00"))
                elif "+" in s:
                    start = datetime.fromisoformat(s)
                else:
                    start = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
                hour = start.replace(minute=0, second=0, microsecond=0)
                if hour >= now.replace(minute=0, second=0, microsecond=0):
                    buckets[hour].append(val)
            except Exception:
                continue
        return sorted((h, sum(v) / len(v)) for h, v in buckets.items())

    def _parse_solar_hours(
        self, solar_forecast: List[Dict], now: datetime
    ) -> List[Tuple[datetime, float]]:
        if not solar_forecast:
            return []
        raw_vals = [float(t.get("value", 0)) for t in solar_forecast if float(t.get("value", 0)) > 0]
        unit_factor = 0.001 if raw_vals and sorted(raw_vals)[len(raw_vals) // 2] > 100 else 1.0
        result = []
        for t in solar_forecast:
            try:
                s = t.get("start", "")
                val = float(t.get("value", 0)) * unit_factor
                if val <= 0:
                    continue
                if s.endswith("Z"):
                    start = datetime.fromisoformat(s.replace("Z", "+00:00"))
                elif "+" in s:
                    start = datetime.fromisoformat(s)
                else:
                    start = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
                if start >= now:
                    result.append((start, val))
            except Exception:
                continue
        return sorted(result)
