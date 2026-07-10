from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import json

from flask import Flask, Response, jsonify, redirect, request, send_from_directory, stream_with_context

import config


def create_app(runtime) -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    icon_dir = Path(__file__).resolve().parent.parent / "icon"

    @app.get("/")
    def index():
        return jsonify(
            {
                "service": "cloud_controller",
                "message": "慧阅初始后端已启动",
                "base_url": "/api/v1",
            }
        )

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/v1/sensors/latest")
    def latest_sensors():
        payload = runtime.get_latest_sensor_payload()
        return jsonify(payload)

    @app.get("/api/v1/sensors/diagnostics")
    def sensor_diagnostics():
        return jsonify(runtime.get_sensor_diagnostics())

    @app.get("/api/v1/sensors/history")
    def sensor_history():
        sensor = request.args.get("sensor", "").strip()
        if sensor not in config.SENSORS:
            return jsonify({"error": "Unsupported sensor"}), 400

        end = _parse_datetime(request.args.get("end")) or datetime.now().astimezone()
        start = _parse_datetime(request.args.get("start")) or (end - timedelta(hours=1))
        data = runtime.get_sensor_history(sensor=sensor, start=start, end=end)
        return jsonify(
            {
                "sensor": sensor,
                "unit": config.SENSORS[sensor]["unit"],
                "data": [{"ts": row["ts"], "value": row["value"]} for row in data],
            }
        )

    @app.get("/api/v1/devices/status")
    def device_status():
        return jsonify(runtime.get_device_status())

    @app.get("/api/v1/devices/diagnostics")
    def device_diagnostics():
        return jsonify(runtime.get_device_diagnostics())

    @app.get("/api/v1/devices/events")
    def device_events():
        limit = int(request.args.get("limit", "50"))
        device = request.args.get("device")
        return jsonify({"events": runtime.get_device_events(limit=limit, device_name=device)})

    @app.post("/api/v1/devices/control")
    def control_device():
        payload = request.get_json(silent=True) or {}
        device = payload.get("device")
        action = payload.get("action")
        value = payload.get("value")
        if not device or not action:
            return jsonify({"error": "device and action are required"}), 400
        try:
            result = runtime.control_device(device=device, action=action, value=value)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, "device": device, **result})

    @app.get("/api/v1/system/profiles")
    def system_profiles():
        return jsonify(runtime.get_profiles())

    @app.get("/api/v1/system/status")
    def system_status():
        return jsonify(runtime.get_system_status())

    @app.get("/api/v1/weather")
    def weather():
        return jsonify(runtime.weather_service.get_current_weather())

    @app.get("/api/v1/shortcuts")
    def shortcut_state():
        return jsonify(runtime.get_shortcut_state())

    @app.post("/api/v1/shortcuts/action")
    def shortcut_action():
        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action", "")).strip()
        params = payload.get("params") or {}
        if not action:
            return jsonify({"error": "action is required"}), 400
        if not isinstance(params, dict):
            return jsonify({"error": "params must be an object"}), 400
        try:
            result = runtime.apply_shortcut_action(action=action, payload=params)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result)

    @app.post("/api/v1/system/profile")
    def system_profile():
        payload = request.get_json(silent=True) or {}
        profile = payload.get("profile")
        if not profile:
            return jsonify({"error": "profile is required"}), 400
        try:
            runtime.set_profile(profile)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, **runtime.get_profiles()})

    @app.get("/api/v1/energy/summary")
    def energy_summary():
        range_name = request.args.get("range", "day")
        try:
            summary = runtime.get_energy_summary(range_name=range_name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(summary)

    @app.get("/api/v1/energy/timeseries")
    def energy_timeseries():
        range_name = request.args.get("range", "day")
        try:
            payload = runtime.get_energy_timeseries(range_name=range_name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(payload)

    @app.get("/api/v1/alerts")
    def alerts():
        return jsonify({"active_alerts": runtime.get_active_alerts()})

    @app.get("/api/v1/assistant/quick-prompts")
    def assistant_quick_prompts():
        return jsonify(
            {
                "prompts": [
                    {"id": "environment", "text": "分析当前环境数据"},
                    {"id": "trends", "text": "查看近期趋势"},
                    {"id": "emergency", "text": "查询应急预案"},
                    {"id": "energy", "text": "分析当前能耗"},
                ]
            }
        )

    @app.get("/app")
    def frontend_redirect():
        return redirect("/app/", code=302)

    @app.get("/app/")
    def frontend_index():
        return send_from_directory(frontend_dir, "index.html")

    @app.get("/app/icon/<path:filename>")
    def frontend_icons(filename: str):
        return send_from_directory(icon_dir, filename)

    @app.get("/app/<path:filename>")
    def frontend_assets(filename: str):
        return send_from_directory(frontend_dir, filename)

    @app.get("/api/v1/assistant/history")
    def assistant_history():
        limit = int(request.args.get("limit", "20"))
        return jsonify({"messages": runtime.get_assistant_history(limit=limit)})

    @app.post("/api/v1/assistant/chat")
    def assistant_chat():
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message", "")).strip()
        stream = bool(payload.get("stream", False))
        if not message:
            return jsonify({"error": "message is required"}), 400

        if stream:
            def generate():
                for token in runtime.stream_assistant_response(message):
                    yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return Response(
                stream_with_context(generate()),
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )

        try:
            response = runtime.chat_with_assistant(message)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(response)

    return app


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed.astimezone()
