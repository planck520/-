from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib import error, request

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

        fallback = self._fallback_decide(
            snapshot=snapshot,
            fsm_state=fsm_state,
            profile_name=profile_name,
            weather=weather,
            fallback_note=None,
        )
        if fsm_state not in {"ARRIVING", "OCCUPIED"}:
            return fallback
        if not config.LLM_ENABLED or not config.LLM_API_KEY:
            return fallback

        try:
            return self._llm_decide(
                snapshot=snapshot,
                fsm_state=fsm_state,
                profile_name=profile_name,
                profile=profile,
                weather=weather,
            )
        except Exception as exc:
            return self._fallback_decide(
                snapshot=snapshot,
                fsm_state=fsm_state,
                profile_name=profile_name,
                weather=weather,
                fallback_note=f"LLM 不可用，已降级为本地规则：{exc}",
            )

    def _llm_decide(
        self,
        snapshot: dict[str, float],
        fsm_state: str,
        profile_name: str,
        profile: dict[str, Any],
        weather: dict | None,
    ) -> ControlDecision:
        response = self._post_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是图书馆物联网舒适性控制助手。只为照明和风扇给出舒适性建议，"
                        "不要处理烟雾、噪声等安全动作；安全动作由后端规则独立执行。"
                        "必须只输出一个 JSON 对象，不要 Markdown。JSON schema: "
                        '{"lighting_brightness":0-100整数,"fan_state":true或false,'
                        '"reasoning":"中文简短理由"}。'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "fsm_state": fsm_state,
                            "profile_name": profile_name,
                            "profile": profile,
                            "sensors": snapshot,
                            "weather": weather or {"enabled": False},
                            "rules": {
                                "vacant_already_handled_locally": True,
                                "co2_comfort_max": config.CO2_COMFORT_MAX,
                                "output_lighting_brightness_percent": "0-100",
                                "output_fan_state": "boolean",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        content = response["choices"][0]["message"]["content"]
        payload = self._parse_json_object(content)

        brightness = int(payload["lighting_brightness"])
        fan_state = bool(payload["fan_state"])
        reasoning = str(payload.get("reasoning", "")).strip()
        if not reasoning:
            raise ValueError("LLM response missing reasoning")

        requested_brightness = brightness
        brightness = self._guard_lighting_brightness(
            requested_brightness=brightness,
            current_lux=snapshot["light"],
            threshold_lux=profile["light_on_below_lux"],
        )
        if brightness == 0 and requested_brightness > 0:
            reasoning = (
                f"{reasoning} 后端照度保护：当前 {snapshot['light']:.1f} Lux "
                f"已高于 {profile['light_on_below_lux']:.0f} Lux 补光阈值，强制关闭照明。"
            )

        return ControlDecision(
            lighting_brightness=int(max(0, min(100, brightness))),
            fan_state=fan_state,
            reasoning=f"LLM 大模型建议：{reasoning}",
            source="llm",
        )

    def _fallback_decide(
        self,
        snapshot: dict[str, float],
        fsm_state: str,
        profile_name: str,
        weather: dict | None,
        fallback_note: str | None,
    ) -> ControlDecision:
        profile = config.PROFILES[profile_name]
        brightness = self._guard_lighting_brightness(
            requested_brightness=profile["lighting_brightness"],
            current_lux=snapshot["light"],
            threshold_lux=profile["light_on_below_lux"],
        )
        fan_state = snapshot["temperature"] >= profile["fan_on_above_c"] or snapshot["co2"] >= config.CO2_COMFORT_MAX

        weather_text = ""
        if weather and weather.get("enabled"):
            weather_text = (
                f"室外天气 {weather.get('condition', '未知')}，"
                f"室外温度约 {weather.get('temperature', '未知')}°C。"
            )

        reasoning = (
            f"当前处于 {fsm_state} 状态，采用 {profile_name} 模式。"
            f"室内光照 {snapshot['light']:.1f} Lux，照明建议 {brightness}%。"
            f"室内温度 {snapshot['temperature']:.1f}°C，CO2 {snapshot['co2']:.1f} ppm，"
            f"{'建议开启' if fan_state else '建议关闭'}风扇。"
            f"{weather_text}"
        )
        if fallback_note:
            reasoning = f"{fallback_note} {reasoning}"

        return ControlDecision(
            lighting_brightness=int(max(0, min(100, brightness))),
            fan_state=bool(fan_state),
            reasoning=reasoning,
            source="fsm_fallback",
        )

    @staticmethod
    def _guard_lighting_brightness(
        requested_brightness: int,
        current_lux: float,
        threshold_lux: float,
    ) -> int:
        if current_lux >= threshold_lux:
            return 0
        return int(max(0, min(100, requested_brightness)))

    def _post_chat_completion(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not config.LLM_BASE_URL:
            raise ValueError("LLM_BASE_URL is not configured")

        url = self._chat_completions_url(config.LLM_BASE_URL)
        payload = {
            "model": config.LLM_MODEL,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
        }
        req = request.Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config.LLM_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=config.LLM_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {exc.code}: {body[:200]}") from exc
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(str(exc)) from exc

    def _chat_completions_url(self, base_url: str) -> str:
        cleaned = base_url.rstrip("/")
        if cleaned.endswith("/chat/completions"):
            return cleaned
        return f"{cleaned}/chat/completions"

    def _parse_json_object(self, content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.S)
            if not match:
                raise ValueError("LLM response is not JSON")
            parsed = json.loads(match.group(0))

        if not isinstance(parsed, dict):
            raise ValueError("LLM response is not a JSON object")
        if "lighting_brightness" not in parsed or "fan_state" not in parsed:
            raise ValueError("LLM response missing required fields")
        return parsed

    def chat(
        self,
        message: str,
        context: dict[str, Any],
        history: list[dict[str, Any]] | None = None,
    ) -> str:
        normalized = message.strip()
        lowered = normalized.lower()
        if not normalized:
            raise ValueError("message is required")

        latest = context.get("latest_sensor_payload", {})
        sensor_data = latest.get("data", {})
        system = context.get("system_status", {})
        devices = context.get("device_status", {})
        alerts = context.get("active_alerts", [])
        energy = context.get("energy_summary", {})

        if "趋势" in normalized or "trend" in lowered:
            return self._trend_answer(context)
        if "预案" in normalized or "应急" in normalized or "告警" in normalized:
            return self._emergency_answer(alerts=alerts)
        if "能耗" in normalized or "节能" in normalized or "energy" in lowered:
            return self._energy_answer(energy=energy)

        return self._environment_answer(
            sensor_data=sensor_data,
            system=system,
            devices=devices,
            alerts=alerts,
        )

    def _environment_answer(
        self,
        sensor_data: dict[str, Any],
        system: dict[str, Any],
        devices: dict[str, Any],
        alerts: list[dict[str, Any]],
    ) -> str:
        def value(name: str, default: str = "未知") -> Any:
            return sensor_data.get(name, {}).get("value", default)

        temp = value("temperature")
        humidity = value("humidity")
        light = value("light")
        co2 = value("co2")
        noise = value("noise")
        smoke = value("smoke")
        pm25 = value("pm25")
        profile = system.get("active_profile", config.DEFAULT_PROFILE)
        fsm_state = system.get("fsm_state", "UNKNOWN")
        profile_config = config.PROFILES.get(profile, config.PROFILES[config.DEFAULT_PROFILE])

        suggestions = []
        try:
            if float(co2) >= config.CO2_COMFORT_MAX:
                suggestions.append("CO2 已接近或超过舒适阈值，建议加强通风或开启风扇。")
            if float(noise) >= config.NOISE_THRESHOLD:
                suggestions.append("噪声高于告警阈值，建议确认现场是否有持续噪声源。")
            if float(light) < profile_config["light_on_below_lux"]:
                suggestions.append("照度低于当前模式开灯阈值，照明可保持开启。")
            if float(smoke) >= config.SMOKE_THRESHOLD:
                suggestions.append("烟雾达到危险阈值，应立即按应急流程处理。")
        except (TypeError, ValueError):
            suggestions.append("部分传感器值暂不可用，建议先确认 oBIX 点位刷新状态。")

        if not suggestions:
            suggestions.append("当前环境总体平稳，保持自动控制即可。")

        alert_text = "无活动告警" if not alerts else f"{len(alerts)} 条活动告警"
        fan_state = devices.get("fan", {}).get("state", False)
        light_state = devices.get("lighting_led", {}).get("state", False)

        return (
            f"当前空间状态为 {fsm_state}，运行模式为 {profile}，活动告警：{alert_text}。\n"
            f"环境数据：温度 {temp}°C，湿度 {humidity}%RH，照度 {light} Lux，"
            f"CO2 {co2} ppm，噪声 {noise} dB，烟雾 {smoke} ppm，PM2.5 {pm25} ug/m3。\n"
            f"设备状态：风扇{'开启' if fan_state else '关闭'}，照明{'开启' if light_state else '关闭'}。\n"
            f"建议：{' '.join(suggestions)}"
        )

    def _energy_answer(self, energy: dict[str, Any]) -> str:
        comparison = energy.get("comparison", {})
        return (
            f"当前统计范围为 {energy.get('range', 'day')}。"
            f"风扇累计耗电约 {energy.get('total_energy_kwh', 0)} kWh，"
            f"运行 {energy.get('fan_runtime_minutes', 0)} 分钟，"
            f"平均功率 {energy.get('avg_power_w', 0)} W。"
            f"相对常开模式预计节能 {comparison.get('saving_percent', 0)}%，"
            f"折算碳减排 {energy.get('co2_reduction_kg', 0)} kg CO2。"
        )

    def _trend_answer(self, context: dict[str, Any]) -> str:
        histories = context.get("recent_history", {})
        if not histories:
            return "目前历史数据不足，建议继续采集几分钟后再查看趋势。"

        parts = []
        for sensor, rows in histories.items():
            if len(rows) < 2:
                continue
            first = rows[0]["value"]
            last = rows[-1]["value"]
            delta = last - first
            direction = "上升" if delta > 0 else "下降" if delta < 0 else "基本稳定"
            parts.append(f"{sensor} {direction}，变化约 {delta:.1f}")
        if not parts:
            return "最近数据变化不明显，整体趋势平稳。"
        return "近期趋势：" + "；".join(parts) + "。"

    def _emergency_answer(self, alerts: list[dict[str, Any]]) -> str:
        if not alerts:
            return (
                "当前没有活动告警。建议保持自动监测，确认烟雾、噪声、CO2 点位持续刷新；"
                "如现场出现异常气味、烟雾或人员不适，应立即人工确认。"
            )

        lines = ["当前存在活动告警，建议按优先级处理："]
        for alert in alerts:
            alert_type = alert.get("type")
            if alert_type == "smoke_warning":
                lines.append("烟雾告警：确认烟雾来源，通知现场人员疏散，必要时切断相关设备电源并联系安保。")
            elif alert_type == "noise_warning":
                lines.append("噪声告警：检查持续噪声源，提醒现场降噪，必要时请管理人员介入。")
            else:
                lines.append(f"{alert.get('message', '未知告警')}：请现场确认并记录处理结果。")
        return "\n".join(lines)

    def stream_tokens(self, text: str) -> list[str]:
        return [text[index : index + 12] for index in range(0, len(text), 12)]
