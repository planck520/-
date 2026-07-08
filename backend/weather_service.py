from __future__ import annotations

import json
import time
from urllib import error, parse, request

import config


class WeatherService:
    def __init__(self) -> None:
        self._cache: dict | None = None
        self._cache_until = 0.0

    def get_current_weather(self) -> dict:
        now = time.time()
        if self._cache is not None and now < self._cache_until:
            return self._cache

        if not config.WEATHER_API_KEY:
            self._cache = {
                "enabled": False,
                "source": "disabled",
                "message": "WEATHER_API_KEY 未配置",
            }
            self._cache_until = now + config.WEATHER_CACHE_SECONDS
            return self._cache

        try:
            query = parse.urlencode(
                {"q": config.WEATHER_CITY, "appid": config.WEATHER_API_KEY, "units": "metric"}
            )
            with request.urlopen(f"{config.WEATHER_API_BASE}?{query}", timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self._cache = {
                "enabled": True,
                "source": "openweather",
                "temperature": payload.get("main", {}).get("temp"),
                "humidity": payload.get("main", {}).get("humidity"),
                "condition": payload.get("weather", [{}])[0].get("description"),
                "city": payload.get("name") or config.WEATHER_CITY,
            }
        except error.HTTPError as exc:
            self._cache = {
                "enabled": False,
                "source": "openweather_error",
                "status": exc.code,
                "message": self._read_http_error(exc),
            }
        except error.URLError as exc:
            self._cache = {
                "enabled": False,
                "source": "network_error",
                "message": str(exc.reason),
            }
        except TimeoutError:
            self._cache = {
                "enabled": False,
                "source": "timeout",
                "message": "OpenWeather 请求超时",
            }
        except json.JSONDecodeError:
            self._cache = {
                "enabled": False,
                "source": "bad_response",
                "message": "OpenWeather 返回内容无法解析",
            }

        self._cache_until = now + config.WEATHER_CACHE_SECONDS
        return self._cache

    @staticmethod
    def _read_http_error(exc: error.HTTPError) -> str:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return f"OpenWeather HTTP {exc.code}"
        return payload.get("message") or f"OpenWeather HTTP {exc.code}"
