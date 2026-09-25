"""经典控制台风格的 A/B 双站联合仿真主窗口。"""

from __future__ import annotations

from typing import Protocol

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.tcc_controller import TccController
from app.services.dual_train_coordinator import DualTrainCoordinator
from app.ui.corridor_overview_widget import CorridorOverviewWidget
from app.ui.dual_operations_pages import (
    DirectionOperationsPage,
    LeuComparisonPage,
    NetworkStatusPage,
    SignalOperationsPage,
    TrackOperationsPage,
    TrainOperationsPage,
    TsrOperationsPage,
)
from app.ui.dual_snapshot import DualStationSnapshot, DualStationSnapshotAggregator
from app.ui.global_status_bar import GlobalStatusBar
from app.ui.station_detail_widget import StationDetailWidget
from app.ui.station_summary_card import StationSummaryCard
from app.ui.styles import CLASSIC_CONSOLE_QSS


NAVIGATION_ITEMS = (
    "双站总览",
    "联合站场图",
    "A站控制",
    "B站控制",
    "轨道电路",
    "信号机控制",
    "应答器/LEU",
    "临时限速",
    "区间改方",
    "通信状态",
    "列车演示",
    "日志告警",
)


class StationRuntimePort(Protocol):
    controller: TccController


class DualRuntimePort(Protocol):
    station_a: StationRuntimePort
    station_b: StationRuntimePort

    def stop(self, *, timeout_ms: int = 3000) -> bool: ...

    def set_station_network_fault(self, station_id: str, enabled: bool): ...  # type: ignore[no-untyped-def]


class DualReadOnlyPage(QWidget):
    """按主题并排展示两站实时字段，提供非空且无伪操作的详情页。"""

    def __init__(self, title: str, kind: str, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.kind = kind
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        self.table = QTableWidget(2, 3)
        self.table.setHorizontalHeaderLabels(["站点", "关键状态", "详细信息"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.note = QLabel(
            "数据来自两站控制器快照；本页不绕过控制器修改状态。"
        )
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

    def set_snapshot(self, model: DualStationSnapshot) -> None:
        for row, snapshot in enumerate((model.station_a, model.station_b)):
            summary, detail = self._texts(snapshot, model)
            values = (f"{snapshot.station_id}站", summary, detail)
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

    def _texts(
        self, snapshot, model: DualStationSnapshot  # type: ignore[no-untyped-def]
    ) -> tuple[str, str]:
        if self.kind == "track":
            non_clear = [
                f"{key}={value.value}"
                for key, value in snapshot.tracks.items()
                if value.value != "CLEAR"
            ]
            codes = ", ".join(
                f"{key}:{value.code.value}" for key, value in snapshot.codes.items()
            )
            details = f"{'; '.join(non_clear) or '全线空闲'}；码序 {codes}"
            return f"非空闲 {len(non_clear)}", details
        if self.kind == "signal":
            signals = ", ".join(
                f"{key}:{value.aspect.value}" for key, value in snapshot.signals.items()
            )
            return f"信号机 {len(snapshot.signals)}", signals
        if self.kind == "telegram":
            item = snapshot.telegram
            return (
                f"{item.port_id} · {item.mode.value}",
                f"模板 {item.template_id}；{item.reason}",
            )
        if self.kind == "tsr":
            detail = ", ".join(
                f"{item.tsr_id}:{item.speed_kmh:g}km/h {item.state.value}"
                for item in snapshot.temporary_speeds
            )
            return f"临时限速 {len(snapshot.temporary_speeds)}", detail or "无活动命令"
        if self.kind == "direction":
            return snapshot.running_direction, (
                "安全锁闭" if snapshot.direction_operation_locked else "允许作业"
            )
        if self.kind == "network":
            return snapshot.connection_state.value, (
                f"发送 {snapshot.network_sent}；接收 {snapshot.network_received}；"
                f"版本 {snapshot.state_version}"
            )
        if self.kind == "train":
            return (
                "安全锁闭" if model.operation_locked else "联合运行条件满足",
                "当前阶段显示联合运行许可；列车位置与操作由唯一联合协调器管理。",
            )
        operations = tuple(snapshot.operation_logs[:5])
        alarms = tuple(snapshot.alarms)
        return f"日志 {len(operations)} · 告警 {len(alarms)}", (
            "; ".join(item.operation for item in operations) or "暂无操作日志"
        )


class DualStationMainWindow(QMainWindow):
    """组合两个独立控制器；业务写操作仍由各站详情组件发起。"""

    def __init__(self, runtime: DualRuntimePort) -> None:
        super().__init__()
        self.runtime = runtime
        self.controller_a = runtime.station_a.controller
        self.controller_b = runtime.station_b.controller
        self.aggregator = DualStationSnapshotAggregator(self)
        self.train_coordinator = DualTrainCoordinator(
            self.controller_a, self.controller_b, parent=self
        )
        self._closed = False
        self.setWindowTitle("CTCS-2 车站列控中心（TCC）双站联合仿真系统")
        self.resize(1440, 900)
        self.setStyleSheet(CLASSIC_CONSOLE_QSS)
        self._build_ui()
        self.aggregator.snapshot_changed.connect(self.refresh)
        self.controller_a.add_snapshot_listener(self.aggregator.update_a)
        self.controller_b.add_snapshot_listener(self.aggregator.update_b)
        self.aggregator.update_a(self.controller_a.snapshot)
        self.aggregator.update_b(self.controller_b.snapshot)
        self._connect_lifecycle_signals()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("dualMainRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        header_bar = QWidget()
        header_bar.setObjectName("consoleHeader")
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("CTCS-2 车站列控中心（TCC）双站联合仿真系统")
        title.setObjectName("applicationTitle")
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        root.addWidget(header_bar)
        self.global_status = GlobalStatusBar()
        root.addWidget(self.global_status)

        body = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setObjectName("sideNavigation")
        self.navigation.addItems(NAVIGATION_ITEMS)
        self.navigation.setFixedWidth(150)
        self.pages = QStackedWidget()
        body.addWidget(self.navigation)
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        self._build_pages()
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)

    def _build_pages(self) -> None:
        config_a = self.controller_a.config
        config_b = self.controller_b.config
        self.station_a_card = StationSummaryCard(config_a)
        self.station_b_card = StationSummaryCard(config_b)
        self.station_a_card.navigate_requested.connect(self._navigate_station)
        self.station_b_card.navigate_requested.connect(self._navigate_station)

        home = QWidget()
        home_layout = QVBoxLayout(home)
        cards = QHBoxLayout()
        cards.addWidget(self.station_a_card)
        cards.addWidget(self.station_b_card)
        home_layout.addLayout(cards)
        self.corridor = CorridorOverviewWidget(
            config_a.topology, config_a.balise_groups
        )
        self.corridor.section_clicked.connect(self._navigate_section)
        self.corridor.setMaximumHeight(430)
        home_layout.addWidget(self.corridor)
        self.recent_table = QTableWidget(0, 3)
        self.recent_table.setHorizontalHeaderLabels(
            ["站点", "类型", "最近事件/严重告警"]
        )
        self.recent_table.horizontalHeader().setStretchLastSection(True)
        self.recent_table.setMinimumHeight(100)
        home_layout.addWidget(self.recent_table, 1)
        self.pages.addWidget(home)

        corridor_page = QWidget()
        corridor_layout = QVBoxLayout(corridor_page)
        self.corridor_full = CorridorOverviewWidget(
            config_a.topology, config_a.balise_groups
        )
        self.corridor_full.section_clicked.connect(self._navigate_section)
        self.corridor_full.setMaximumHeight(470)
        corridor_layout.addWidget(self.corridor_full)
        detail_heading = QLabel("区段双站一致性明细")
        detail_heading.setObjectName("pageHeading")
        corridor_layout.addWidget(detail_heading)
        self.corridor_detail_table = QTableWidget(0, 7)
        self.corridor_detail_table.setHorizontalHeaderLabels(
            ["区段", "归属", "A站状态/码序", "B站状态/码序", "界面显示", "一致性", "判定依据"]
        )
        self.corridor_detail_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.corridor_detail_table.verticalHeader().setVisible(False)
        corridor_header = self.corridor_detail_table.horizontalHeader()
        corridor_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        corridor_header.setSectionResizeMode(6, QHeaderView.Stretch)
        corridor_layout.addWidget(self.corridor_detail_table, 1)
        self.pages.addWidget(corridor_page)

        self.station_a_detail = StationDetailWidget(
            self.controller_a, include_train_page=False
        )
        self.station_b_detail = StationDetailWidget(
            self.controller_b, include_train_page=False
        )
        self.pages.addWidget(self._wrap(self.station_a_detail))
        self.pages.addWidget(self._wrap(self.station_b_detail))

        self.track_operations_page = TrackOperationsPage(
            self.controller_a, self.controller_b
        )
        self.signal_operations_page = SignalOperationsPage(
            self.controller_a, self.controller_b
        )
        self.leu_comparison_page = LeuComparisonPage()
        self.tsr_operations_page = TsrOperationsPage(
            self.controller_a, self.controller_b
        )
        self.direction_operations_page = DirectionOperationsPage(
            self.controller_a,
            self.controller_b,
            getattr(self.runtime, "set_station_network_fault", None),
        )
        self.network_status_page = NetworkStatusPage(
            self.controller_a,
            self.controller_b,
            getattr(self.runtime, "set_station_network_fault", None),
        )
        self.train_operations_page = TrainOperationsPage(
            self.controller_a,
            self.controller_b,
            self.train_coordinator,
        )
        for page in (
            self.track_operations_page,
            self.signal_operations_page,
            self.leu_comparison_page,
            self.tsr_operations_page,
            self.direction_operations_page,
            self.network_status_page,
            self.train_operations_page,
        ):
            self.pages.addWidget(page)
        self.log_page = DualReadOnlyPage("双站操作日志与活动告警", "log")
        self.pages.addWidget(self.log_page)

    @staticmethod
    def _wrap(widget: QWidget) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
        return page

    def _connect_lifecycle_signals(self) -> None:
        lifecycle_signal = getattr(self.runtime, "lifecycle_changed", None)
        if lifecycle_signal is not None:
            lifecycle_signal.connect(
                lambda state: self.global_status.set_lifecycle_text(state.value)
            )
        failure_signal = getattr(self.runtime, "startup_failed", None)
        if failure_signal is not None:
            failure_signal.connect(
                lambda reason: self.global_status.set_lifecycle_text(
                    reason, failed=True
                )
            )

    def refresh(self, model: DualStationSnapshot) -> None:
        self.global_status.set_snapshot(model)
        lock_reason = (
            "双站通信、方向或共享区段状态不满足联合行车条件"
        )
        self.station_a_detail.set_external_operation_lock(
            model.operation_locked, lock_reason
        )
        self.station_b_detail.set_external_operation_lock(
            model.operation_locked, lock_reason
        )
        self.station_a_card.set_snapshot(model.station_a)
        self.station_b_card.set_snapshot(model.station_b)
        self.corridor.set_snapshot(model)
        self.corridor_full.set_snapshot(model)
        self._fill_corridor_details(model)
        for page in (
            self.track_operations_page,
            self.signal_operations_page,
            self.leu_comparison_page,
            self.tsr_operations_page,
            self.direction_operations_page,
            self.network_status_page,
            self.train_operations_page,
            self.log_page,
        ):
            page.set_snapshot(model)
        self._fill_recent(model)

    def _fill_corridor_details(self, model: DualStationSnapshot) -> None:
        """展示每个物理区段的双站视角，便于定位不一致和码序来源。"""
        self.corridor_detail_table.setRowCount(len(model.sections))
        for row, section in enumerate(model.sections):
            section_id = section.section_id
            if section_id.startswith("A_"):
                owner = "A站"
            elif section_id.startswith("B_"):
                owner = "B站"
            else:
                owner = "共享"
            code_a = model.station_a.codes[section_id].code.value
            code_b = model.station_b.codes[section_id].code.value
            values = (
                section_id,
                owner,
                f"{section.station_a_state.value} / {code_a}",
                f"{section.station_b_state.value} / {code_b}",
                section.display_state.value if section.display_state is not None else "安全未知",
                "一致" if section.consistent else "不一致",
                section.reason,
            )
            for column, value in enumerate(values):
                self.corridor_detail_table.setItem(
                    row, column, QTableWidgetItem(value)
                )

    def _fill_recent(self, model: DualStationSnapshot) -> None:
        rows: list[tuple[str, str, str]] = []
        for snapshot in (model.station_a, model.station_b):
            for alarm in snapshot.alarms:
                if alarm.level.value == "CRITICAL":
                    rows.append((snapshot.station_id, "严重告警", alarm.message))
            for item in snapshot.operation_logs[:5]:
                rows.append((snapshot.station_id, "操作", f"{item.operation}：{item.reason}"))
        self.recent_table.setRowCount(min(10, len(rows)))
        for row, values in enumerate(rows[:10]):
            for column, value in enumerate(values):
                self.recent_table.setItem(row, column, QTableWidgetItem(value))

    def _navigate_station(self, station_id: str) -> None:
        self.navigation.setCurrentRow(2 if station_id == "A" else 3)

    def _navigate_section(self, section_id: str) -> None:
        if section_id.startswith("A_"):
            self._navigate_station("A")
            self.station_a_detail.tabs.setCurrentIndex(1)
        elif section_id.startswith("B_"):
            self._navigate_station("B")
            self.station_b_detail.tabs.setCurrentIndex(1)
        else:
            self.navigation.setCurrentRow(4)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._closed:
            event.accept()
            return
        self.station_a_detail.stop_activity()
        self.station_b_detail.stop_activity()
        self.train_coordinator.shutdown()
        if not self.runtime.stop(timeout_ms=3000):
            self.global_status.set_lifecycle_text(
                "关闭失败：网络停止请求不可撤销，列车演示保持安全停止",
                failed=True,
            )
            event.ignore()
            return
        self._closed = True
        event.accept()
