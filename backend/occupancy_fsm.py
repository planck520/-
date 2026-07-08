from __future__ import annotations

import config


class OccupancyFSM:
    def __init__(self) -> None:
        self.state = "VACANT"

    def update(self, score: float) -> str:
        previous = self.state

        if self.state == "VACANT":
            if score >= config.FSM_ENTER_OCCUPIED:
                self.state = "OCCUPIED"
            elif score >= config.FSM_ENTER_ARRIVING:
                self.state = "ARRIVING"
        elif self.state == "ARRIVING":
            if score >= config.FSM_ENTER_OCCUPIED:
                self.state = "OCCUPIED"
            elif score < config.FSM_ENTER_ARRIVING * 0.5:
                self.state = "VACANT"
        elif self.state == "OCCUPIED":
            if score < config.FSM_ENTER_LEAVING:
                self.state = "LEAVING"
        elif self.state == "LEAVING":
            if score <= config.FSM_EXIT_OCCUPIED:
                self.state = "VACANT"
            elif score >= config.FSM_ENTER_OCCUPIED:
                self.state = "OCCUPIED"

        return previous
