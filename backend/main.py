from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Any

import config
from database_manager import DatabaseManager
from device_controller import DeviceController
from llm_service import LLMService
from obix_client import ObixClient
from occupancy_detector import OccupancyDetector
from sensor_data_collector import SensorDataCollector
from weather_service import WeatherService


class BackendRuntime:
    def __init__(self) -> None:
        self.database = DatabaseManager(config.DATABASE_PATH)
        self.obix_client = ObixClient()
        self.weather_service = WeatherService()
        self.llm_service = LLMService()
        self.sensor_collector = SensorDataCollector(self.obix_client)
        self.occupancy_detector = OccupancyDetector()
        self.device_controller = DeviceController(
            obix_client=self.obix_client,
            database=self.database,
            llm_service=self.llm_service,
            weather_service=self.weather_service,
        )
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._latest_timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self._latest_snapshot = self.sensor_collector._collect_simulated()
        self._fsm_state = "VACANT"
        self._fsm_score = 0.0
        self._fsm_override_state: str | None = None
        self._demo_mode_override: bool | None = None
        self._shortcut_history: list[dict[str, Any]] = []
        self._collector_meta = {"source": "simulation"}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop_error: str | None = None
        self._successful_polls = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="sensor-loop")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                timestamp, snapshot, meta = self._collect_for_active_mode()
                previous_state, current_state, score = self.occupancy_detector.evaluate(snapshot)
                with self._lock:
                    override_state = self._fsm_override_state
                if override_state is not None:
                    previous_state = self._fsm_state
                    current_state = override_state
                    self.occupancy_detector.fsm.state = override_state
                    score = self._fsm_score
                self.database.insert_sensor_snapshot(timestamp=timestamp, readings=snapshot)
                self.device_controller.update(
                    timestamp=timestamp,
                    snapshot=snapshot,
                    fsm_state=current_state,
                    fsm_score=score,
                    data_source=meta.get("source", "simulation"),
                )
                with self._lock:
                    self._latest_timestamp = timestamp
                    self._latest_snapshot = snapshot
                    self._fsm_state = current_state
                    self._fsm_score = score
                    self._collector_meta = meta
                    self._successful_polls += 1
                    self._loop_error = None
                if previous_state != current_state:
                    pass
                self._stop_event.wait(config.POLL_INTERVAL_SECONDS)
        except Exception as exc:
            with self._lock:
                self._loop_error = str(exc)

    def _collect_for_active_mode(self) -> tuple[str, dict[str, float], dict[str, str]]:
        with self._lock:
            demo_override = self._demo_mode_override

        if demo_override is True:
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            return timestamp, self.sensor_collector._collect_simulated(), {
                "source": "simulation",
                "demo_override": "true",
            }

        if demo_override is False and config.SIMULATION_MODE:
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            readings = self.sensor_collector._collect_from_obix()
            return timestamp, readings, {"source": "obix", "demo_override": "false"}

        return self.sensor_collector.collect()

    def get_latest_sensor_payload(self) -> dict[str, Any]:
        with self._lock:
            timestamp = self._latest_timestamp
            snapshot = self._latest_snapshot.copy()
        return {
            "timestamp": timestamp,
            "data": {
                sensor_name: {
                    "value": snapshot[sensor_name],
                    "unit": config.SENSORS[sensor_name]["unit"],
                }
                for sensor_name in config.SENSORS
            },
        }

    def get_sensor_history(self, sensor: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self.database.get_sensor_history(sensor_name=sensor, start=start, end=end)

    def get_device_status(self) -> dict[str, Any]:
        return self.device_controller.get_device_status()

    def control_device(self, device: str, action: str, value: Any = None) -> dict[str, Any]:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        return self.device_controller.manual_control(
            timestamp=timestamp,
            device=device,
            action=action,
            value=value,
        )

    def get_profiles(self) -> dict[str, Any]:
        return {
            "active_profile": self.device_controller.active_profile,
            "profiles": config.PROFILES,
        }

    def get_system_status(self) -> dict[str, Any]:
        with self._lock:
            fsm_state = self._fsm_state
            fsm_score = self._fsm_score
            fsm_override_state = self._fsm_override_state
            demo_mode_override = self._demo_mode_override
        control_state = self.device_controller.get_system_control_state()
        return {
            "fsm_state": fsm_state,
            "fsm_score": fsm_score,
            "fsm_override_state": fsm_override_state,
            "ai_mode": control_state["ai_mode"],
            "active_profile": control_state["active_profile"],
            "active_profile_config": control_state["active_profile_config"],
            "last_llm_decision": control_state["last_llm_decision"],
            "degraded": control_state["degraded"],
            "demo_mode": self._effective_simulation_mode(),
            "demo_mode_override": demo_mode_override,
            "uptime_seconds": int(time.time() - self.started_at),
        }

    def set_profile(self, profile: str) -> None:
        self.device_controller.set_profile(profile)

    def get_energy_summary(self, range_name: str) -> dict[str, Any]:
        return self.database.get_energy_summary(range_name=range_name)

    def get_energy_timeseries(self, range_name: str) -> dict[str, Any]:
        return self.database.get_energy_timeseries(range_name=range_name)

    def get_device_events(self, limit: int = 50, device_name: str | None = None) -> list[dict[str, Any]]:
        return self.database.get_device_events(limit=limit, device_name=device_name)

    def get_active_alerts(self) -> list[dict[str, Any]]:
        return self.database.get_active_alerts()

    def get_shortcut_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "fsm_override_state": self._fsm_override_state,
                "demo_mode": self._effective_simulation_mode(),
                "demo_mode_override": self._demo_mode_override,
                "available_actions": [
                    "set_fsm",
                    "clear_fsm",
                    "trigger_alert",
                    "clear_alert",
                    "control_device",
                    "set_demo_mode",
                    "toggle_demo_mode",
                ],
                "history": list(reversed(self._shortcut_history[-20:])),
            }

    def apply_shortcut_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

        if action == "set_fsm":
            state = str(payload.get("state", "")).upper()
            if state not in {"VACANT", "ARRIVING", "OCCUPIED", "LEAVING"}:
                raise ValueError("Unsupported FSM state")
            score_map = {"VACANT": 0.0, "ARRIVING": 0.45, "OCCUPIED": 0.85, "LEAVING": 0.35}
            with self._lock:
                self._fsm_override_state = state
                self._fsm_state = state
                self._fsm_score = score_map[state]
                self.occupancy_detector.fsm.state = state
            self.database.log_fsm_state(timestamp=timestamp, state=state, score=score_map[state])
            self._apply_demo_fsm_controls(timestamp=timestamp, fsm_state=state, fsm_score=score_map[state])
            result = {
                "fsm_override_state": state,
                "fsm_state": state,
                "fsm_score": score_map[state],
                "device_status": self.get_device_status(),
            }
        elif action == "clear_fsm":
            with self._lock:
                self._fsm_override_state = None
            result = {"fsm_override_state": None, "fsm_state": self.get_system_status()["fsm_state"]}
        elif action == "trigger_alert":
            alert_type = str(payload.get("type", "smoke_warning"))
            result = self._trigger_demo_alert(timestamp=timestamp, alert_type=alert_type)
        elif action == "clear_alert":
            alert_type = payload.get("type")
            result = self._clear_demo_alert(timestamp=timestamp, alert_type=alert_type)
        elif action == "control_device":
            device = str(payload.get("device", ""))
            device_action = str(payload.get("device_action", ""))
            value = payload.get("value")
            if not device or not device_action:
                raise ValueError("device and device_action are required")
            result = self.control_device(device=device, action=device_action, value=value)
            result = {"device": device, "device_status": result}
        elif action == "set_demo_mode":
            enabled = bool(payload.get("enabled"))
            with self._lock:
                self._demo_mode_override = enabled
            result = {"demo_mode": self._effective_simulation_mode(), "demo_mode_override": enabled}
        elif action == "toggle_demo_mode":
            with self._lock:
                current = self._effective_simulation_mode()
                self._demo_mode_override = not current
            result = {"demo_mode": self._effective_simulation_mode(), "demo_mode_override": self._demo_mode_override}
        else:
            raise ValueError("Unsupported shortcut action")

        self._record_shortcut(timestamp=timestamp, action=action, payload=payload, result=result)
        return {"success": True, "action": action, **result, "shortcut_state": self.get_shortcut_state()}

    def get_assistant_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.database.get_assistant_messages(limit=limit)

    def chat_with_assistant(self, message: str) -> dict[str, Any]:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        context = self._build_assistant_context()
        self.database.log_assistant_message(
            timestamp=timestamp,
            role="user",
            message=message,
            context=context,
        )
        answer = self.llm_service.chat(
            message=message,
            context=context,
            history=self.database.get_assistant_messages(limit=12),
        )
        response_timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self.database.log_assistant_message(
            timestamp=response_timestamp,
            role="assistant",
            message=answer,
            context=context,
        )
        return {
            "timestamp": response_timestamp,
            "message": answer,
            "context": context,
            "source": "rule_context_assistant",
        }

    def stream_assistant_response(self, message: str):
        response = self.chat_with_assistant(message)
        for token in self.llm_service.stream_tokens(response["message"]):
            yield token

    def _build_assistant_context(self) -> dict[str, Any]:
        latest = self.get_latest_sensor_payload()
        system = self.get_system_status()
        end = datetime.now().astimezone()
        start = end - timedelta(minutes=10)
        recent_history = {}
        for sensor in ("temperature", "humidity", "light", "co2", "noise", "smoke", "pm25"):
            recent_history[sensor] = self.get_sensor_history(sensor=sensor, start=start, end=end)
        return {
            "latest_sensor_payload": latest,
            "system_status": system,
            "device_status": self.get_device_status(),
            "active_alerts": self.get_active_alerts(),
            "energy_summary": self.get_energy_summary("day"),
            "recent_history": recent_history,
            "weather": self.weather_service.get_current_weather(),
        }

    def get_collector_meta(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._collector_meta)

    def read_physical_device_states(self) -> dict[str, Any]:
        if config.SIMULATION_MODE:
            return {"mode": "simulation", "states": self.get_device_status()}
        return {"mode": "obix", "states": self.obix_client.read_device_points()}

    def get_runtime_diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "loop_error": self._loop_error,
                "successful_polls": self._successful_polls,
                "thread_alive": bool(self._thread and self._thread.is_alive()),
            }

    def ensure_healthy(self) -> None:
        diagnostics = self.get_runtime_diagnostics()
        if diagnostics["loop_error"]:
            raise RuntimeError(diagnostics["loop_error"])
        if not diagnostics["thread_alive"]:
            raise RuntimeError("Background collector thread is not running")

    def _effective_simulation_mode(self) -> bool:
        return config.SIMULATION_MODE if self._demo_mode_override is None else self._demo_mode_override

    def _record_shortcut(
        self,
        timestamp: str,
        action: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        entry = {
            "timestamp": timestamp,
            "action": action,
            "payload": payload,
            "result": result,
        }
        with self._lock:
            self._shortcut_history.append(entry)
            self._shortcut_history = self._shortcut_history[-100:]

    def _trigger_demo_alert(self, timestamp: str, alert_type: str) -> dict[str, Any]:
        if alert_type == "smoke_warning":
            sensor_value = float(config.SMOKE_THRESHOLD + 20)
            self.database.open_alert(
                timestamp=timestamp,
                alert_type="smoke_warning",
                severity="critical",
                message="Demo smoke warning triggered by shortcut",
                sensor_value=sensor_value,
                threshold=config.SMOKE_THRESHOLD,
            )
            self.device_controller.manual_control(timestamp, "buzzer", "on")
        elif alert_type == "noise_warning":
            sensor_value = float(config.NOISE_THRESHOLD + 10)
            self.database.open_alert(
                timestamp=timestamp,
                alert_type="noise_warning",
                severity="warning",
                message="Demo noise warning triggered by shortcut",
                sensor_value=sensor_value,
                threshold=config.NOISE_THRESHOLD,
            )
            self.device_controller.manual_control(timestamp, "warning_led", "on")
        else:
            raise ValueError("Unsupported alert type")
        return {"active_alerts": self.get_active_alerts(), "device_status": self.get_device_status()}

    def _clear_demo_alert(self, timestamp: str, alert_type: Any = None) -> dict[str, Any]:
        alert_types = [str(alert_type)] if alert_type else ["smoke_warning", "noise_warning"]
        for item in alert_types:
            if item not in {"smoke_warning", "noise_warning"}:
                raise ValueError("Unsupported alert type")
            self.database.resolve_alert(timestamp=timestamp, alert_type=item)
        if not alert_type or alert_type == "smoke_warning":
            self.device_controller.manual_control(timestamp, "buzzer", "off")
            self.device_controller.manual_control(timestamp, "buzzer", "auto")
        if not alert_type or alert_type == "noise_warning":
            self.device_controller.manual_control(timestamp, "warning_led", "off")
            self.device_controller.manual_control(timestamp, "warning_led", "auto")
        return {"active_alerts": self.get_active_alerts(), "device_status": self.get_device_status()}

    def _apply_demo_fsm_controls(self, timestamp: str, fsm_state: str, fsm_score: float) -> None:
        self.device_controller.manual_control(timestamp, "lighting_led", "auto")
        self.device_controller.manual_control(timestamp, "fan", "auto")
        with self._lock:
            snapshot = self._latest_snapshot.copy()
            data_source = self._collector_meta.get("source", "simulation")
        self.device_controller.update(
            timestamp=timestamp,
            snapshot=snapshot,
            fsm_state=fsm_state,
            fsm_score=fsm_score,
            data_source=data_source,
        )


def main() -> None:
    from web_server import create_app

    runtime = BackendRuntime()
    runtime.start()
    app = create_app(runtime)
    app.run(host=config.HOST, port=config.PORT, debug=False)


if __name__ == "__main__":
    main()
