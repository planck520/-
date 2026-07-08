# cloud_controller

Initial backend for the HuYue library IoT controller. It exposes the API from the design document, stores readings in SQLite, reads/writes oBIX points, and can run either against real JACE hardware or simulated data.

## Run

```powershell
cd C:\Users\justin\Documents\物联网
pip install -r .\cloud_controller\requirements.txt
python .\cloud_controller\main.py
```

## Configuration

The backend now accepts both the code-style environment variables and the names used in the design document.

Common real-device variables:

```powershell
$env:JACE_IP="192.168.1.140"
$env:STATION_NAME="LibraryCtrl"
$env:OBIX_USERNAME="admin"
$env:OBIX_PASSWORD="password"
```

Equivalent variable names also work:

```powershell
$env:OBIX_IP="192.168.1.140"
$env:OBIX_STATION_NAME="LibraryCtrl"
```

If `JACE_IP` or `OBIX_IP` is set to a real address, the backend automatically uses real oBIX mode:

- `SIMULATION_MODE=false`
- `STRICT_OBIX_MODE=true`

If no real JACE address is configured, it stays in simulation mode so the backend can still run locally.

## Live Test Script

Print live sensor data:

```powershell
python .\cloud_controller\test_backend.py --watch 3 --interval 2 --require-real
```

Turn the warning LED on:

```powershell
python .\cloud_controller\test_backend.py --watch 1 --require-real --control-device warning_led --action on
```

Turn the warning LED off:

```powershell
python .\cloud_controller\test_backend.py --watch 1 --require-real --control-device warning_led --action off
```

The script prints sensor values, FSM/system state, logical device state, and physical oBIX readback when running in real-device mode.
