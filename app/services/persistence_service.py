"""把存储异常转换为界面可见告警的应用服务。"""

from typing import Protocol

from app.infrastructure.sqlite_repository import (
    DirectionAuthorityEntry,
    OperationLogEntry,
    TelegramHistoryEntry,
)
from app.services.alarm_service import AlarmLevel, AlarmService


class HistoryRepository(Protocol):
    def append_operation(self, entry: OperationLogEntry) -> None: ...

    def append_telegram(self, entry: TelegramHistoryEntry) -> None: ...

    def save_direction_authority(self, entry: DirectionAuthorityEntry) -> None: ...

    def load_direction_authority(
        self, station_id: str
    ) -> DirectionAuthorityEntry | None: ...

    def close(self) -> None: ...


class PersistenceService:
    def __init__(self, repository: HistoryRepository, alarms: AlarmService) -> None:
        self.repository = repository
        self.alarms = alarms

    def save_operation(self, entry: OperationLogEntry) -> bool:
        return self._save(
            lambda: self.repository.append_operation(entry),
            entry.event_time_ms,
            source="SQLite/operation",
        )

    def save_telegram(self, entry: TelegramHistoryEntry) -> bool:
        return self._save(
            lambda: self.repository.append_telegram(entry),
            entry.event_time_ms,
            source="SQLite/telegram",
        )

    def save_direction_authority(self, entry: DirectionAuthorityEntry) -> bool:
        return self._save(
            lambda: self.repository.save_direction_authority(entry),
            entry.updated_at_ms,
            source="SQLite/direction",
        )

    def load_direction_authority(
        self, station_id: str, *, now_ms: int
    ) -> DirectionAuthorityEntry | None:
        try:
            entry = self.repository.load_direction_authority(station_id)
            self.alarms.clear_alarm(
                "PERSISTENCE_FAILURE", "SQLite/direction", now_ms=now_ms
            )
            return entry
        except Exception as exc:
            self.alarms.raise_alarm(
                "PERSISTENCE_FAILURE",
                AlarmLevel.CRITICAL,
                f"权威方向读取失败：{exc}",
                "SQLite/direction",
                now_ms=now_ms,
            )
            raise RuntimeError(f"权威方向读取失败：{exc}") from exc

    def close(self) -> None:
        self.repository.close()

    def _save(
        self, operation, now_ms: int, *, source: str
    ) -> bool:  # type: ignore[no-untyped-def]
        try:
            operation()
            self.alarms.clear_alarm("PERSISTENCE_FAILURE", source, now_ms=now_ms)
            return True
        except Exception as exc:
            self.alarms.raise_alarm(
                "PERSISTENCE_FAILURE",
                AlarmLevel.CRITICAL,
                f"历史记录保存失败：{exc}",
                source,
                now_ms=now_ms,
            )
            return False
