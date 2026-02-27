"""
Thread-safe StateStore for EVCC-Smartload v6.

Single source of truth for shared mutable state between the main decision loop
(writer) and the web server (reader). All writes are guarded by a single RLock.
Readers call snapshot() to get an atomic shallow copy.

SSE broadcast: StateStore maintains a list of per-client queue.Queue objects.
After each update(), it broadcasts the new snapshot to all connected SSE clients
outside the RLock (no I/O while holding the lock).
"""

import copy
import queue
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from state import Action, PlanHorizon, SystemState


class StateStore:
    """RLock-guarded store for all shared mutable state.

    Writers: main decision loop (via update()).
    Readers: web server request handlers (via snapshot()).

    Design decisions (see 01-RESEARCH.md):
    - RLock (not Lock): re-entrant, safe if nested calls occur.
    - snapshot() returns shallow copies: SystemState fields are primitives +
      lists, so copy.copy() is safe and ~100x faster than dataclasses.asdict().
    - SSE clients use a separate _sse_lock (not the main RLock) to avoid
      holding the state lock during I/O.
    - Broadcast happens AFTER releasing the RLock to avoid holding it during
      queue I/O (see research anti-pattern: "Never hold StateStore._lock during I/O").
    """

    def __init__(self) -> None:
        # --- Main state fields (guarded by _lock) ---
        self._lock = threading.RLock()
        self._state: Optional[SystemState] = None
        self._lp_action: Optional[Action] = None
        self._rl_action: Optional[Action] = None
        self._solar_forecast: List[Dict] = []
        self._last_update: Optional[datetime] = None

        # --- v7: Forecast fields (guarded by _lock) ---
        self._consumption_forecast: Optional[List[float]] = None
        self._pv_forecast: Optional[List[float]] = None
        self._pv_confidence: float = 0.0
        self._pv_correction_label: str = ""
        self._pv_quality_label: str = ""
        self._forecaster_ready: bool = False
        self._forecaster_data_days: int = 0
        self._ha_warnings: List[str] = []

        # --- Phase 4: LP plan storage (guarded by _lock) ---
        self._plan: Optional[PlanHorizon] = None

        # --- Phase 5: Dynamic buffer result (guarded by _lock) ---
        self._buffer_result: Optional[dict] = None

        # --- Phase 11: Mode control status (guarded by _lock) ---
        self._mode_control_status: Optional[dict] = None

        # --- Phase 12: Arbitrage status (guarded by _lock) ---
        self._arbitrage_status: Optional[dict] = None

        # --- SSE client queues (guarded by _sse_lock, separate from _lock) ---
        self._sse_clients: List[queue.Queue] = []
        self._sse_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write interface (called from main decision loop only)
    # ------------------------------------------------------------------

    def update(
        self,
        state: Optional[SystemState],
        lp_action: Optional[Action],
        rl_action: Optional[Action],
        solar_forecast: Optional[List[Dict]] = None,
        consumption_forecast: Optional[List[float]] = None,
        pv_forecast: Optional[List[float]] = None,
        pv_confidence: float = 0.0,
        pv_correction_label: str = "",
        pv_quality_label: str = "",
        forecaster_ready: bool = False,
        forecaster_data_days: int = 0,
        ha_warnings: Optional[List[str]] = None,
        buffer_result: Optional[dict] = None,
        mode_control_status: Optional[dict] = None,
        arbitrage_status: Optional[dict] = None,
    ) -> None:
        """Update all state fields atomically under RLock.

        Releases the lock BEFORE broadcasting to SSE clients to avoid
        holding the lock during queue I/O.
        """
        with self._lock:
            self._state = state
            self._lp_action = lp_action
            self._rl_action = rl_action
            self._solar_forecast = list(solar_forecast) if solar_forecast else []
            self._last_update = datetime.now(timezone.utc)
            # v7: forecast fields
            self._consumption_forecast = list(consumption_forecast) if consumption_forecast else None
            self._pv_forecast = list(pv_forecast) if pv_forecast else None
            self._pv_confidence = pv_confidence
            self._pv_correction_label = pv_correction_label
            self._pv_quality_label = pv_quality_label
            self._forecaster_ready = forecaster_ready
            self._forecaster_data_days = forecaster_data_days
            self._ha_warnings = list(ha_warnings) if ha_warnings else []
            # Phase 5: dynamic buffer result
            self._buffer_result = buffer_result
            # Phase 11: mode control status
            self._mode_control_status = mode_control_status
            # Phase 12: arbitrage status
            self._arbitrage_status = arbitrage_status
            # Take snapshot while still holding lock
            snap = self._snapshot_unlocked()

        # Broadcast outside the lock — iterates client queues (I/O)
        self._broadcast(snap)

    def update_plan(self, plan: PlanHorizon) -> None:
        """Store the latest LP plan under RLock.

        Does NOT broadcast SSE — plan data is included in the next regular
        update() broadcast via _snapshot_unlocked() / _snapshot_to_json_dict().
        """
        with self._lock:
            self._plan = plan

    def get_plan(self) -> Optional[PlanHorizon]:
        """Return the latest LP plan (or None if not yet computed).

        PlanHorizon is immutable after construction (dataclass), so returning
        the reference directly is safe without deep-copying.
        """
        with self._lock:
            return self._plan

    # ------------------------------------------------------------------
    # Read interface (called from web handlers)
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict:
        """Return a shallow copy of all state fields; safe for concurrent reads.

        Callers should call this ONCE at the top of each handler method and
        reference the returned dict throughout (anti-pattern: calling snapshot()
        multiple times per handler yields state from different cycles).
        """
        with self._lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> Dict:
        """Build snapshot dict; caller MUST hold self._lock."""
        snap = {
            "state": copy.copy(self._state),
            "lp_action": copy.copy(self._lp_action),
            "rl_action": copy.copy(self._rl_action),
            "solar_forecast": list(self._solar_forecast),
            "last_update": self._last_update,
            # v7: forecast fields
            "consumption_forecast": list(self._consumption_forecast) if self._consumption_forecast else None,
            "pv_forecast": list(self._pv_forecast) if self._pv_forecast else None,
            "pv_confidence": self._pv_confidence,
            "pv_correction_label": self._pv_correction_label,
            "pv_quality_label": self._pv_quality_label,
            "forecaster_ready": self._forecaster_ready,
            "forecaster_data_days": self._forecaster_data_days,
            "ha_warnings": list(self._ha_warnings) if self._ha_warnings else [],
            # Phase 5: dynamic buffer result
            "buffer_result": copy.copy(self._buffer_result),
            # Phase 11: mode control status
            "mode_control_status": copy.copy(self._mode_control_status),
            # Phase 12: arbitrage status
            "arbitrage_status": copy.copy(self._arbitrage_status),
        }
        # Phase 4: plan summary fields (lightweight — full slot timeline in Phase 6)
        if self._plan is not None:
            snap["plan_computed_at"] = self._plan.computed_at.isoformat() if self._plan.computed_at else None
            snap["plan_solver_status"] = self._plan.solver_status
            snap["plan_cost_eur"] = self._plan.solver_fun
            snap["plan_slots_count"] = len(self._plan.slots)
        else:
            snap["plan_computed_at"] = None
            snap["plan_solver_status"] = None
            snap["plan_cost_eur"] = None
            snap["plan_slots_count"] = 0
        # Keep plan reference for _snapshot_to_json_dict (plan_summary SSE key)
        snap["_plan"] = self._plan
        return snap

    # ------------------------------------------------------------------
    # SSE client management
    # ------------------------------------------------------------------

    def register_sse_client(self) -> queue.Queue:
        """Create and register a new SSE client queue.

        Returns the queue; caller blocks on queue.get() in the SSE handler.
        maxsize=10: drops updates for slow clients rather than blocking the
        broadcast loop.
        """
        client_q: queue.Queue = queue.Queue(maxsize=10)
        with self._sse_lock:
            self._sse_clients.append(client_q)
        return client_q

    def unregister_sse_client(self, client_q: queue.Queue) -> None:
        """Remove a client queue when its SSE connection closes."""
        with self._sse_lock:
            try:
                self._sse_clients.remove(client_q)
            except ValueError:
                pass  # already removed (e.g., double-close)

    def _broadcast(self, snap: Dict) -> None:
        """Push snapshot to all registered SSE clients.

        Iterates a copy of _sse_clients (Pitfall 3 from research: avoids
        mutation-during-iteration if a client unregisters concurrently).
        Slow clients whose queue is full receive a silent drop (queue.Full).
        """
        # Serialise the snapshot to a JSON-safe dict for SSE transmission
        payload = _snapshot_to_json_dict(snap)

        with self._sse_lock:
            clients = list(self._sse_clients)

        for client_q in clients:
            try:
                client_q.put_nowait(payload)
            except queue.Full:
                pass  # slow client — drop this update


# ------------------------------------------------------------------
# Serialisation helper
# ------------------------------------------------------------------

def _snapshot_to_json_dict(snap: Dict) -> Dict:
    """Convert a snapshot dict to a JSON-serialisable dict for SSE.

    Uses default=str for datetime and dataclass fields that may not be
    natively JSON-serialisable.
    """
    state: Optional[SystemState] = snap.get("state")
    lp: Optional[Action] = snap.get("lp_action")
    last_update: Optional[datetime] = snap.get("last_update")
    plan: Optional[PlanHorizon] = snap.get("_plan")

    p = state.price_percentiles if state else {}

    # Phase 4: plan_summary — lightweight LP plan status for dashboard
    if plan is not None:
        slot0 = plan.slots[0] if plan.slots else None
        plan_summary = {
            "computed_at": plan.computed_at.isoformat() if plan.computed_at else None,
            "status": plan.solver_status,
            "cost_eur": plan.solver_fun,
            "current_action": {
                "bat_charge": plan.current_bat_charge,
                "bat_discharge": plan.current_bat_discharge,
                "ev_charge": plan.current_ev_charge,
            },
        }
    else:
        plan_summary = None

    return {
        "last_update": last_update.isoformat() if last_update else None,
        "state": {
            "battery_soc": state.battery_soc if state else None,
            "battery_power": state.battery_power if state else None,
            "grid_power": state.grid_power if state else None,
            "current_price": state.current_price if state else None,
            "pv_power": state.pv_power if state else None,
            "home_power": state.home_power if state else None,
            "ev_connected": state.ev_connected if state else None,
            "ev_soc": state.ev_soc if state else None,
            "ev_power": state.ev_power if state else None,
            "ev_name": state.ev_name if state else None,
            "price_p20": p.get(20) if state else None,
            "price_p60": p.get(60) if state else None,
            "price_spread": state.price_spread if state else None,
            "hours_cheap_remaining": state.hours_cheap_remaining if state else None,
            "solar_forecast_total_kwh": state.solar_forecast_total_kwh if state else None,
        } if state else None,
        "lp_action": {
            "battery_action": lp.battery_action if lp else None,
            "ev_action": lp.ev_action if lp else None,
            "battery_limit_eur": lp.battery_limit_eur if lp else None,
            "ev_limit_eur": lp.ev_limit_eur if lp else None,
        } if lp else None,
        # v7: forecast section — enables live chart updates via SSE
        "forecast": {
            "consumption_96": snap.get("consumption_forecast"),
            "pv_96": snap.get("pv_forecast"),
            "pv_confidence": snap.get("pv_confidence", 0.0),
            "pv_correction_label": snap.get("pv_correction_label", ""),
            "pv_quality_label": snap.get("pv_quality_label", ""),
            "forecaster_ready": snap.get("forecaster_ready", False),
            "forecaster_data_days": snap.get("forecaster_data_days", 0),
            "ha_warnings": snap.get("ha_warnings", []),
        },
        # Phase 4: plan_summary — lightweight LP plan status for dashboard
        "plan_summary": plan_summary,
        # Phase 5: dynamic buffer — mode, current_buffer_pct, days_remaining, log_recent
        "buffer": snap.get("buffer_result"),
        # Phase 11: mode control — override status, evcc reachability
        "mode_control": snap.get("mode_control_status"),
        # Phase 12: arbitrage — battery-to-EV discharge status
        "arbitrage": snap.get("arbitrage_status"),
    }
