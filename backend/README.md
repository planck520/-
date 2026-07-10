# cloud_controller backend

Backend service for the HuYue library IoT controller. It stores sensor readings in SQLite, reads and writes JACE/oBIX points, exposes dashboard APIs, and includes a terminal keyboard demo helper for competition demos.

## Run The Backend

```powershell
cd C:\Users\24869\Desktop\物联网\-\backend
python main.py
```

Default service URL:

```text
http://127.0.0.1:5000
```

Frontend dashboard:

```text
http://127.0.0.1:5000/app
```

The frontend is a static FlashBack-style operations console in `../frontend`. It uses the backend API by default when opened from `/app`. If you open `frontend/index.html` directly, it will call `http://127.0.0.1:5000`; you can override that with:

```text
frontend/index.html?api=http://127.0.0.1:5000
```

Health check:

```powershell
curl http://127.0.0.1:5000/health
```

## Configuration

Common real-device variables:

```powershell
$env:OBIX_IP="192.168.1.140"
$env:OBIX_USERNAME="obixuser"
$env:OBIX_PASSWORD="ADmin12345"
```

AI API config can be stored in a local file:

```powershell
cd C:\Users\24869\Desktop\物联网\-\backend
copy AIAPIconfig.example AIAPIconfig
```

Then edit `AIAPIconfig`:

```text
LLM_ENABLED=true
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=your_api_key_here
LLM_TIMEOUT_SECONDS=8
```

`AIAPIconfig` is ignored by git. Commit `AIAPIconfig.example`, not the real config file.

When `LLM_ENABLED=true` and the key/base URL are valid, Function 4 uses the LLM engine for weather-aware comfort advice in `ARRIVING` and `OCCUPIED` states. The LLM result is displayed on the dashboard and stored in SQLite for explanation only; it does not write hardware.

```json
{"lighting_brightness": 60, "fan_state": true, "reasoning": "中文建议理由"}
```

Lighting and fan writes are always handled by local deterministic rules. `VACANT` turns lighting and fan off locally. Smoke/noise safety actions are also handled by deterministic backend rules. If the LLM call fails or returns invalid JSON, the dashboard shows the local-rule explanation instead.

Demo/simulation mode:

```powershell
$env:SIMULATION_MODE="true"
```

The buzzer is installed by default and writes to the Workbench/oBIX BooleanWritable point `蜂鸣器`. If the buzzer is temporarily disconnected, disable physical writes while keeping demo logic state:

```powershell
$env:BUZZER_INSTALLED="false"
```

## Keyboard Demo

Start the backend first, then open a second PowerShell window:

```powershell
cd C:\Users\24869\Desktop\物联网\-\backend
python keyboard_demo.py
```

Keyboard controls:

```text
1  FSM -> VACANT, then immediately apply auto light/fan control
2  FSM -> ARRIVING, then immediately apply auto light/fan control
3  FSM -> OCCUPIED, then immediately apply auto light/fan control
4  FSM -> LEAVING, then immediately apply auto light/fan control
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

p  Print shortcut/system/device state
h  Help
q  Quit
```

The same demo shortcuts are also available in the frontend dashboard when the browser focus is not inside a text input:

```text
1/2/3/4  Force FSM to VACANT / ARRIVING / OCCUPIED / LEAVING
0        Clear FSM override
n/N      Trigger / clear noise warning
s/S      Trigger / clear smoke warning
a        Clear all warnings
d        Toggle demo/real mode
f/F/r    Fan on / off / auto
b/B      Buzzer on / off
w/W      Warning LED on / off
l/L/R    Lighting LED on / off / auto
```

## Shortcut API

The keyboard helper calls:

```text
POST /api/v1/shortcuts/action
```

Examples:

```json
{"action": "set_fsm", "params": {"state": "OCCUPIED"}}
```

```json
{"action": "control_device", "params": {"device": "fan", "device_action": "on"}}
```

```json
{"action": "control_device", "params": {"device": "lighting_led", "device_action": "set_brightness", "value": 100}}
```

```json
{"action": "trigger_alert", "params": {"type": "noise_warning"}}
```

## Live Test Script

Print live sensor data and run API checks:

```powershell
python test_backend.py --watch 1 --api-check
```

Run against real hardware and fail if simulation is enabled:

```powershell
python test_backend.py --watch 3 --interval 2 --require-real
```

Manual device examples:

```powershell
python test_backend.py --require-real --control-device fan --action on
python test_backend.py --require-real --control-device fan --action off
python test_backend.py --require-real --control-device fan --action auto
python test_backend.py --require-real --control-device lighting_led --action set_brightness --value 100
python test_backend.py --require-real --control-device lighting_led --action set_brightness --value 0
```
