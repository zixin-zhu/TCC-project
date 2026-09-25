"""存储失败转为可见告警，不传播为界面崩溃。"""

from app.infrastructure.sqlite_repository import OperationLogEntry, TelegramHistoryEntry
from app.services.alarm_service import AlarmLevel, AlarmService
from app.services.persistence_service import PersistenceService


class BrokenRepository:
    def append_operation(self, _entry):  # type: ignore[no-untyped-def]
        raise OSError("磁盘只读")

    def append_telegram(self, _entry):  # type: ignore[no-untyped-def]
        raise OSError("磁盘只读")

    def save_direction_authority(self, _entry):  # type: ignore[no-untyped-def]
        raise OSError("磁盘只读")

    def load_direction_authority(self, _station_id):  # type: ignore[no-untyped-def]
        raise OSError("磁盘只读")

    def close(self) -> None:
        pass


def test_persistence_failure_becomes_visible_alarm() -> None:
    alarms = AlarmService()
    service = PersistenceService(BrokenRepository(), alarms)

    saved = service.save_operation(
        OperationLogEntry("A", 1000, "测试", True, "成功", 1, {})
    )

    assert saved is False
    alarm = alarms.active_alarms()[0]
    assert alarm.level is AlarmLevel.CRITICAL
    assert alarm.code == "PERSISTENCE_FAILURE"
    assert "磁盘只读" in alarm.message


def test_successful_operation_save_does_not_clear_telegram_failure() -> None:
    class MixedRepository(BrokenRepository):
        def append_operation(self, _entry):  # type: ignore[no-untyped-def]
            return None

    alarms = AlarmService()
    service = PersistenceService(MixedRepository(), alarms)
    telegram = TelegramHistoryEntry(
        "A", 1000, "B_A_CTL", "TG_A_DEFAULT", "DEFAULT", {}, "7B7D", "AABBCCDD"
    )

    assert service.save_telegram(telegram) is False
    assert service.save_operation(
        OperationLogEntry("A", 1001, "测试", True, "成功", 1, {})
    )

    assert any(
        alarm.source == "SQLite/telegram" for alarm in alarms.active_alarms()
    )


def test_authority_read_failure_is_not_treated_as_missing_record() -> None:
    alarms = AlarmService()
    service = PersistenceService(BrokenRepository(), alarms)

    try:
        service.load_direction_authority("A", now_ms=1000)
    except RuntimeError as exc:
        assert "读取失败" in str(exc)
    else:
        raise AssertionError("权威方向读取失败必须阻止继续初始化")

    assert any(
        alarm.source == "SQLite/direction" for alarm in alarms.active_alarms()
    )
