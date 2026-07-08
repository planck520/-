from __future__ import annotations

import threading
import time
from datetime import datetime
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
                timestamp, snapshot, meta = self.sensor_collector.collect()
                previous_state, current_state, score = self.occupancy_detector.evaluate(snapshot)
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

    def get_system_status(self) -> dict[str, Any]:
        with self._lock:
            fsm_state = self._fsm_state
            fsm_score = self._fsm_score
        control_state = self.device_controller.get_system_control_state()
        return {
            "fsm_state": fsm_state,
            "fsm_score": fsm_score,
            "ai_mode": control_state["ai_mode"],
            "active_profile": control_state["active_profile"],
            "last_llm_decision": control_state["last_llm_decision"],
            "degraded": control_state["degraded"],
            "uptime_seconds": int(time.time() - self.started_at),
        }

    def set_profile(self, profile: str) -> None:
        self.device_controller.set_profile(profile)

    def get_energy_summary(self, range_name: str) -> dict[str, Any]:
        return self.database.get_energy_summary(range_name=range_name)

    def get_active_alerts(self) -> list[dict[str, Any]]:
        return self.database.get_active_alerts()

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


def main() -> None:
    from web_server import create_app

    runtime = BackendRuntime()
    runtime.start()
    app = create_app(runtime)
    app.run(host=config.HOST, port=config.PORT, debug=False)


if __name__ == "__main__":
    main()
