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
            self._cache = {"enabled": False, "source": "disabled"}
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
            }
        except (error.URLError, TimeoutError, json.JSONDecodeError):
            self._cache = {"enabled": False, "source": "fallback"}

        self._cache_until = now + config.WEATHER_CACHE_SECONDS
        return self._cache
