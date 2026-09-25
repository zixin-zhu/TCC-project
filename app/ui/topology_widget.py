"""沿用原软件蓝灰配色的配置驱动线路概览图。"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from app.core.enums import TrackState
from app.core.models import TopologyConfig
from app.services.tcc_controller import TccSnapshot


class TopologyWidget(QWidget):
    """图元只保存业务 ID，颜色和文字全部来自控制器快照。"""

    def __init__(self, topology: TopologyConfig, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self._topology = topology
        self._snapshot: TccSnapshot | None = None
        self.setMinimumHeight(260)

    def set_snapshot(self, snapshot: TccSnapshot) -> None:
        self._snapshot = snapshot
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f7f9fc"))
        sections = self._topology.sections
        margin = 55
        width = max(1, self.width() - margin * 2)
        segment = width / max(1, len(sections))
        y = 125
        body_font = QFont()
        body_font.setPointSize(9)
        painter.setFont(body_font)
        for index, section in enumerate(sections):
            left = int(margin + index * segment)
            right = int(margin + (index + 1) * segment)
            state = (
                self._snapshot.tracks.get(section.id, TrackState.CLEAR)
                if self._snapshot is not None
                else TrackState.CLEAR
            )
            color = {
                TrackState.CLEAR: QColor("#263238"),
                TrackState.OCCUPIED: QColor("#d84343"),
                TrackState.FAULT_OCCUPIED: QColor("#8e24aa"),
                TrackState.SHUNT_BAD: QColor("#ef6c00"),
            }[state]
            painter.setPen(QPen(color, 6))
            painter.drawLine(left, y, right - 4, y)
            painter.setPen(QColor("#263238"))
            painter.drawText(left, y - 18, section.id)
            if self._snapshot is not None:
                code = self._snapshot.codes.get(section.id)
                if code is not None:
                    painter.setPen(QColor("#2f6fad"))
                    painter.drawText(left, y + 28, code.code.value)

        painter.setPen(QColor("#2f6fad"))
        heading_font = QFont()
        heading_font.setPointSize(11)
        heading_font.setBold(True)
        painter.setFont(heading_font)
        direction = self._snapshot.running_direction if self._snapshot else "--"
        lock_text = "（安全锁闭）" if self._snapshot and self._snapshot.direction_operation_locked else ""
        painter.drawText(margin, 55, f"运行方向：{direction} {lock_text}")
