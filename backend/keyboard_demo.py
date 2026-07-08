from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, request


DEFAULT_BASE_URL = os.getenv("DEMO_API_BASE", "http://127.0.0.1:5000/api/v1")


KEY_ACTIONS = {
    "1": ("set_fsm", {"state": "VACANT"}, "FSM -> VACANT"),
    "2": ("set_fsm", {"state": "ARRIVING"}, "FSM -> ARRIVING"),
    "3": ("set_fsm", {"state": "OCCUPIED"}, "FSM -> OCCUPIED"),
    "4": ("set_fsm", {"state": "LEAVING"}, "FSM -> LEAVING"),
    "0": ("clear_fsm", {}, "Clear FSM override"),
    "n": ("trigger_alert", {"type": "noise_warning"}, "Trigger noise warning"),
    "N": ("clear_alert", {"type": "noise_warning"}, "Clear noise warning"),
    "s": ("trigger_alert", {"type": "smoke_warning"}, "Trigger smoke warning"),
    "S": ("clear_alert", {"type": "smoke_warning"}, "Clear smoke warning"),
    "a": ("clear_alert", {}, "Clear all warnings"),
    "d": ("toggle_demo_mode", {}, "Toggle demo/real mode"),
    "f": ("control_device", {"device": "fan", "device_action": "on"}, "Fan on"),
    "F": ("control_device", {"device": "fan", "device_action": "off"}, "Fan off"),
    "b": ("control_device", {"device": "buzzer", "device_action": "on"}, "Buzzer on"),
    "B": ("control_device", {"device": "buzzer", "device_action": "off"}, "Buzzer off"),
    "w": ("control_device", {"device": "warning_led", "device_action": "on"}, "Warning LED on"),
    "W": ("control_device", {"device": "warning_led", "device_action": "off"}, "Warning LED off"),
    "l": (
        "control_device",
        {"device": "lighting_led", "device_action": "set_brightness", "value": 100},
        "Lighting LED on",
    ),
    "L": (
        "control_device",
        {"device": "lighting_led", "device_action": "set_brightness", "value": 0},
        "Lighting LED off",
    ),
    "r": ("control_device", {"device": "fan", "device_action": "auto"}, "Fan auto"),
    "R": ("control_device", {"device": "lighting_led", "device_action": "auto"}, "Lighting LED auto"),
}


def configure_console() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def post_json(base_url: str, path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(base_url: str, path: str) -> dict:
    req = request.Request(
        url=f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    with request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def read_key() -> str:
    if os.name == "nt":
        import msvcrt

        while True:
            raw = msvcrt.getwch()
            if raw in ("\x00", "\xe0"):
                msvcrt.getwch()
                continue
            return raw
    return input("key> ")[:1]


def print_help() -> None:
    print(
        """
Keyboard demo controls

1  FSM -> VACANT
2  FSM -> ARRIVING
3  FSM -> OCCUPIED
4  FSM -> LEAVING
0  Clear FSM override

n  Trigger noise warning
N  Clear noise warning
s  Trigger smoke warning
S  Clear smoke warning
a  Clear all warnings

d  Toggle demo/real mode

f  Fan on
F  Fan off
r  Fan auto
b  Buzzer on
B  Buzzer off
w  Warning LED on
W  Warning LED off
l  Lighting LED on
L  Lighting LED off
R  Lighting LED auto

p  Print shortcut/system state
h  Help
q  Quit
"""
    )


def print_state(base_url: str) -> None:
    shortcuts = get_json(base_url, "shortcuts")
    system = get_json(base_url, "system/status")
    alerts = get_json(base_url, "alerts")
    devices = get_json(base_url, "devices/status")
    print(
        json.dumps(
            {
                "fsm_state": system.get("fsm_state"),
                "fsm_override_state": system.get("fsm_override_state"),
                "demo_mode": system.get("demo_mode"),
                "demo_mode_override": system.get("demo_mode_override"),
                "ai_mode": system.get("ai_mode"),
                "active_alerts": alerts.get("active_alerts", []),
                "devices": devices,
                "last_shortcuts": shortcuts.get("history", [])[:3],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="Keyboard helper for demo shortcut actions.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend API base URL.")
    args = parser.parse_args()

    print(f"Connecting to {args.base_url}")
    try:
        print_state(args.base_url)
    except (error.URLError, TimeoutError, ConnectionError) as exc:
        print(f"Backend is not reachable: {exc}")
        print("Start it first with: python main.py")
        return 1

    print_help()
    while True:
        key = read_key()
        if key in {"q", "Q", "\x03"}:
            print("Bye.")
            return 0
        if key in {"h", "H", "?"}:
            print_help()
            continue
        if key in {"p", "P"}:
            print_state(args.base_url)
            continue

        action = KEY_ACTIONS.get(key)
        if action is None:
            print(f"Unknown key: {repr(key)}. Press h for help.")
            continue

        action_name, params, label = action
        try:
            response = post_json(
                args.base_url,
                "shortcuts/action",
                {"action": action_name, "params": params},
            )
            state = response.get("shortcut_state", {})
            device_status = response.get("device_status")
            if device_status is not None:
                print(f"{label} | device_status={json.dumps(device_status, ensure_ascii=False)}")
            else:
                print(
                    f"{label} | fsm_override={state.get('fsm_override_state')} "
                    f"demo_mode={state.get('demo_mode')}"
                )
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(f"Action failed: HTTP {exc.code} {detail}")
        except (error.URLError, TimeoutError, ConnectionError) as exc:
            print(f"Backend connection failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
