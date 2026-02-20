"""Event detector — unchanged from v4."""

from typing import List
from state import SystemState


class EventDetector:
    """Detects notable energy events for RL reward shaping."""

    def __init__(self):
        self._prev: SystemState = None

    def detect(self, state: SystemState) -> List[str]:
        events = []
        if self._prev is None:
            self._prev = state
            return events

        prev = self._prev

        # Price events
        if state.current_price < prev.current_price * 0.85:
            events.append("PRICE_DROP")
        elif state.current_price > prev.current_price * 1.15:
            events.append("PRICE_SPIKE")

        # PV surge
        if state.pv_power > prev.pv_power * 1.5 and state.pv_power > 2000:
            events.append("PV_SURGE")

        # EV externally charged (SoC increased without wallbox)
        if (not state.ev_connected and not prev.ev_connected
                and state.ev_soc > prev.ev_soc + 5):
            events.append("EV_CHARGED_EXTERNALLY")

        self._prev = state
        return events
