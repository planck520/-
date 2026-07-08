from __future__ import annotations

from datetime import datetime
from typing import Any

import config
from database_manager import DatabaseManager
from llm_service import LLMService
from obix_client import ObixClient
from weather_service import WeatherService


class DeviceController:
    def __init__(
        self,
        obix_client: ObixClient,
        database: DatabaseManager,
        llm_service: LLMService,
        weather_service: WeatherService,
    ) -> None:
        self.obix_client = obix_client
        self.database = database
        self.llm_service = llm_service
        self.weather_service = weather_service
        self.active_profile = config.DEFAULT_PROFILE
        self.device_status = {
            "buzzer": {"state": False, "trigger": None},
            "warning_led": {"state": False, "trigger": None},
            "lighting_led": {"state": False, "brightness": 0, "mode": "auto"},
            "fan": {"state": False, "mode": "auto"},
        }
        self.last_llm_decision = "初始版本启用规则回退控制。"
        self.ai_mode = "fsm_fallback"
        self.degraded = config.SIMULATION_MODE
        self.last_write_error = ""
        self._noise_above_since: datetime | None = None
        self._noise_below_since: datetime | None = None
        self._smoke_below_since: datetime | None = None
        self._last_decision_signature: tuple[int, bool, str] | None = None

    def update(
        self,
        timestamp: str,
        snapshot: dict[str, float],
        fsm_state: str,
        fsm_score: float,
        data_source: str,
    ) -> None:
        current_time = datetime.fromisoformat(timestamp)
        self.degraded = data_source != "obix"
        self._apply_safety_rules(current_time=current_time, timestamp=timestamp, snapshot=snapshot)
        self._apply_comfort_control(timestamp=timestamp, snapshot=snapshot, fsm_state=fsm_state)
        if self.database.get_active_alerts():
            self.ai_mode = "emergency_override"
        elif self.device_status["lighting_led"]["mode"] == "auto" or self.device_status["fan"]["mode"] == "auto":
            self.ai_mode = "fsm_fallback"
        else:
            self.ai_mode = "manual_override"
        self.database.log_fsm_state(timestamp=timestamp, state=fsm_state, score=fsm_score)

    def get_device_status(self) -> dict[str, Any]:
        return self.device_status

    def get_system_control_state(self) -> dict[str, Any]:
        return {
            "active_profile": self.active_profile,
            "ai_mode": self.ai_mode,
            "last_llm_decision": self.last_llm_decision,
            "degraded": self.degraded,
            "last_write_error": self.last_write_error,
        }

    def set_profile(self, profile_name: str) -> None:
        if profile_name not in config.PROFILES:
            raise ValueError("Unsupported profile")
        self.active_profile = profile_name

    def manual_control(self, timestamp: str, device: str, action: str, value: Any = None) -> dict[str, Any]:
        if device not in self.device_status:
            raise ValueError("Unsupported device")

        if device in {"buzzer", "warning_led"}:
            desired_state = action == "on"
            if action not in {"on", "off"}:
                raise ValueError("Unsupported action")
            self._set_bool_device(
                timestamp=timestamp,
                device=device,
                desired_state=desired_state,
                source="manual",
                trigger="manual_override",
            )
            return self.device_status[device]

        if device == "lighting_led":
            if action == "set_brightness":
                brightness = int(value)
                if brightness < 0 or brightness > 100:
                    raise ValueError("Brightness must be between 0 and 100")
                self.device_status["lighting_led"]["mode"] = "manual"
                self._set_lighting(timestamp=timestamp, brightness=brightness, source="manual")
                return self.device_status["lighting_led"]
            if action == "auto":
                self.device_status["lighting_led"]["mode"] = "auto"
                return self.device_status["lighting_led"]
            raise ValueError("Unsupported action")

        if device == "fan":
            if action == "auto":
                self.device_status["fan"]["mode"] = "auto"
                return self.device_status["fan"]
            if action not in {"on", "off"}:
                raise ValueError("Unsupported action")
            self.device_status["fan"]["mode"] = "manual"
            self._set_bool_device(
                timestamp=timestamp,
                device="fan",
                desired_state=action == "on",
                source="manual",
                trigger="manual_override",
            )
            return self.device_status["fan"]

        raise ValueError("Unsupported device")

    def _apply_safety_rules(
        self,
        current_time: datetime,
        timestamp: str,
        snapshot: dict[str, float],
    ) -> None:
        smoke_value = snapshot["smoke"]
        noise_value = snapshot["noise"]

        if smoke_value >= config.SMOKE_THRESHOLD:
            self._smoke_below_since = None
            self.database.open_alert(
                timestamp=timestamp,
                alert_type="smoke_warning",
                severity="critical",
                message=f"烟雾浓度超标：{smoke_value:.1f} ppm",
                sensor_value=smoke_value,
                threshold=config.SMOKE_THRESHOLD,
            )
            self._set_bool_device(
                timestamp=timestamp,
                device="buzzer",
                desired_state=True,
                source="safety_rule",
                trigger="smoke_warning",
            )
        elif smoke_value <= config.SMOKE_THRESHOLD - config.SMOKE_HYSTERESIS:
            if self._smoke_below_since is None:
                self._smoke_below_since = current_time
            if (current_time - self._smoke_below_since).total_seconds() >= config.SMOKE_CLEAR_DELAY_SECONDS:
                self.database.resolve_alert(timestamp=timestamp, alert_type="smoke_warning")
                self._set_bool_device(
                    timestamp=timestamp,
                    device="buzzer",
                    desired_state=False,
                    source="safety_rule",
                    trigger=None,
                )

        if noise_value >= config.NOISE_THRESHOLD:
            self._noise_below_since = None
            if self._noise_above_since is None:
                self._noise_above_since = current_time
            if (current_time - self._noise_above_since).total_seconds() >= config.NOISE_DURATION_SECONDS:
                self.database.open_alert(
                    timestamp=timestamp,
                    alert_type="noise_warning",
                    severity="warning",
                    message=f"噪声持续超标：{noise_value:.1f} dB",
                    sensor_value=noise_value,
                    threshold=config.NOISE_THRESHOLD,
                )
                self._set_bool_device(
                    timestamp=timestamp,
                    device="warning_led",
                    desired_state=True,
                    source="safety_rule",
                    trigger="noise_warning",
                )
        elif noise_value <= config.NOISE_THRESHOLD - config.NOISE_HYSTERESIS:
            self._noise_above_since = None
            if self._noise_below_since is None:
                self._noise_below_since = current_time
            if (current_time - self._noise_below_since).total_seconds() >= config.NOISE_CLEAR_DURATION_SECONDS:
                self.database.resolve_alert(timestamp=timestamp, alert_type="noise_warning")
                self._set_bool_device(
                    timestamp=timestamp,
                    device="warning_led",
                    desired_state=False,
                    source="safety_rule",
                    trigger=None,
                )

    def _apply_comfort_control(self, timestamp: str, snapshot: dict[str, float], fsm_state: str) -> None:
        decision = self.llm_service.decide(
            snapshot=snapshot,
            fsm_state=fsm_state,
            profile_name=self.active_profile,
            weather=self.weather_service.get_current_weather(),
        )
        self.last_llm_decision = decision.reasoning
        decision_signature = (decision.lighting_brightness, decision.fan_state, fsm_state)
        if decision_signature != self._last_decision_signature:
            self.database.log_llm_decision(
                timestamp=timestamp,
                fsm_state=fsm_state,
                reasoning=decision.reasoning,
                actions={
                    "lighting_brightness": decision.lighting_brightness,
                    "fan_state": decision.fan_state,
                    "source": decision.source,
                },
            )
            self._last_decision_signature = decision_signature

        if self.device_status["lighting_led"]["mode"] == "auto":
            self._set_lighting(
                timestamp=timestamp,
                brightness=decision.lighting_brightness,
                source=decision.source,
            )
        if self.device_status["fan"]["mode"] == "auto":
            self._set_bool_device(
                timestamp=timestamp,
                device="fan",
                desired_state=decision.fan_state,
                source=decision.source,
                trigger=fsm_state.lower(),
            )

    def _set_lighting(self, timestamp: str, brightness: int, source: str) -> None:
        desired_state = brightness > 0
        current = self.device_status["lighting_led"]
        if current["brightness"] == brightness and current["state"] == desired_state:
            return
        current["brightness"] = brightness
        current["state"] = desired_state
        analog_value = round(brightness / 100.0 * config.LIGHTING_ANALOG_MAX, 2)
        self._write_obix_value(
            device="lighting_led",
            value=analog_value,
            source=source,
            event_action="set_brightness",
            event_value={"brightness": brightness, "analog_value": analog_value},
        )

    def _set_bool_device(
        self,
        timestamp: str,
        device: str,
        desired_state: bool,
        source: str,
        trigger: str | None,
    ) -> None:
        current = self.device_status[device]
        if current["state"] == desired_state and current.get("trigger") == trigger:
            return
        current["state"] = desired_state
        if "trigger" in current:
            current["trigger"] = trigger
        self._write_obix_value(
            device=device,
            value=desired_state,
            source=source,
            event_action="on" if desired_state else "off",
            event_value={"state": desired_state, "trigger": trigger},
        )

    def _write_obix_value(
        self,
        device: str,
        value: Any,
        source: str,
        event_action: str,
        event_value: Any,
    ) -> None:
        point_meta = config.DEVICE_POINTS[device]
        try:
            if not config.SIMULATION_MODE:
                self.obix_client.write_point(
                    point_name=point_meta["point_name"],
                    value=value,
                    kind=point_meta["kind"],
                )
            self.last_write_error = ""
        except Exception as exc:
            self.last_write_error = str(exc)
            self.degraded = True
        finally:
            self.database.log_device_event(
                timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                device_name=device,
                action=event_action,
                value=event_value,
                source=source,
            )
