from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

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
        simulation_mode_provider: Callable[[], bool] | None = None,
    ) -> None:
        self.obix_client = obix_client
        self.database = database
        self.llm_service = llm_service
        self.weather_service = weather_service
        self._simulation_mode_provider = simulation_mode_provider or (lambda: config.SIMULATION_MODE)
        self.active_profile = config.DEFAULT_PROFILE
        self.device_status = {
            "buzzer": {"state": False, "trigger": None, "mode": "auto"},
            "warning_led": {"state": False, "trigger": None, "mode": "auto"},
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
        self._last_comfort_source = "fsm_fallback"
        self._last_lighting_write: int | None = None

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
        manual_devices = [
            name
            for name, status in self.device_status.items()
            if status.get("mode") == "manual"
        ]
        if self.database.get_active_alerts():
            self.ai_mode = "emergency_override"
        elif manual_devices:
            self.ai_mode = "manual_override"
        elif self._last_comfort_source == "llm_advice":
            self.ai_mode = "llm_advice"
        else:
            self.ai_mode = "fsm_fallback"
        self.database.log_fsm_state(timestamp=timestamp, state=fsm_state, score=fsm_score)

    def get_device_status(self) -> dict[str, Any]:
        return self.device_status

    def get_system_control_state(self) -> dict[str, Any]:
        return {
            "active_profile": self.active_profile,
            "active_profile_config": config.PROFILES[self.active_profile],
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
            if action == "auto":
                self.device_status[device]["mode"] = "auto"
                return self.device_status[device]
            if action not in {"on", "off"}:
                raise ValueError("Unsupported action")
            desired_state = action == "on"
            self.device_status[device]["mode"] = "manual"
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
            if self.device_status["buzzer"]["mode"] == "auto":
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
                if self.device_status["buzzer"]["mode"] == "auto":
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
                if self.device_status["warning_led"]["mode"] == "auto":
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
                if self.device_status["warning_led"]["mode"] == "auto":
                    self._set_bool_device(
                        timestamp=timestamp,
                        device="warning_led",
                        desired_state=False,
                        source="safety_rule",
                        trigger=None,
                    )

    def _apply_comfort_control(self, timestamp: str, snapshot: dict[str, float], fsm_state: str) -> None:
        profile = config.PROFILES[self.active_profile]
        if fsm_state == "VACANT":
            rule_brightness = 0
            rule_fan_state = False
        else:
            rule_brightness = self._rule_lighting_brightness(snapshot=snapshot, profile=profile)
            rule_fan_state = self._guard_fan_state(
                current_state=self.device_status["fan"]["state"],
                snapshot=snapshot,
                profile=profile,
            )

        if self.device_status["lighting_led"]["mode"] == "auto":
            self._set_lighting(
                timestamp=timestamp,
                brightness=rule_brightness,
                source="local_rule",
            )
        if self.device_status["fan"]["mode"] == "auto":
            self._set_bool_device(
                timestamp=timestamp,
                device="fan",
                desired_state=rule_fan_state,
                source="local_rule",
                trigger=fsm_state.lower(),
            )

        advice = self.llm_service.decide(
            snapshot=snapshot,
            fsm_state=fsm_state,
            profile_name=self.active_profile,
            weather=self.weather_service.get_current_weather(),
        )
        self.last_llm_decision = (
            f"{advice.reasoning} 本地规则实际执行：照明 {rule_brightness}%，"
            f"风扇{'开启' if rule_fan_state else '关闭'}。LLM 仅作为天气/环境建议，不直接控制硬件。"
        )
        self._last_comfort_source = "llm_advice" if advice.source == "llm" else "fsm_fallback"
        decision_signature = (rule_brightness, rule_fan_state, fsm_state)
        if decision_signature != self._last_decision_signature:
            self.database.log_llm_decision(
                timestamp=timestamp,
                fsm_state=fsm_state,
                reasoning=self.last_llm_decision,
                actions={
                    "lighting_brightness": rule_brightness,
                    "fan_state": rule_fan_state,
                    "source": "local_rule",
                    "llm_advice_source": advice.source,
                    "llm_advice_only": True,
                },
            )
            self._last_decision_signature = decision_signature

    def _rule_lighting_brightness(self, snapshot: dict[str, float], profile: dict[str, Any]) -> int:
        if snapshot["light"] >= profile["light_on_below_lux"]:
            return 0
        return int(max(0, min(100, profile["lighting_brightness"])))

    def _guard_fan_state(
        self,
        current_state: bool,
        snapshot: dict[str, float],
        profile: dict[str, Any],
    ) -> bool:
        temperature = snapshot["temperature"]
        co2 = snapshot["co2"]
        temp_on = profile["fan_on_above_c"]
        temp_off = temp_on - config.FAN_TEMP_HYSTERESIS

        if temperature >= temp_on or co2 >= config.CO2_COMFORT_MAX:
            return True
        if temperature <= temp_off and co2 <= config.CO2_FAN_OFF_BELOW:
            return False
        return bool(current_state)

    def _set_lighting(self, timestamp: str, brightness: int, source: str) -> None:
        desired_state = brightness > 0
        current = self.device_status["lighting_led"]
        if (
            self._last_lighting_write == brightness
            and current["brightness"] == brightness
            and current["state"] == desired_state
        ):
            return
        current["brightness"] = brightness
        current["state"] = desired_state
        analog_value = round(brightness / 100.0 * config.LIGHTING_ANALOG_MAX, 2)
        point_meta = config.DEVICE_POINTS["lighting_led"]
        if self._write_obix_value(
            device="lighting_led",
            value=analog_value,
            source=source,
            event_action="set_brightness",
            event_value={
                "brightness": brightness,
                "analog_value": analog_value,
                "physical_value": analog_value,
                "point_kind": point_meta["kind"],
            },
        ):
            self._last_lighting_write = brightness

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
    ) -> bool:
        point_meta = config.DEVICE_POINTS[device]
        try:
            if not self._simulation_mode_provider() and point_meta.get("installed", True):
                self.obix_client.write_point(
                    point_name=point_meta["point_name"],
                    value=value,
                    kind=point_meta["kind"],
                )
            self.last_write_error = ""
            return True
        except Exception as exc:
            self.last_write_error = str(exc)
            self.degraded = True
            return False
        finally:
            self.database.log_device_event(
                timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                device_name=device,
                action=event_action,
                value=event_value,
                source=source,
            )
