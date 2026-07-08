from __future__ import annotations

from datetime import datetime, timedelta

from flask import Flask, jsonify, request

import config


def create_app(runtime) -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False

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

    @app.get("/api/v1/system/status")
    def system_status():
        return jsonify(runtime.get_system_status())

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
        return jsonify({"success": True, "profile": profile})

    @app.get("/api/v1/energy/summary")
    def energy_summary():
        range_name = request.args.get("range", "day")
        try:
            summary = runtime.get_energy_summary(range_name=range_name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(summary)

    @app.get("/api/v1/alerts")
    def alerts():
        return jsonify({"active_alerts": runtime.get_active_alerts()})

    return app


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed
