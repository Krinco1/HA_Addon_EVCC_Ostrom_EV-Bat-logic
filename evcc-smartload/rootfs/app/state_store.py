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

from state import Action, SystemState


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
            # Take snapshot while still holding lock
            snap = self._snapshot_unlocked()

        # Broadcast outside the lock — iterates client queues (I/O)
        self._broadcast(snap)

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
        return {
            "state": copy.copy(self._state),
            "lp_action": copy.copy(self._lp_action),
            "rl_action": copy.copy(self._rl_action),
            "solar_forecast": list(self._solar_forecast),
            "last_update": self._last_update,
        }

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

    p = state.price_percentiles if state else {}

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
    }
