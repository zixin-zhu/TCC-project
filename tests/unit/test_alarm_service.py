"""告警去重、清除和历史保留测试。"""

from app.services.alarm_service import AlarmLevel, AlarmService


def test_same_active_alarm_is_deduplicated_and_can_be_cleared() -> None:
    service = AlarmService()

    first = service.raise_alarm(
        "LEU_DEFAULT", AlarmLevel.CRITICAL, "LEU 输入断联", "LEU_A_1", now_ms=1000
    )
    duplicate = service.raise_alarm(
        "LEU_DEFAULT", AlarmLevel.CRITICAL, "LEU 输入断联", "LEU_A_1", now_ms=1100
    )
    cleared = service.clear_alarm("LEU_DEFAULT", "LEU_A_1", now_ms=1200)

    assert duplicate == first
    assert cleared is not None and cleared.active is False
    assert service.active_alarms() == ()
    assert len(service.history()) == 1


def test_alarm_identity_includes_source() -> None:
    service = AlarmService()
    service.raise_alarm("TRACK_FAULT", AlarmLevel.WARNING, "区段故障", "Q1", now_ms=1)
    service.raise_alarm("TRACK_FAULT", AlarmLevel.WARNING, "区段故障", "Q2", now_ms=2)

    assert {item.source for item in service.active_alarms()} == {"Q1", "Q2"}
