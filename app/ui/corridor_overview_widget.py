"""配置驱动的 A/B 联合线路总览图。"""

from __future__ import annotations

from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QPolygon
from PyQt5.QtWidgets import QWidget

from app.core.enums import TrackState
from app.core.models import BaliseGroupsConfig, TopologyConfig
from app.ui.dual_snapshot import DualStationSnapshot, SectionConsistency


_STATE_TEXT = {
    TrackState.CLEAR: "空闲",
    TrackState.OCCUPIED: "占用",
    TrackState.FAULT_OCCUPIED: "故障占用",
    TrackState.SHUNT_BAD: "分路不良",
}

_STATE_COLOR = {
    TrackState.CLEAR: QColor("#33424e"),
    TrackState.OCCUPIED: QColor("#c62828"),
    TrackState.FAULT_OCCUPIED: QColor("#7b1fa2"),
    TrackState.SHUNT_BAD: QColor("#c05a00"),
}


class CorridorOverviewWidget(QWidget):
    """按配置长度绘制区段；点击只发导航信号，不直接修改业务状态。"""

    section_clicked = pyqtSignal(str)

    def __init__(
        self,
        topology: TopologyConfig,
        balise_groups: BaliseGroupsConfig,
        parent=None,  # type: ignore[no-untyped-def]
    ) -> None:
        super().__init__(parent)
        self._topology = topology
        self._balise_groups = balise_groups
        self._snapshot: DualStationSnapshot | None = None
        self._section_rects: dict[str, QRect] = {}
        self.setMinimumHeight(330)
        self.setAccessibleName("A/B 双站联合线路图")

    @property
    def section_order(self) -> tuple[str, ...]:
        return tuple(section.id for section in self._topology.sections)

    @property
    def section_rects(self) -> dict[str, QRect]:
        """返回绘图矩形副本，供只读命中测试与辅助功能使用。"""
        return {
            section_id: QRect(rect)
            for section_id, rect in self._section_rects.items()
        }

    def set_snapshot(self, snapshot: DualStationSnapshot) -> None:
        self._snapshot = snapshot
        descriptions = [
            f"{item.section_id}：{self._status_text(item)}"
            for item in snapshot.sections
        ]
        descriptions.extend(
            f"{signal.id}：{self.signal_status_text(signal.id)}"
            for signal in self._topology.signals
        )
        if snapshot.operation_locked:
            descriptions.insert(0, "安全锁闭")
        self.setAccessibleDescription("；".join(descriptions))
        self.update()

    def section_status_text(self, section_id: str) -> str:
        item = self._section_model(section_id)
        return self._status_text(item)

    def signal_status_text(self, signal_id: str) -> str:
        """双站信号结果不一致时不选择任一侧作为联合显示真值。"""
        if self._snapshot is None:
            return "等待双站快照"
        signal_a = self._snapshot.station_a.signals.get(signal_id)
        signal_b = self._snapshot.station_b.signals.get(signal_id)
        if signal_a is None or signal_b is None:
            return "信号不一致：一侧缺失"
        state_a = self._signal_state(signal_a)
        state_b = self._signal_state(signal_b)
        if state_a != state_b:
            return (
                f"信号不一致：A={signal_a.aspect.value}，"
                f"B={signal_b.aspect.value}"
            )
        if self._snapshot.operation_locked:
            return f"安全锁闭（双站实际={signal_a.aspect.value}）"
        return signal_a.aspect.value

    def section_at(self, point: QPoint) -> str | None:
        for section_id, rect in self._section_rects.items():
            if rect.contains(point):
                return section_id
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            section_id = self.section_at(event.pos())
            if section_id is not None:
                self.section_clicked.emit(section_id)
                event.accept()
                return
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        self._section_rects = self._layout_sections()
        self._draw_header(painter)
        self._draw_temporary_speeds(painter)
        self._draw_sections(painter)
        self._draw_signals(painter)
        self._draw_balises(painter)
        self._draw_legend(painter)

    def _layout_sections(self) -> dict[str, QRect]:
        sections = self._topology.sections
        if not sections:
            return {}
        margin = 46
        usable = max(1, self.width() - margin * 2)
        total_length = max(1.0, sum(item.length_m for item in sections))
        cursor = float(margin)
        result: dict[str, QRect] = {}
        for index, section in enumerate(sections):
            if index == len(sections) - 1:
                right = margin + usable
            else:
                right = margin + round(
                    usable
                    * sum(item.length_m for item in sections[: index + 1])
                    / total_length
                )
            left = round(cursor)
            result[section.id] = QRect(left, 145, max(1, right - left), 30)
            cursor = float(right)
        return result

    def _draw_header(self, painter: QPainter) -> None:
        snapshot = self._snapshot
        painter.setPen(QColor("#07558f"))
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        if snapshot is None:
            painter.drawText(46, 35, "联合线路图 · 等待双站快照")
            return
        direction = (
            "A站 → B站"
            if snapshot.authoritative_direction.value == "A_TO_B"
            else "B站 → A站"
        )
        painter.drawText(46, 35, f"权威运行方向：{direction}")
        if snapshot.operation_locked:
            painter.fillRect(0, 48, self.width(), 25, QColor("#b42318"))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                46,
                66,
                "安全锁闭：通信、方向或共享区段状态尚未满足条件",
            )
        painter.setPen(QPen(QColor("#1976d2"), 3))
        start_x, end_x = 80, max(100, self.width() - 80)
        if snapshot.authoritative_direction.value == "B_TO_A":
            start_x, end_x = end_x, start_x
        painter.drawLine(start_x, 96, end_x, 96)
        tip = QPoint(end_x, 96)
        sign = 1 if end_x > start_x else -1
        painter.drawLine(tip, QPoint(end_x - 12 * sign, 89))
        painter.drawLine(tip, QPoint(end_x - 12 * sign, 103))

    def _draw_sections(self, painter: QPainter) -> None:
        body_font = QFont()
        body_font.setPointSize(8)
        body_font.setBold(False)
        painter.setFont(body_font)
        for section in self._topology.sections:
            rect = self._section_rects[section.id]
            model = self._section_model(section.id, required=False)
            if model is None or model.display_state is None:
                painter.fillRect(rect, QColor("#f6c945"))
                painter.setPen(QPen(QColor("#1f2d38"), 2))
                step = 12
                for offset in range(-rect.height(), rect.width(), step):
                    painter.drawLine(
                        rect.left() + offset,
                        rect.bottom(),
                        rect.left() + offset + rect.height(),
                        rect.top(),
                    )
                status_text = "不一致" if model is not None else "等待"
            else:
                painter.fillRect(rect, _STATE_COLOR[model.display_state])
                status_text = _STATE_TEXT[model.display_state]
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawRect(rect)
            painter.setPen(QColor("#1f2d38"))
            painter.drawText(
                QRect(rect.left(), rect.top() - 39, rect.width(), 36),
                Qt.AlignCenter,
                f"{section.id}\n{section.name}",
            )
            code = self._code_text(section.id)
            painter.drawText(
                QRect(rect.left(), rect.bottom() + 5, rect.width(), 58),
                Qt.AlignHCenter | Qt.AlignTop,
                f"{status_text}\n{code}\n{section.length_m:g} m",
            )

    def _draw_signals(self, painter: QPainter) -> None:
        if self._snapshot is None:
            return
        section_signal_count: dict[str, int] = {}
        for signal in self._topology.signals:
            rect = self._section_rects.get(signal.protects_section)
            result_a = self._snapshot.station_a.signals.get(signal.id)
            result_b = self._snapshot.station_b.signals.get(signal.id)
            if rect is None or result_a is None or result_b is None:
                continue
            if self._signal_state(result_a) != self._signal_state(result_b):
                color = QColor("#f6c945")
                label = f"{signal.id} 不一致"
            elif self._snapshot.operation_locked:
                color = QColor("#59636b")
                label = f"{signal.id} 锁闭"
            else:
                color = {
                    "GREEN": QColor("#1d9d55"),
                    "YELLOW": QColor("#e0a300"),
                    "DOUBLE_YELLOW": QColor("#e0a300"),
                    "RED": QColor("#d72638"),
                    "RED_LAMP_FAILURE": QColor("#7b1fa2"),
                    "DARK": QColor("#59636b"),
                }.get(result_a.aspect.value, QColor("#59636b"))
                label = signal.id
            offset = section_signal_count.get(signal.protects_section, 0)
            section_signal_count[signal.protects_section] = offset + 1
            center = QPoint(rect.left() + 7 + offset * 30, rect.top() - 52)
            painter.setBrush(color)
            painter.setPen(QColor("#1f2d38"))
            painter.drawEllipse(center, 6, 6)
            painter.drawText(center.x() + 9, center.y() + 4, label)

    def _draw_balises(self, painter: QPainter) -> None:
        section_by_id = {item.id: item for item in self._topology.sections}
        painter.setBrush(QColor("#f2c94c"))
        painter.setPen(QColor("#6b5600"))
        for group in self._balise_groups.groups:
            rect = self._section_rects.get(group.section_id)
            section = section_by_id.get(group.section_id)
            # 空安全：应答器组可能没有成员(配置异常或未录入)，此时无法求取
            # 首枚应答器的位置，直接跳过该组，避免 balises[0] 越界崩溃。
            if rect is None or section is None or not group.balises:
                continue
            first = group.balises[0]
            ratio = min(1.0, max(0.0, first.position_m / section.length_m))
            x = round(rect.left() + rect.width() * ratio)
            y = rect.bottom() + 60
            painter.drawPolygon(
                QPolygon([QPoint(x, y - 9), QPoint(x - 7, y + 5), QPoint(x + 7, y + 5)])
            )
            painter.drawText(x + 9, y + 4, group.id)

    def _draw_temporary_speeds(self, painter: QPainter) -> None:
        if self._snapshot is None or not self._section_rects:
            return
        restrictions = (
            tuple(self._snapshot.station_a.temporary_speeds)
            + tuple(self._snapshot.station_b.temporary_speeds)
        )
        if not restrictions:
            return
        first = next(iter(self._section_rects.values())).left()
        last = list(self._section_rects.values())[-1].right()
        total = max(1.0, sum(item.length_m for item in self._topology.sections))
        painter.setPen(QPen(QColor("#d69e00"), 5))
        for item in restrictions:
            left = first + round((last - first) * max(0.0, item.start_m) / total)
            right = first + round((last - first) * min(total, item.end_m) / total)
            painter.drawLine(left, 118, right, 118)
            painter.drawText(left, 113, f"{item.tsr_id} {item.speed_kmh:g}km/h")

    def _draw_legend(self, painter: QPainter) -> None:
        legend_font = QFont()
        legend_font.setPointSize(8)
        painter.setFont(legend_font)
        painter.setPen(QColor("#1f2d38"))
        painter.drawText(
            46,
            self.height() - 35,
            "状态：空闲(深灰)　占用(红)　故障占用(紫)　分路不良(橙)　"
            "双站不一致(黄黑并标字)",
        )

    def _section_model(
        self, section_id: str, *, required: bool = True
    ) -> SectionConsistency | None:
        if self._snapshot is not None:
            for item in self._snapshot.sections:
                if item.section_id == section_id:
                    return item
        if required:
            raise KeyError(section_id)
        return None

    @staticmethod
    def _status_text(item: SectionConsistency) -> str:
        if not item.consistent:
            return "不一致"
        if item.display_state is None:
            return "未知"
        return _STATE_TEXT[item.display_state]

    def _code_text(self, section_id: str) -> str:
        if self._snapshot is None:
            return "码序 --"
        code_a = self._snapshot.station_a.codes.get(section_id)
        code_b = self._snapshot.station_b.codes.get(section_id)
        if section_id.startswith("A_"):
            return f"码序 {code_a.code.value}" if code_a else "码序 --"
        if section_id.startswith("B_"):
            return f"码序 {code_b.code.value}" if code_b else "码序 --"
        if code_a is None or code_b is None:
            return "码序 --"
        if code_a.code is code_b.code:
            return f"码序 {code_a.code.value}"
        return f"码序 A:{code_a.code.value}/B:{code_b.code.value}"

    @staticmethod
    def _signal_state(signal) -> tuple[object, bool, bool, bool]:  # type: ignore[no-untyped-def]
        return (
            signal.aspect,
            signal.relay_hj,
            signal.relay_uj,
            signal.relay_lj,
        )
