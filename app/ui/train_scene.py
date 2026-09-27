"""列车演示 2D 场景。

场景是协调器快照的可视化投影：它只更新图元位置和选中状态，不拥有定时器，
不执行列车推进，也不直接修改任何 TCC 控制器状态。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PyQt5.QtCore import QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from app.core.models import TopologyConfig
from app.services.dual_train_coordinator import DualTrainState, DualTrainStatus
from app.services.train_projection import TrainProjection, TrainProjectionMapper


class _TrainGraphicsItem(QGraphicsRectItem):
    """带业务 ID 的可点击列车图元。"""

    def __init__(self, train_id: str, on_clicked: Callable[[str], None]) -> None:
        super().__init__(-22.0, -11.0, 44.0, 22.0)
        self.train_id = train_id
        self._on_clicked = on_clicked
        self.setAcceptHoverEvents(True)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._on_clicked(self.train_id)
        super().mousePressEvent(event)


class TrainSceneWidget(QGraphicsView):
    """拓扑驱动的列车线路图和列车选择高亮。"""

    train_selected = pyqtSignal(str)

    def __init__(self, topology: TopologyConfig, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setObjectName("trainScene")
        self.setMinimumHeight(220)
        self.setRenderHint(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(1)  # Qt.ScrollBarAlwaysOff
        self.setVerticalScrollBarPolicy(1)
        self.mapper = TrainProjectionMapper(topology)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.selected_train_id: str | None = None
        self._train_items: dict[str, _TrainGraphicsItem] = {}
        self._train_labels: dict[str, QGraphicsSimpleTextItem] = {}
        self._draw_topology()

    def _draw_topology(self) -> None:
        self.scene.clear()
        self._train_items.clear()
        self._train_labels.clear()
        self.scene.setSceneRect(0.0, 0.0, self.mapper.scene_width, 190.0)
        track_pen = QPen(QColor("#394b59"), 4.0)
        separator_pen = QPen(QColor("#b8c7d3"), 1.0)
        for section in self.mapper.sections:
            center = (section.x_start + section.x_end) / 2.0
            self.scene.addLine(section.x_start, 88.0, section.x_end, 88.0, track_pen)
            self.scene.addLine(section.x_start, 70.0, section.x_start, 106.0, separator_pen)
            label = self.scene.addSimpleText(
                f"{section.section_id}\n{section.name}\n{section.length_m:g} m"
            )
            label.setFont(QFont(".AppleSystemUIFont", 9))
            label.setPos(center - 45.0, 112.0)
        if self.mapper.sections:
            last = self.mapper.sections[-1]
            self.scene.addLine(last.x_end, 70.0, last.x_end, 106.0, separator_pen)
        left = self.scene.addSimpleText("A站")
        right = self.scene.addSimpleText("B站")
        left.setFont(QFont(".AppleSystemUIFont", 10, QFont.Bold))
        right.setFont(QFont(".AppleSystemUIFont", 10, QFont.Bold))
        left.setPos(0.0, 15.0)
        right.setPos(self.mapper.scene_width - 28.0, 15.0)
        legend = self.scene.addSimpleText(
            "列车颜色：待发/准备/运行/停车/到达；点击图元或下拉框可选中列车"
        )
        legend.setPos(8.0, 165.0)

    @property
    def train_items(self) -> dict[str, _TrainGraphicsItem]:
        """供测试和页面同步使用的当前图元快照。"""
        return dict(self._train_items)

    def set_trains(self, trains: Iterable[DualTrainState]) -> None:
        projections = tuple(self.mapper.project(train) for train in trains)
        visible_ids = {item.train_id for item in projections}
        for train_id in tuple(self._train_items):
            if train_id not in visible_ids:
                item = self._train_items.pop(train_id)
                label = self._train_labels.pop(train_id)
                self.scene.removeItem(item)
                self.scene.removeItem(label)
        for projection in projections:
            item = self._train_items.get(projection.train_id)
            if item is None:
                item = _TrainGraphicsItem(projection.train_id, self._select_from_scene)
                self._train_items[projection.train_id] = item
                self.scene.addItem(item)
                label = QGraphicsSimpleTextItem(projection.train_id)
                label.setFont(QFont(".AppleSystemUIFont", 9, QFont.Bold))
                self._train_labels[projection.train_id] = label
                self.scene.addItem(label)
            self._update_item(item, self._train_labels[projection.train_id], projection)
        if self.selected_train_id not in visible_ids:
            self.selected_train_id = next(iter(visible_ids), None)
        self._refresh_selection_pen()

    def set_selected_train(self, train_id: str | None) -> None:
        if train_id is not None and train_id not in self._train_items:
            return
        self.selected_train_id = train_id
        self._refresh_selection_pen()

    def _select_from_scene(self, train_id: str) -> None:
        self.set_selected_train(train_id)
        self.train_selected.emit(train_id)

    def _refresh_selection_pen(self) -> None:
        for train_id, item in self._train_items.items():
            selected = train_id == self.selected_train_id
            item.setPen(QPen(QColor("#ff9800" if selected else "#1b4f72"), 3.0 if selected else 1.0))

    @staticmethod
    def _update_item(
        item: _TrainGraphicsItem,
        label: QGraphicsSimpleTextItem,
        projection: TrainProjection,
    ) -> None:
        item.setPos(QPointF(projection.x_center, projection.y_center))
        item.setBrush(QColor(_status_color(projection.status)))
        label.setText(
            f"{projection.train_id} · {projection.status.value}\n"
            f"{projection.section_id or '待发/已到达'} · {projection.current_speed_kmh:.0f} km/h"
        )
        label.setPos(projection.x_center - 42.0, projection.y_center - 42.0)


def _status_color(status: DualTrainStatus) -> str:
    return {
        DualTrainStatus.WAITING: "#78909c",
        DualTrainStatus.READY: "#43a047",
        DualTrainStatus.RUNNING: "#1976d2",
        DualTrainStatus.STOPPED: "#ef8c00",
        DualTrainStatus.ARRIVED: "#7e57c2",
        DualTrainStatus.RESET: "#78909c",
    }[status]
