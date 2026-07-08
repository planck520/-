from __future__ import annotations

import config
from occupancy_fsm import OccupancyFSM


class OccupancyDetector:
    def __init__(self) -> None:
        self.fsm = OccupancyFSM()
        self.previous_snapshot: dict[str, float] | None = None

    def evaluate(self, snapshot: dict[str, float]) -> tuple[str, str, float]:
        score = self._score_snapshot(snapshot=snapshot, previous=self.previous_snapshot)
        previous_state = self.fsm.update(score)
        current_state = self.fsm.state
        self.previous_snapshot = snapshot.copy()
        return previous_state, current_state, round(score, 2)

    def _score_snapshot(
        self,
        snapshot: dict[str, float],
        previous: dict[str, float] | None,
    ) -> float:
        temp_delta = 0.0
        humidity_delta = 0.0
        light_delta = 0.0
        if previous is not None:
            temp_delta = abs(snapshot["temperature"] - previous["temperature"])
            humidity_delta = abs(snapshot["humidity"] - previous["humidity"])
            light_delta = abs(snapshot["light"] - previous["light"])

        components = {
            "co2": self._normalize(snapshot["co2"], "co2"),
            "noise": self._normalize(snapshot["noise"], "noise"),
            "temp_delta": self._normalize(temp_delta, "temp_delta"),
            "humidity_delta": self._normalize(humidity_delta, "humidity_delta"),
            "pm25": self._normalize(snapshot["pm25"], "pm25"),
            "light_delta": self._normalize(light_delta, "light_delta"),
        }
        score = 0.0
        for key, weight in config.FSM_WEIGHTS.items():
            score += components[key] * weight
        return max(0.0, min(1.0, score))

    def _normalize(self, value: float, key: str) -> float:
        low, high = config.OCCUPANCY_SCORE_RANGES[key]
        if value <= low:
            return 0.0
        if value >= high:
            return 1.0
        return (value - low) / (high - low)
