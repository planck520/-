from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass
class ControlDecision:
    lighting_brightness: int
    fan_state: bool
    reasoning: str
    source: str


class LLMService:
    def decide(
        self,
        snapshot: dict[str, float],
        fsm_state: str,
        profile_name: str,
        weather: dict | None = None,
    ) -> ControlDecision:
        profile = config.PROFILES[profile_name]
        if fsm_state == "VACANT":
            return ControlDecision(
                lighting_brightness=0,
                fan_state=False,
                reasoning="空间当前判定为无人状态，关闭照明和风扇以降低能耗。",
                source="fsm_fallback",
            )

        brightness = profile["lighting_brightness"] if snapshot["light"] < profile["light_on_below_lux"] else 0
        fan_state = snapshot["temperature"] >= profile["fan_on_above_c"] or snapshot["co2"] >= config.CO2_COMFORT_MAX

        weather_text = ""
        if weather and weather.get("enabled"):
            weather_text = f" 室外天气为{weather.get('condition', '未知')}，室外温度约{weather.get('temperature', '未知')}°C。"

        reasoning = (
            f"当前处于 {fsm_state} 状态，采用 {profile_name} 模式。"
            f"室内光照 {snapshot['light']:.1f} Lux，照明建议 {brightness}% 。"
            f"室内温度 {snapshot['temperature']:.1f}°C、CO2 {snapshot['co2']:.1f} ppm，"
            f"{'建议开启' if fan_state else '建议关闭'}风扇。"
            f"{weather_text}"
        )

        if config.LLM_ENABLED and config.LLM_API_KEY:
            reasoning += " 已检测到 LLM 配置，但当前初始版本仍默认采用规则回退控制。"

        return ControlDecision(
            lighting_brightness=int(max(0, min(100, brightness))),
            fan_state=bool(fan_state),
            reasoning=reasoning,
            source="fsm_fallback",
        )
