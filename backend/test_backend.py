from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timedelta
from typing import Any

import config
from main import BackendRuntime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def print_line(message: str = "") -> None:
    print(message)


def print_section(title: str) -> None:
    print_line(f"\n=== {title} ===")


def format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def print_sensor_payload(payload: dict[str, Any]) -> None:
    print_section("Latest Sensor Payload")
    print_line(f"timestamp: {payload['timestamp']}")
    for sensor_name, meta in payload["data"].items():
        print_line(f"{sensor_name:12} {format_value(meta['value']):>8} {meta['unit']}")


def print_mapping(title: str, payload: dict[str, Any]) -> None:
    print_section(title)
    print_line(json.dumps(payload, ensure_ascii=False, indent=2))


def run_basic_assertions(runtime: BackendRuntime) -> None:
    runtime.ensure_healthy()
    latest = runtime.get_latest_sensor_payload()
    if "timestamp" not in latest or "data" not in latest:
        raise AssertionError("latest payload is incomplete")
    if set(latest["data"].keys()) != set(config.SENSORS.keys()):
        raise AssertionError("sensor fields are incomplete")

    system_status = runtime.get_system_status()
    if "fsm_state" not in system_status or "active_profile" not in system_status:
        raise AssertionError("system status is incomplete")

    end = datetime.now().astimezone()
    start = end - timedelta(minutes=5)
    history = runtime.get_sensor_history("co2", start=start, end=end)
    if not history:
        raise AssertionError("history data is empty")

    energy = runtime.get_energy_summary("day")
    if "comparison" not in energy:
        raise AssertionError("energy summary is incomplete")


def run_api_checks(runtime: BackendRuntime) -> None:
    if importlib.util.find_spec("flask") is None:
        print_line("[INFO] Flask not detected, skipping API checks")
        return

    from web_server import create_app

    app = create_app(runtime)
    client = app.test_client()
    routes = [
        "/api/v1/sensors/latest",
        "/api/v1/devices/status",
        "/api/v1/devices/events",
        "/api/v1/system/status",
        "/api/v1/system/profiles",
        "/api/v1/shortcuts",
        "/api/v1/energy/summary?range=day",
        "/api/v1/energy/timeseries?range=day",
        "/api/v1/alerts",
        "/api/v1/assistant/quick-prompts",
        "/api/v1/assistant/history",
    ]
    for route in routes:
        response = client.get(route)
        if response.status_code != 200:
            raise AssertionError(f"GET {route} failed with {response.status_code}")

    response = client.post("/api/v1/system/profile", json={"profile": "balanced"})
    if response.status_code != 200:
        raise AssertionError("POST /api/v1/system/profile failed")

    response = client.post(
        "/api/v1/devices/control",
        json={"device": "fan", "action": "auto"},
    )
    if response.status_code != 200:
        raise AssertionError("POST /api/v1/devices/control failed")

    shortcut_checks = [
        {"action": "set_fsm", "params": {"state": "OCCUPIED"}},
        {"action": "clear_fsm"},
        {"action": "trigger_alert", "params": {"type": "noise_warning"}},
        {"action": "clear_alert", "params": {"type": "noise_warning"}},
        {"action": "control_device", "params": {"device": "fan", "device_action": "on"}},
        {"action": "control_device", "params": {"device": "fan", "device_action": "off"}},
        {"action": "control_device", "params": {"device": "lighting_led", "device_action": "set_brightness", "value": 100}},
        {"action": "control_device", "params": {"device": "lighting_led", "device_action": "set_brightness", "value": 0}},
        {"action": "set_demo_mode", "params": {"enabled": True}},
        {"action": "toggle_demo_mode"},
    ]
    for payload in shortcut_checks:
        response = client.post("/api/v1/shortcuts/action", json=payload)
        if response.status_code != 200:
            raise AssertionError(f"POST /api/v1/shortcuts/action failed for {payload}")

    response = client.post(
        "/api/v1/assistant/chat",
        json={"message": "分析当前环境数据"},
    )
    if response.status_code != 200:
        raise AssertionError("POST /api/v1/assistant/chat failed")

    print_line("[INFO] API checks passed")


def apply_manual_control(runtime: BackendRuntime, args: argparse.Namespace) -> None:
    if not args.control_device:
        return

    if args.control_device == "lighting_led":
        if args.action == "auto":
            result = runtime.control_device("lighting_led", "auto", args.value)
            print_mapping("Manual Control Result", result)
            time.sleep(args.post_control_wait)
            print_mapping("Device Status After Control", runtime.get_device_status())
            print_mapping("Physical Device State Readback", runtime.read_physical_device_states())
            return
        if args.action != "set_brightness":
            raise ValueError("lighting_led requires --action set_brightness or auto")
        if args.value is None:
            raise ValueError("lighting_led set_brightness requires --value")
        result = runtime.control_device("lighting_led", "set_brightness", args.value)
    else:
        if args.action not in {"on", "off", "auto"}:
            raise ValueError("action must be on/off/auto for this device")
        result = runtime.control_device(args.control_device, args.action, args.value)

    print_mapping("Manual Control Result", result)
    time.sleep(args.post_control_wait)
    print_mapping("Device Status After Control", runtime.get_device_status())
    print_mapping("Physical Device State Readback", runtime.read_physical_device_states())


def watch_runtime(runtime: BackendRuntime, args: argparse.Namespace) -> None:
    for index in range(args.watch):
        runtime.ensure_healthy()
        latest = runtime.get_latest_sensor_payload()
        collector_meta = runtime.get_collector_meta()
        system_status = runtime.get_system_status()
        device_status = runtime.get_device_status()
        diagnostics = runtime.get_runtime_diagnostics()

        print_section(f"Runtime Snapshot {index + 1}/{args.watch}")
        print_line(f"simulation_mode: {config.SIMULATION_MODE}")
        print_line(f"strict_obix_mode: {config.STRICT_OBIX_MODE}")
        print_line(f"collector_meta: {json.dumps(collector_meta, ensure_ascii=False)}")
        print_line(f"diagnostics: {json.dumps(diagnostics, ensure_ascii=False)}")
        print_sensor_payload(latest)
        print_mapping("System Status", system_status)
        print_mapping("Logical Device Status", device_status)

        if not config.SIMULATION_MODE:
            print_mapping("Physical Device State Readback", runtime.read_physical_device_states())

        if index + 1 < args.watch:
            time.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backend runtime viewer and live device control helper."
    )
    parser.add_argument(
        "--watch",
        type=int,
        default=1,
        help="How many runtime snapshots to print.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=max(1.0, config.POLL_INTERVAL_SECONDS),
        help="Seconds to wait between snapshots.",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Run basic assertions against runtime data.",
    )
    parser.add_argument(
        "--api-check",
        action="store_true",
        help="Run Flask test-client API checks if Flask is installed.",
    )
    parser.add_argument(
        "--control-device",
        choices=["warning_led", "buzzer", "fan", "lighting_led"],
        help="Device to control after startup.",
    )
    parser.add_argument(
        "--action",
        choices=["on", "off", "auto", "set_brightness"],
        help="Action to apply to the device.",
    )
    parser.add_argument(
        "--value",
        type=int,
        help="Value used by actions such as set_brightness.",
    )
    parser.add_argument(
        "--post-control-wait",
        type=float,
        default=1.0,
        help="Seconds to wait before reading back device status after a control command.",
    )
    parser.add_argument(
        "--require-real",
        action="store_true",
        help="Fail immediately if SIMULATION_MODE is still enabled.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    runtime: BackendRuntime | None = None

    try:
        if args.require_real and config.SIMULATION_MODE:
            raise RuntimeError(
                "SIMULATION_MODE is true. Set SIMULATION_MODE=false before running against real hardware."
            )

        print_section("Startup")
        print_line(f"simulation_mode: {config.SIMULATION_MODE}")
        print_line(f"strict_obix_mode: {config.STRICT_OBIX_MODE}")
        print_line(f"obix_ip: {config.OBIX_IP}")
        print_line(f"obix_port: {config.OBIX_PORT}")
        print_line(f"station_name: {config.OBIX_STATION_NAME}")

        runtime = BackendRuntime()
        runtime.start()
        time.sleep(max(2.5, config.POLL_INTERVAL_SECONDS + 0.5))
        runtime.ensure_healthy()

        if args.self_check:
            run_basic_assertions(runtime)
            print_line("[INFO] Runtime checks passed")

        watch_runtime(runtime, args)
        apply_manual_control(runtime, args)

        if args.api_check:
            run_api_checks(runtime)

        print_section("Result")
        print_line(
            json.dumps(
                {
                    "result": "passed",
                    "simulation_mode": config.SIMULATION_MODE,
                    "strict_obix_mode": config.STRICT_OBIX_MODE,
                    "flask_installed": importlib.util.find_spec("flask") is not None,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        print_section("Result")
        print_line(json.dumps({"result": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        if runtime is not None:
            runtime.stop()
            time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(main())
