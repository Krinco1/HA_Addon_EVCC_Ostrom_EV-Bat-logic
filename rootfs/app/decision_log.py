"""
Decision Log — v5.0

Extended with sequencer-related entries (charge schedule, quiet hours,
Telegram notifications).
"""

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional


class DecisionEntry:
    __slots__ = ("ts", "category", "icon", "text", "details", "source")

    def __init__(self, category: str, icon: str, text: str,
                 details: str = "", source: str = "system"):
        self.ts = datetime.now(timezone.utc)
        self.category = category
        self.icon = icon
        self.text = text
        self.details = details
        self.source = source

    def to_dict(self) -> dict:
        return {
            "ts": self.ts.isoformat(),
            "ts_local": self.ts.astimezone().strftime("%H:%M:%S"),
            "category": self.category,
            "icon": self.icon,
            "text": self.text,
            "details": self.details,
            "source": self.source,
        }


class DecisionLog:
    def __init__(self, max_entries: int = 100):
        self._entries: deque = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def observe(self, text: str, details: str = "", source: str = "system"):
        self._add("observe", "👁️", text, details, source)

    def plan(self, text: str, details: str = "", source: str = "system"):
        self._add("plan", "🧠", text, details, source)

    def action(self, text: str, details: str = "", source: str = "controller"):
        self._add("action", "⚡", text, details, source)

    def warning(self, text: str, details: str = "", source: str = "system"):
        self._add("warning", "⚠️", text, details, source)

    def rl(self, text: str, details: str = "", source: str = "rl"):
        self._add("rl", "🤖", text, details, source)

    def sequencer(self, text: str, details: str = "", source: str = "sequencer"):
        """v5: Log a sequencer / charge-scheduling decision."""
        self._add("sequencer", "🔄", text, details, source)

    def _add(self, category: str, icon: str, text: str, details: str, source: str):
        entry = DecisionEntry(category, icon, text, details, source)
        with self._lock:
            self._entries.append(entry)

    def get_recent(self, n: int = 30) -> List[dict]:
        with self._lock:
            entries = list(self._entries)
        return [e.to_dict() for e in entries[-n:]]

    def get_last_cycle_summary(self) -> dict:
        with self._lock:
            entries = list(self._entries)
        if not entries:
            return {"observations": [], "plans": [], "actions": [], "sequencer": []}

        now = datetime.now(timezone.utc)
        recent = [e for e in entries if (now - e.ts).total_seconds() < 120]
        return {
            "observations": [e.to_dict() for e in recent if e.category == "observe"],
            "plans": [e.to_dict() for e in recent if e.category == "plan"],
            "actions": [e.to_dict() for e in recent if e.category in ("action", "rl")],
            "warnings": [e.to_dict() for e in recent if e.category == "warning"],
            "sequencer": [e.to_dict() for e in recent if e.category == "sequencer"],
        }


def log_main_cycle(
    dlog: "DecisionLog",
    state,
    cfg,
    vehicles: Dict,
    lp_action,
    rl_action,
    comparator,
    tariffs: list,
    solar_forecast: list = None,
    sequencer=None,
):
    """Called each main loop iteration to log full decision reasoning."""
    if not state:
        dlog.warning("Kein System-Status verfügbar")
        return

    price_ct = state.current_price * 100
    p20 = state.price_percentiles.get(20, state.current_price) * 100
    p60 = state.price_percentiles.get(60, state.current_price) * 100
    bat_soc = state.battery_soc
    pv_kw = state.pv_power / 1000
    home_kw = state.home_power / 1000

    dlog.observe(
        f"Preis {price_ct:.1f}ct (P20={p20:.1f} P60={p60:.1f}) · "
        f"Batterie {bat_soc:.0f}% · PV {pv_kw:.1f}kW · Haus {home_kw:.1f}kW",
        source="system",
    )

    bat_limit = cfg.battery_max_price_ct
    ev_limit = cfg.ev_max_price_ct

    for name, v in vehicles.items():
        soc = v.get_effective_soc()
        connected = "🔌 am Wallbox" if v.connected_to_wallbox else "🅿️ nicht verbunden"
        stale = " ⚠️ VERALTET" if v.is_data_stale() else ""
        dlog.observe(
            f"{name}: {soc:.0f}% ({v.data_source}) · {connected}{stale}",
            details=f"{v.capacity_kwh}kWh, Ziel {cfg.ev_target_soc}%",
            source="vehicle",
        )

    # Battery decision
    if lp_action:
        bat_names = {0:"hold", 1:"P20", 2:"P40", 3:"P60", 4:"max", 5:"PV", 6:"entladen"}
        bat_label = bat_names.get(lp_action.battery_action, "?")
        bl = f"{lp_action.battery_limit_eur * 100:.1f}ct" if lp_action.battery_limit_eur else "—"
        dlog.plan(f"Batterie: {bat_label} @ {bl}", source="battery")

    # EV decisions
    for name, v in vehicles.items():
        soc = v.get_effective_soc()
        need = max(0, (cfg.ev_target_soc - soc) / 100 * v.capacity_kwh)
        if need < 1:
            continue
        if v.connected_to_wallbox:
            if price_ct <= ev_limit:
                dlog.plan(f"{name}: Laden ({need:.0f}kWh, {price_ct:.1f}ct ≤ {ev_limit}ct)", source="vehicle")
            else:
                dlog.plan(f"{name}: Warten ({price_ct:.1f}ct > {ev_limit}ct)", source="vehicle")
        else:
            dlog.plan(f"{name}: {need:.0f}kWh Bedarf, nicht am Wallbox", source="vehicle")

    # PV surplus
    if pv_kw > 0.5:
        surplus = max(0, pv_kw - home_kw)
        if surplus > 0.3:
            dlog.observe(f"PV-Überschuss: {surplus:.1f}kW", source="system")

    # Sequencer status
    if sequencer is not None:
        sched = sequencer.get_schedule_summary()
        if sched:
            dlog.sequencer(
                f"Lade-Plan: {len(sched)} Slots für {len({s['vehicle'] for s in sched})} EV(s)",
                details=", ".join(f"{s['vehicle']} {s['start_local']}" for s in sched[:3]),
                source="sequencer",
            )
        requests = sequencer.get_requests_summary()
        if requests:
            for v_name, req in requests.items():
                dlog.sequencer(
                    f"{v_name}: {req['need_kwh']}kWh → {req['target_soc']}% ({req['status']})",
                    source="sequencer",
                )
        now = datetime.now(timezone.utc)
        quiet_status = sequencer.get_quiet_hours_status(now)
        if quiet_status["currently_active"]:
            dlog.observe(
                f"Ruhezeit aktiv ({quiet_status['start']}:00–{quiet_status['end']}:00) → kein EV-Wechsel",
                source="sequencer",
            )

    # LP actions
    if lp_action:
        if lp_action.battery_limit_eur is not None:
            dlog.action(f"LP → Batterie-Limit: {lp_action.battery_limit_eur * 100:.1f}ct", source="controller")
        if lp_action.ev_limit_eur is not None:
            dlog.action(f"LP → EV-Limit: {lp_action.ev_limit_eur * 100:.1f}ct", source="controller")

    # RL status
    try:
        n_comps = len(comparator.comparisons)
        win_pct = (comparator.rl_wins / max(1, n_comps)) * 100
        label = "aktiv" if comparator.rl_ready else "Schatten-Modus"
        dlog.rl(f"RL {label} (Win-Rate: {win_pct:.0f}%, {n_comps} Vergleiche)", source="rl")

        if rl_action and lp_action:
            if rl_action.battery_action != lp_action.battery_action:
                dlog.rl(
                    f"RL weicht ab: Bat {rl_action.battery_action} (LP: {lp_action.battery_action})",
                    source="rl",
                )
    except Exception:
        pass
