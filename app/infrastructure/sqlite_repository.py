"""TCC 操作日志与逻辑报文历史的 SQLite 仓库。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.core.enums import RunningDirection


@dataclass(frozen=True)
class OperationLogEntry:
    station_id: str
    event_time_ms: int
    operation: str
    success: bool
    reason: str
    state_version: int
    details: Mapping[str, Any]


@dataclass(frozen=True)
class TelegramHistoryEntry:
    station_id: str
    event_time_ms: int
    balise_id: str
    template_id: str
    mode: str
    logical_payload: Mapping[str, Any]
    simulation_hex: str
    crc32: str


@dataclass(frozen=True)
class DirectionAuthorityEntry:
    """A 站持久化的唯一区间方向真值及最近一次恢复证据。"""

    station_id: str
    direction: RunningDirection
    updated_at_ms: int
    state_version: int
    recovery: Mapping[str, Any] | None = None


class SQLiteRepository:
    """每次操作使用独立连接，避免把 sqlite 连接跨线程共享。

    数据库启用 WAL、外键和 busy_timeout；建表脚本可重复执行。仓库只保存
    可序列化历史，不保存 QObject、socket 或运行中的领域对象。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._initialize()

    @property
    def schema_version(self) -> int:
        self._ensure_open()
        connection = self._connect()
        try:
            row = connection.execute("PRAGMA user_version").fetchone()
            return int(row[0])
        finally:
            connection.close()

    def append_operation(self, entry: OperationLogEntry) -> None:
        self._ensure_open()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO operation_logs (
                        station_id, event_time_ms, operation, success,
                        reason, state_version, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.station_id,
                        entry.event_time_ms,
                        entry.operation,
                        int(entry.success),
                        entry.reason,
                        entry.state_version,
                        self._json(entry.details),
                    ),
                )
        finally:
            connection.close()

    def append_telegram(self, entry: TelegramHistoryEntry) -> None:
        self._ensure_open()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO telegram_history (
                        station_id, event_time_ms, balise_id, template_id,
                        mode, logical_json, simulation_hex, crc32
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.station_id,
                        entry.event_time_ms,
                        entry.balise_id,
                        entry.template_id,
                        entry.mode,
                        self._json(entry.logical_payload),
                        entry.simulation_hex,
                        entry.crc32,
                    ),
                )
        finally:
            connection.close()

    def save_direction_authority(self, entry: DirectionAuthorityEntry) -> None:
        self._ensure_open()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO direction_authority (
                        station_id, direction, updated_at_ms,
                        state_version, recovery_json
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(station_id) DO UPDATE SET
                        direction = excluded.direction,
                        updated_at_ms = excluded.updated_at_ms,
                        state_version = excluded.state_version,
                        recovery_json = excluded.recovery_json
                    """,
                    (
                        entry.station_id,
                        entry.direction.value,
                        entry.updated_at_ms,
                        entry.state_version,
                        None if entry.recovery is None else self._json(entry.recovery),
                    ),
                )
        finally:
            connection.close()

    def load_direction_authority(
        self, station_id: str
    ) -> DirectionAuthorityEntry | None:
        self._ensure_open()
        connection = self._connect()
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """
                SELECT station_id, direction, updated_at_ms,
                       state_version, recovery_json
                FROM direction_authority WHERE station_id = ?
                """,
                (station_id,),
            ).fetchone()
            if row is None:
                return None
            recovery_json = row["recovery_json"]
            return DirectionAuthorityEntry(
                station_id=row["station_id"],
                direction=RunningDirection(row["direction"]),
                updated_at_ms=row["updated_at_ms"],
                state_version=row["state_version"],
                recovery=(
                    None if recovery_json is None else json.loads(recovery_json)
                ),
            )
        finally:
            connection.close()

    def list_operations(
        self, station_id: str, *, limit: int = 200
    ) -> tuple[OperationLogEntry, ...]:
        self._ensure_open()
        connection = self._connect()
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT station_id, event_time_ms, operation, success,
                       reason, state_version, details_json
                FROM operation_logs
                WHERE station_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (station_id, limit),
            ).fetchall()
            return tuple(
                OperationLogEntry(
                    row["station_id"],
                    row["event_time_ms"],
                    row["operation"],
                    bool(row["success"]),
                    row["reason"],
                    row["state_version"],
                    json.loads(row["details_json"]),
                )
                for row in rows
            )
        finally:
            connection.close()

    def list_telegrams(
        self, station_id: str, *, limit: int = 200
    ) -> tuple[TelegramHistoryEntry, ...]:
        self._ensure_open()
        connection = self._connect()
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT station_id, event_time_ms, balise_id, template_id,
                       mode, logical_json, simulation_hex, crc32
                FROM telegram_history
                WHERE station_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (station_id, limit),
            ).fetchall()
            return tuple(
                TelegramHistoryEntry(
                    row["station_id"],
                    row["event_time_ms"],
                    row["balise_id"],
                    row["template_id"],
                    row["mode"],
                    json.loads(row["logical_json"]),
                    row["simulation_hex"],
                    row["crc32"],
                )
                for row in rows
            )
        finally:
            connection.close()

    def close(self) -> None:
        self._closed = True

    def _initialize(self) -> None:
        connection = self._connect(check_open=False)
        try:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS operation_logs (
                        id INTEGER PRIMARY KEY,
                        station_id TEXT NOT NULL,
                        event_time_ms INTEGER NOT NULL,
                        operation TEXT NOT NULL,
                        success INTEGER NOT NULL CHECK (success IN (0, 1)),
                        reason TEXT NOT NULL,
                        state_version INTEGER NOT NULL,
                        details_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_operation_station_time
                        ON operation_logs(station_id, event_time_ms DESC);

                    CREATE TABLE IF NOT EXISTS telegram_history (
                        id INTEGER PRIMARY KEY,
                        station_id TEXT NOT NULL,
                        event_time_ms INTEGER NOT NULL,
                        balise_id TEXT NOT NULL,
                        template_id TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        logical_json TEXT NOT NULL,
                        simulation_hex TEXT NOT NULL,
                        crc32 TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_telegram_station_time
                        ON telegram_history(station_id, event_time_ms DESC);
                    CREATE TABLE IF NOT EXISTS direction_authority (
                        station_id TEXT PRIMARY KEY,
                        direction TEXT NOT NULL,
                        updated_at_ms INTEGER NOT NULL,
                        state_version INTEGER NOT NULL,
                        recovery_json TEXT
                    );
                    PRAGMA user_version = 2;
                    """
                )
        finally:
            connection.close()

    def _connect(self, *, check_open: bool = True) -> sqlite3.Connection:
        if check_open:
            self._ensure_open()
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("SQLite 仓库已关闭")

    @staticmethod
    def _json(value: Mapping[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
