"""不依赖 Qt 的结构化告警管理。"""

from dataclasses import dataclass, replace
from enum import Enum


class AlarmLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class AlarmRecord:
    code: str
    level: AlarmLevel
    message: str
    source: str
    occurred_at_ms: int
    active: bool = True
    cleared_at_ms: int | None = None


class AlarmService:
    """以“告警码 + 来源”去重，同时保留清除后的审计历史。"""

    def __init__(self) -> None:
        self._active: dict[tuple[str, str], AlarmRecord] = {}
        self._history: list[AlarmRecord] = []

    def raise_alarm(
        self,
        code: str,
        level: AlarmLevel,
        message: str,
        source: str,
        *,
        now_ms: int,
    ) -> AlarmRecord:
        key = (code, source)
        existing = self._active.get(key)
        if existing is not None:
            return existing
        record = AlarmRecord(code, level, message, source, now_ms)
        self._active[key] = record
        self._history.append(record)
        return record

    def clear_alarm(
        self, code: str, source: str, *, now_ms: int
    ) -> AlarmRecord | None:
        key = (code, source)
        existing = self._active.pop(key, None)
        if existing is None:
            return None
        cleared = replace(existing, active=False, cleared_at_ms=now_ms)
        self._history[self._history.index(existing)] = cleared
        return cleared

    def active_alarms(self) -> tuple[AlarmRecord, ...]:
        return tuple(
            sorted(
                self._active.values(),
                key=lambda item: (item.level.value, item.occurred_at_ms, item.code),
            )
        )

    def history(self) -> tuple[AlarmRecord, ...]:
        return tuple(self._history)
