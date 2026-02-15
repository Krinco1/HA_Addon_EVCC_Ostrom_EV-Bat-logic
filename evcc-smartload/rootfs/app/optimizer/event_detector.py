"""
Event detector – recognises significant state changes for RL reward shaping.
"""

from collections import deque
from typing import List, Optional

from state import SystemState


class EventDetector:
    """Detects notable events (price spikes, EV plug-in, battery low, etc.)."""

    def __init__(self):
        self.last_state: Optional[SystemState] = None
        self.ev_history: deque = deque(maxlen=100)
        self.price_history: deque = deque(maxlen=100)

    def detect(self, state: SystemState) -> List[str]:
        events: List[str] = []

        if self.last_state:
            prev = self.last_state

            # EV events
            if not prev.ev_connected and state.ev_connected:
                events.append("EV_CONNECTED")
            if prev.ev_connected and not state.ev_connected:
                if state.ev_soc > prev.ev_soc + 5:
                    events.append("EV_CHARGED_EXTERNALLY")
                else:
                    events.append("EV_DISCONNECTED")

            # Price events
            if state.current_price < prev.current_price * 0.8:
                events.append("PRICE_DROP")
            if state.current_price > prev.current_price * 1.2:
                events.append("PRICE_SPIKE")

            # Battery events
            if state.battery_soc < 15 and prev.battery_soc >= 15:
                events.append("BATTERY_LOW")
            if state.battery_soc > 85 and prev.battery_soc <= 85:
                events.append("BATTERY_FULL")

            # PV events
            if state.pv_power > 1000 and prev.pv_power < 500:
                events.append("PV_SURGE")
            if state.pv_power < 200 and prev.pv_power > 1000:
                events.append("PV_DROP")

            # Grid export
            if state.grid_power < -1000:
                events.append("GRID_EXPORT")

        self.last_state = state
        return events
