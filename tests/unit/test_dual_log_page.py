"""A/B 上下分区日志告警页的逐条展示测试。"""

from types import SimpleNamespace

from PyQt5.QtWidgets import QTableWidget

from app.core.enums import ConnectionState
from app.infrastructure.sqlite_repository import OperationLogEntry
from app.services.alarm_service import AlarmLevel, AlarmRecord
from app.ui.dual_log_page import DualLogAlarmPage
from app.ui.dual_snapshot import DualStationSnapshot


def _station(station_id: str, rows: int):
    operations = tuple(
        OperationLogEntry(station_id, index, f"操作-{index}", True, "完成", index, {})
        for index in range(rows)
    )
    history = (
        AlarmRecord(
            f"{station_id}-A",
            AlarmLevel.WARNING,
            "已恢复告警",
            "test",
            rows + 1,
            active=False,
            cleared_at_ms=rows + 2,
        ),
        AlarmRecord(
            f"{station_id}-B", AlarmLevel.CRITICAL, "活动告警", "test", rows + 3
        ),
    )
    return SimpleNamespace(
        station_id=station_id,
        operation_logs=operations,
        alarms=tuple(item for item in history if item.active),
        alarm_history=history,
    )


def _model():
    return SimpleNamespace(station_a=_station("A", 205), station_b=_station("B", 2))


def test_page_splits_a_and_b_and_caps_each_station_at_200(qtbot) -> None:  # type: ignore[no-untyped-def]
    page = DualLogAlarmPage()
    qtbot.addWidget(page)

    page.set_snapshot(_model())

    assert page.station_a_table.rowCount() == 200
    assert page.station_b_table.rowCount() == 4
    assert page.station_a_group.title().startswith("A站")
    assert page.station_b_group.title().startswith("B站")
    assert "活动" in page.station_b_table.item(0, 5).text()
    assert any(
        page.station_b_table.item(row, 1).text() == "告警恢复"
        for row in range(page.station_b_table.rowCount())
    )


def test_page_has_readable_columns_and_no_heartbeat_rows(qtbot) -> None:  # type: ignore[no-untyped-def]
    page = DualLogAlarmPage()
    qtbot.addWidget(page)
    page.set_snapshot(_model())

    for table in (page.station_a_table, page.station_b_table):
        assert isinstance(table, QTableWidget)
        assert table.columnCount() == 8
        headers = [table.horizontalHeaderItem(index).text() for index in range(8)]
        assert headers == ["时间", "类型", "级别", "代码/操作", "来源", "结果", "说明", "版本"]
        visible = " ".join(
            table.item(row, column).text()
            for row in range(table.rowCount())
            for column in range(table.columnCount())
            if table.item(row, column) is not None
        )
        assert "HEARTBEAT" not in visible
