from __future__ import annotations

import os
from pathlib import Path


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value.strip()
    return default


def _env_bool(*names: str, default: bool = False) -> bool:
    raw = _env(*names, default=str(default).lower())
    return raw.lower() in {"1", "true", "yes", "on"}


def _is_placeholder_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"192.168.x.x", "<jace_ip>", "jace_ip", "localhost"}


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "cloud_controller.db"

HOST = _env("IOT_HOST", "HOST", default="0.0.0.0")
PORT = int(_env("IOT_PORT", "PORT", default="5000"))
POLL_INTERVAL_SECONDS = float(_env("POLL_INTERVAL_SECONDS", default="2"))

OBIX_IP = _env("OBIX_IP", "JACE_IP", "JACE8000_IP", default="192.168.1.140")
OBIX_PORT = int(_env("OBIX_PORT", "JACE_PORT", default="443"))
OBIX_USE_HTTPS = _env_bool("OBIX_USE_HTTPS", "JACE_USE_HTTPS", default=True)
OBIX_USERNAME = _env("OBIX_USERNAME", "OBIX_USER", "JACE_USERNAME", default="obixuser")
OBIX_PASSWORD = _env("OBIX_PASSWORD", "OBIX_PASS", "JACE_PASSWORD", default="ADmin12345")
OBIX_ROOT_PATH = _env("OBIX_ROOT_PATH", default="/obix")
OBIX_STATION_NAME = _env("OBIX_STATION_NAME", "STATION_NAME", "NIAGARA_STATION_NAME", default="Test230616")
OBIX_TIMEOUT_SECONDS = float(_env("OBIX_TIMEOUT_SECONDS", default="4"))
OBIX_VERIFY_SSL = _env_bool("OBIX_VERIFY_SSL", default=False)

_HAS_REAL_OBIX_CONFIG = not _is_placeholder_host(OBIX_IP)
SIMULATION_MODE = _env_bool("SIMULATION_MODE", default=not _HAS_REAL_OBIX_CONFIG)
SIMULATION_SEED = int(_env("SIMULATION_SEED", default="20260707"))
STRICT_OBIX_MODE = _env_bool("STRICT_OBIX_MODE", default=not SIMULATION_MODE)

WEATHER_API_KEY = _env("WEATHER_API_KEY", "OPENWEATHER_API_KEY")
WEATHER_CITY = _env("WEATHER_CITY", default="Wuhan,cn")
WEATHER_API_BASE = _env("WEATHER_API_BASE", default="https://api.openweathermap.org/data/2.5/weather")
WEATHER_CACHE_SECONDS = int(_env("WEATHER_CACHE_SECONDS", default="600"))

LLM_ENABLED = _env_bool("LLM_ENABLED", default=False)
LLM_MODEL = _env("LLM_MODEL", default="deepseek-chat")
LLM_BASE_URL = _env("LLM_BASE_URL")
LLM_API_KEY = _env("LLM_API_KEY", "DEEPSEEK_API_KEY")

DEFAULT_PROFILE = _env("DEFAULT_PROFILE", default="balanced")
FAN_VOLTAGE = float(_env("FAN_VOLTAGE", default="24.0"))
FAN_ALWAYS_ON_POWER_W = float(_env("FAN_ALWAYS_ON_POWER_W", default="24.0"))
CARBON_EMISSION_FACTOR_KG_PER_KWH = float(
    _env("CARBON_EMISSION_FACTOR_KG_PER_KWH", default="0.7")
)
LIGHTING_ANALOG_MAX = float(_env("LIGHTING_ANALOG_MAX", default="10.0"))

SMOKE_THRESHOLD = float(_env("SMOKE_THRESHOLD", default="150"))
SMOKE_HYSTERESIS = float(_env("SMOKE_HYSTERESIS", default="20"))
SMOKE_CLEAR_DELAY_SECONDS = int(_env("SMOKE_CLEAR_DELAY_SECONDS", default="5"))
NOISE_THRESHOLD = float(_env("NOISE_THRESHOLD", default="55"))
NOISE_HYSTERESIS = float(_env("NOISE_HYSTERESIS", default="3"))
NOISE_DURATION_SECONDS = int(_env("NOISE_DURATION_SECONDS", default="3"))
NOISE_CLEAR_DURATION_SECONDS = int(_env("NOISE_CLEAR_DURATION_SECONDS", default="10"))
CO2_COMFORT_MAX = float(_env("CO2_COMFORT_MAX", default="1000"))

FSM_ENTER_OCCUPIED = float(_env("FSM_ENTER_OCCUPIED", default="0.70"))
FSM_EXIT_OCCUPIED = float(_env("FSM_EXIT_OCCUPIED", default="0.30"))
FSM_ENTER_ARRIVING = float(_env("FSM_ENTER_ARRIVING", default="0.40"))
FSM_ENTER_LEAVING = float(_env("FSM_ENTER_LEAVING", default="0.50"))

OCCUPANCY_SCORE_RANGES = {
    "co2": (450.0, 1200.0),
    "noise": (30.0, 70.0),
    "temp_delta": (0.0, 1.5),
    "humidity_delta": (0.0, 8.0),
    "pm25": (0.0, 120.0),
    "light_delta": (0.0, 350.0),
}

FSM_WEIGHTS = {
    "co2": 0.35,
    "noise": 0.20,
    "temp_delta": 0.15,
    "humidity_delta": 0.10,
    "pm25": 0.10,
    "light_delta": 0.10,
}

SENSORS = {
    "temperature": {"point_name": "室内温度", "unit": "°C", "raw": True},
    "humidity": {"point_name": "室内湿度", "unit": "%RH", "raw": True},
    "light": {"point_name": "光照强度", "unit": "Lux", "raw": True},
    "co2": {"point_name": "CO2浓度", "unit": "ppm", "raw": True},
    "noise": {"point_name": "噪声传感器", "unit": "dB", "raw": True},
    "smoke": {"point_name": "烟雾传感器", "unit": "ppm", "raw": True},
    "pm25": {"point_name": "PM2.5浓度", "unit": "µg/m³", "raw": True},
    "fan_current": {"point_name": "风扇电流（功率）", "unit": "A", "raw": True},
    "fan_power": {"point_name": "风扇电流（功率）", "unit": "W", "raw": False},
}

RAW_SENSOR_KEYS = [name for name, meta in SENSORS.items() if meta["raw"]]

DEVICE_POINTS = {
    "buzzer": {"point_name": "警示LED开关", "kind": "bool"},
    "warning_led": {"point_name": "警示LED开关", "kind": "bool"},
    "lighting_led": {"point_name": "照明LED", "kind": "real"},
    "fan": {"point_name": "风扇开关", "kind": "bool"},
}

PROFILES = {
    "energy_saving": {
        "fan_on_above_c": 28.0,
        "light_on_below_lux": 200.0,
        "lighting_brightness": 50,
    },
    "comfort": {
        "fan_on_above_c": 24.0,
        "light_on_below_lux": 500.0,
        "lighting_brightness": 80,
    },
    "balanced": {
        "fan_on_above_c": 26.0,
        "light_on_below_lux": 300.0,
        "lighting_brightness": 60,
    },
}

ENERGY_RANGE_TO_HOURS = {
    "hour": 1,
    "day": 24,
    "week": 24 * 7,
}


