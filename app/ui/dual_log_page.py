"""A/B 双站上下分区、逐条展示的日志告警页面。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.infrastructure.sqlite_repository import OperationLogEntry
from app.services.alarm_service import AlarmRecord
from app.services.tcc_controller import TccSnapshot
from app.ui.dual_snapshot import DualStationSnapshot


@dataclass(frozen=True)
class LogAlarmRow:
    """页面统一展示的一条业务事件。"""

    station_id: str
    event_time_ms: int
    event_type: str
    level: str
    code_or_operation: str
    source: str
    result: str
    message: str
    state_version: int
    active: bool | None = None


class DualLogAlarmPage(QWidget):
    """固定 A 上 B 下的双站日志与告警列表。"""

    HEADERS = ["时间", "类型", "级别", "代码/操作", "来源", "结果", "说明", "版本"]
    MAX_ROWS = 200

    def __init__(self, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.station_a_group, self.station_a_table = self._build_station_panel("A")
        self.station_b_group, self.station_b_table = self._build_station_panel("B")
        layout.addWidget(self.station_a_group, 1)
        layout.addWidget(self.station_b_group, 1)

    def _build_station_panel(self, station_id: str) -> tuple[QGroupBox, QTableWidget]:
        group = QGroupBox(f"{station_id}站 · 日志与告警（最多 {self.MAX_ROWS} 条）")
        table = QTableWidget(0, len(self.HEADERS))
        table.setHorizontalHeaderLabels(self.HEADERS)
        table.setObjectName(f"station{station_id}LogTable")
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        table.setWordWrap(False)
        table.setAlternatingRowColors(True)
        box_layout = QVBoxLayout(group)
        box_layout.addWidget(table)
        return group, table

    def set_snapshot(self, model: DualStationSnapshot) -> None:
        self._fill_table(self.station_a_table, model.station_a)
        self._fill_table(self.station_b_table, model.station_b)

    def _fill_table(self, table: QTableWidget, snapshot: TccSnapshot) -> None:
        rows = self.rows_for_snapshot(snapshot)
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.event_time_ms,
                row.event_type,
                row.level,
                row.code_or_operation,
                row.source,
                row.result,
                row.message,
                row.state_version,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 6:
                    item.setToolTip(row.message)
                if row.event_type == "告警" and row.active:
                    item.setForeground(QColor("#b42318"))
                elif row.event_type == "告警恢复":
                    item.setForeground(QColor("#71808c"))
                table.setItem(row_index, column, item)

    @classmethod
    def rows_for_snapshot(cls, snapshot: TccSnapshot) -> tuple[LogAlarmRow, ...]:
        """合并操作与告警历史，按时间倒序并限制单站 200 条。"""
        rows: list[LogAlarmRow] = []
        for item in snapshot.operation_logs:
            rows.append(cls._operation_row(item))
        history: Iterable[AlarmRecord] = getattr(
            snapshot, "alarm_history", tuple(snapshot.alarms)
        )
        for item in history:
            active = item.active
            rows.append(
                LogAlarmRow(
                    snapshot.station_id,
                    item.occurred_at_ms if active else (item.cleared_at_ms or item.occurred_at_ms),
                    "告警" if active else "告警恢复",
                    item.level.value,
                    item.code,
                    item.source,
                    "活动" if active else "已恢复",
                    item.message,
                    0,
                    active,
                )
            )
        rows.sort(key=lambda item: item.event_time_ms, reverse=True)
        return tuple(rows[: cls.MAX_ROWS])

    @staticmethod
    def _operation_row(item: OperationLogEntry) -> LogAlarmRow:
        return LogAlarmRow(
            item.station_id,
            item.event_time_ms,
            "操作",
            "INFO" if item.success else "WARNING",
            item.operation,
            "controller",
            "成功" if item.success else "拒绝",
            item.reason,
            item.state_version,
            None,
        )
