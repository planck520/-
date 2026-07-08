from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import config


class DatabaseManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    @contextmanager
    def _connection(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sensor_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    sensor_name TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS device_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    value TEXT,
                    source TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fsm_state_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    state TEXT NOT NULL,
                    score REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS llm_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    fsm_state TEXT NOT NULL,
                    reasoning TEXT NOT NULL,
                    actions TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    triggered_at TEXT NOT NULL,
                    resolved_at TEXT,
                    type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    sensor_value REAL,
                    threshold REAL
                );

                CREATE INDEX IF NOT EXISTS idx_readings_sensor_time
                ON sensor_readings(sensor_name, timestamp);

                CREATE INDEX IF NOT EXISTS idx_readings_time
                ON sensor_readings(timestamp);

                CREATE INDEX IF NOT EXISTS idx_alerts_active
                ON alerts(type, resolved_at);
                """
            )

    def insert_sensor_snapshot(self, timestamp: str, readings: dict[str, float]) -> None:
        rows = [
            (timestamp, sensor_name, value, config.SENSORS[sensor_name]["unit"])
            for sensor_name, value in readings.items()
        ]
        with self._connection() as conn:
            conn.executemany(
                """
                INSERT INTO sensor_readings (timestamp, sensor_name, value, unit)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )

    def get_sensor_history(
        self,
        sensor_name: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, value, unit
                FROM sensor_readings
                WHERE sensor_name = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (sensor_name, start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
            ).fetchall()
        return [{"ts": row["timestamp"], "value": row["value"], "unit": row["unit"]} for row in rows]

    def log_device_event(
        self,
        timestamp: str,
        device_name: str,
        action: str,
        value: Any,
        source: str,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO device_events (timestamp, device_name, action, value, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (timestamp, device_name, action, json.dumps(value, ensure_ascii=False), source),
            )

    def log_fsm_state(self, timestamp: str, state: str, score: float) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO fsm_state_log (timestamp, state, score)
                VALUES (?, ?, ?)
                """,
                (timestamp, state, score),
            )

    def log_llm_decision(
        self,
        timestamp: str,
        fsm_state: str,
        reasoning: str,
        actions: dict[str, Any],
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO llm_decisions (timestamp, fsm_state, reasoning, actions)
                VALUES (?, ?, ?, ?)
                """,
                (timestamp, fsm_state, reasoning, json.dumps(actions, ensure_ascii=False)),
            )

    def open_alert(
        self,
        timestamp: str,
        alert_type: str,
        severity: str,
        message: str,
        sensor_value: float,
        threshold: float,
    ) -> None:
        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT id
                FROM alerts
                WHERE type = ? AND resolved_at IS NULL
                LIMIT 1
                """,
                (alert_type,),
            ).fetchone()
            if existing:
                return
            conn.execute(
                """
                INSERT INTO alerts (triggered_at, type, severity, message, sensor_value, threshold)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (timestamp, alert_type, severity, message, sensor_value, threshold),
            )

    def resolve_alert(self, timestamp: str, alert_type: str) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE alerts
                SET resolved_at = ?
                WHERE type = ? AND resolved_at IS NULL
                """,
                (timestamp, alert_type),
            )

    def get_active_alerts(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, type, severity, message, triggered_at, sensor_value, threshold
                FROM alerts
                WHERE resolved_at IS NULL
                ORDER BY triggered_at DESC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "type": row["type"],
                "severity": row["severity"],
                "message": row["message"],
                "triggered_at": row["triggered_at"],
                "value": row["sensor_value"],
                "threshold": row["threshold"],
            }
            for row in rows
        ]

    def get_latest_llm_reasoning(self) -> str | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT reasoning
                FROM llm_decisions
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return None if row is None else row["reasoning"]

    def get_energy_summary(self, range_name: str) -> dict[str, Any]:
        if range_name not in config.ENERGY_RANGE_TO_HOURS:
            raise ValueError("Unsupported range")

        now = datetime.now().astimezone()
        hours = config.ENERGY_RANGE_TO_HOURS[range_name]
        start = now - timedelta(hours=hours)
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, value
                FROM sensor_readings
                WHERE sensor_name = 'fan_power' AND timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (start.isoformat(timespec="seconds"),),
            ).fetchall()

        points = [
            (datetime.fromisoformat(row["timestamp"]), float(row["value"]))
            for row in rows
        ]

        total_wh = 0.0
        runtime_seconds = 0.0
        for index, (current_ts, current_value) in enumerate(points):
            if index + 1 < len(points):
                next_ts = points[index + 1][0]
            else:
                next_ts = min(now, current_ts + timedelta(seconds=config.POLL_INTERVAL_SECONDS))
            interval_seconds = max(0.0, (next_ts - current_ts).total_seconds())
            total_wh += current_value * interval_seconds / 3600.0
            if current_value > 0.1:
                runtime_seconds += interval_seconds

        total_kwh = total_wh / 1000.0
        avg_power_w = total_wh / hours if hours else 0.0
        always_on_kwh = config.FAN_ALWAYS_ON_POWER_W * hours / 1000.0
        saving_percent = 0.0
        if always_on_kwh > 0:
            saving_percent = max(0.0, (always_on_kwh - total_kwh) / always_on_kwh * 100.0)

        return {
            "range": range_name,
            "total_energy_kwh": round(total_kwh, 3),
            "fan_runtime_minutes": int(runtime_seconds / 60.0),
            "avg_power_w": round(avg_power_w, 1),
            "co2_reduction_kg": round(
                max(0.0, always_on_kwh - total_kwh) * config.CARBON_EMISSION_FACTOR_KG_PER_KWH,
                2,
            ),
            "comparison": {
                "ai_mode_kwh": round(total_kwh, 3),
                "always_on_kwh": round(always_on_kwh, 3),
                "saving_percent": round(saving_percent, 1),
            },
        }
