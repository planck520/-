from __future__ import annotations

import math
import random
import time
from datetime import datetime

import config
from obix_client import ObixClient


class SensorDataCollector:
    def __init__(self, obix_client: ObixClient) -> None:
        self.obix_client = obix_client
        self.random = random.Random(config.SIMULATION_SEED)
        self.last_source = "simulation" if config.SIMULATION_MODE else "obix"
        self.last_error = ""
        self.last_sensor_status = self._build_status(source=self.last_source, online=config.SIMULATION_MODE)

    def collect(self, previous_readings: dict[str, float] | None = None) -> tuple[str, dict[str, float], dict[str, object]]:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        if not config.SIMULATION_MODE:
            readings, status = self._collect_from_obix_partial(previous_readings=previous_readings)
            online_count = sum(1 for item in status.values() if item["online"])
            errors = {name: item["error"] for name, item in status.items() if item["error"]}

            if online_count:
                self.last_source = "obix"
                self.last_error = "; ".join(f"{name}: {err}" for name, err in errors.items())
                self.last_sensor_status = status
                meta: dict[str, object] = {"source": "obix", "sensor_status": status}
                if errors:
                    meta["partial_error"] = self.last_error
                return timestamp, readings, meta

            self.last_source = "error"
            self.last_error = "; ".join(f"{name}: {err}" for name, err in errors.items()) or "all oBIX sensor reads failed"
            self.last_sensor_status = status
            if config.STRICT_OBIX_MODE:
                raise RuntimeError(f"Failed to collect data from oBIX: {self.last_error}")
            readings = previous_readings.copy() if previous_readings else self._collect_simulated()
            return timestamp, readings, {
                "source": "error",
                "error": self.last_error,
                "sensor_status": status,
            }
        readings = self._collect_simulated()
        self.last_sensor_status = self._build_status(source="simulation", online=True)
        return timestamp, readings, {"source": "simulation", "sensor_status": self.last_sensor_status}

    def _collect_from_obix(self) -> dict[str, float]:
        readings: dict[str, float] = {}
        for sensor_name in config.RAW_SENSOR_KEYS:
            point_name = config.SENSORS[sensor_name]["point_name"]
            readings[sensor_name] = float(self.obix_client.read_point(point_name))
        readings["fan_power"] = round(readings["fan_current"] * config.FAN_VOLTAGE, 2)
        return readings

    def _collect_from_obix_partial(
        self,
        previous_readings: dict[str, float] | None = None,
    ) -> tuple[dict[str, float], dict[str, dict[str, object]]]:
        readings: dict[str, float] = previous_readings.copy() if previous_readings else self._collect_simulated()
        status: dict[str, dict[str, object]] = {}
        now = datetime.now().astimezone().isoformat(timespec="seconds")

        for sensor_name in config.RAW_SENSOR_KEYS:
            point_name = config.SENSORS[sensor_name]["point_name"]
            try:
                readings[sensor_name] = float(self.obix_client.read_point(point_name))
                status[sensor_name] = {
                    "online": True,
                    "source": "obix",
                    "point_name": point_name,
                    "updated_at": now,
                    "error": "",
                }
            except Exception as exc:
                status[sensor_name] = {
                    "online": False,
                    "source": "obix",
                    "point_name": point_name,
                    "updated_at": now,
                    "error": str(exc),
                }

        fan_current_ok = bool(status.get("fan_current", {}).get("online"))
        if fan_current_ok:
            readings["fan_power"] = round(readings["fan_current"] * config.FAN_VOLTAGE, 2)
        status["fan_power"] = {
            "online": fan_current_ok,
            "source": "derived",
            "point_name": config.SENSORS["fan_power"]["point_name"],
            "updated_at": now,
            "error": "" if fan_current_ok else "fan_current offline",
        }
        return readings, status

    def _build_status(self, source: str, online: bool) -> dict[str, dict[str, object]]:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        return {
            sensor_name: {
                "online": online,
                "source": source,
                "point_name": meta["point_name"],
                "updated_at": now,
                "error": "",
            }
            for sensor_name, meta in config.SENSORS.items()
        }

    def _collect_simulated(self) -> dict[str, float]:
        tick = time.time() / 60.0
        occupied = int(tick) % 10 < 6
        base_light = 180.0 if occupied else 380.0
        temperature = 25.0 + math.sin(tick / 3.0) * 1.8 + (1.2 if occupied else -0.2)
        humidity = 56.0 + math.sin(tick / 5.0) * 6.0 + (2.0 if occupied else -1.0)
        light = base_light + math.sin(tick * 2.0) * 35.0 + self.random.uniform(-10.0, 10.0)
        co2 = 520.0 + (260.0 if occupied else 40.0) + math.sin(tick) * 30.0
        noise = 38.0 + (14.0 if occupied else 3.0) + abs(math.sin(tick * 3.0)) * 6.0
        smoke = 8.0 + abs(math.sin(tick / 2.5)) * 4.0
        pm25 = 20.0 + (18.0 if occupied else 4.0) + abs(math.sin(tick / 1.7)) * 8.0
        fan_should_run = (
            temperature >= config.PROFILES[config.DEFAULT_PROFILE]["fan_on_above_c"]
            or co2 >= config.CO2_COMFORT_MAX
        )
        fan_current = 0.34 if fan_should_run else 0.0
        fan_power = fan_current * config.FAN_VOLTAGE
        return {
            "temperature": round(temperature, 2),
            "humidity": round(humidity, 2),
            "light": round(max(0.0, light), 2),
            "co2": round(co2, 2),
            "noise": round(noise, 2),
            "smoke": round(smoke, 2),
            "pm25": round(pm25, 2),
            "fan_current": round(fan_current, 2),
            "fan_power": round(fan_power, 2),
        }
