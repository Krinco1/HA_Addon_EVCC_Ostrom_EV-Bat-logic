"""
Controller – applies optimiser/RL actions to evcc.
"""

from typing import Optional

from config import Config
from evcc_client import EvccClient
from logging_util import log
from state import Action


class Controller:
    """Translates Action objects into evcc API calls."""

    def __init__(self, evcc: EvccClient, cfg: Config):
        self.evcc = evcc
        self.cfg = cfg
        self.last_action: Optional[Action] = None

    def apply(self, action: Action) -> float:
        """Apply action and return estimated cost (placeholder, refined later)."""

        # Battery
        if action.battery_limit_eur is not None and action.battery_limit_eur > 0:
            self.evcc.set_battery_grid_charge_limit(action.battery_limit_eur)
        else:
            self.evcc.clear_battery_grid_charge_limit()

        # EV
        if action.ev_limit_eur is not None:
            self.evcc.set_smart_cost_limit(max(0, action.ev_limit_eur))

        self.last_action = action
        return 0.0
