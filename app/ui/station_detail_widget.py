"""可嵌入的 TCC 单站业务详情组件。"""

import json
from collections.abc import Callable

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.enums import RunningDirection, TrackInputSource, TrackState
from app.core.models import OperationResult
from app.domain.direction_change import direction_requester_station
from app.services.tcc_controller import TccController, TccSnapshot
from app.services.shared_state_request_service import SharedStateRequestService
from app.services.train_demo_service import TrainDemoService
from app.ui.styles import configure_combo_box, relay_text, set_semantic_state
from app.ui.topology_widget import TopologyWidget


class _RatioTableWidget(QTableWidget):
    """按指定比例分配列宽，窗口缩放时保持业务字段的视觉层级。"""

    def __init__(self, column_count: int, ratios: tuple[int, ...]) -> None:
        super().__init__(0, column_count)
        if len(ratios) != column_count or any(ratio <= 0 for ratio in ratios):
            raise ValueError("表格列宽比例必须与列数一致且均为正数")
        self._column_width_ratios = ratios
        self.setProperty("columnWidthRatios", ratios)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._apply_column_widths()

    def _apply_column_widths(self) -> None:
        available = self.viewport().width()
        if available <= 0:
            return
        total = sum(self._column_width_ratios)
        widths = [available * ratio // total for ratio in self._column_width_ratios]
        widths[-1] += available - sum(widths)
        for index, width in enumerate(widths):
            self.setColumnWidth(index, max(1, width))


class StationDetailWidget(QWidget):
    """展示并操作一个站的九类业务，不拥有网络或数据库生命周期。"""

    operation_completed = pyqtSignal(object)

    def __init__(
        self,
        controller: TccController,
        *,
        include_train_page: bool = True,
        shared_request_service: SharedStateRequestService | None = None,
        network_fault_handler: Callable[[str, bool], OperationResult] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.include_train_page = include_train_page
        self.shared_request_service = shared_request_service
        self._network_fault_handler = network_fault_handler
        self._external_operation_locked = False
        self._external_lock_reason = ""
        self._last_direction: RunningDirection | None = None
        self.train_demo = TrainDemoService(controller)
        self.train_timer = QTimer(self)
        self.train_timer.setInterval(500)
        self.train_timer.timeout.connect(self._train_tick)
        self.setObjectName("stationDetailRoot")
        self._build_ui()
        if self.shared_request_service is not None:
            self.shared_request_service.requests_changed.connect(
                self._refresh_shared_requests
            )
        controller.add_snapshot_listener(self.refresh)
        self.refresh(controller.snapshot)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        header_bar = QWidget()
        header_bar.setObjectName("consoleHeader")
        header = QHBoxLayout(header_bar)
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("高铁列控课程设计 · TCC 单站仿真")
        title.setObjectName("applicationTitle")
        self.station_label = QLabel()
        self.station_label.setObjectName("stationIdentity")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.station_label)
        root.addWidget(header_bar)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_overview_page()
        self._build_track_page()
        self._build_signal_page()
        self._build_telegram_page()
        self._build_tsr_page()
        if self.shared_request_service is not None:
            # 申请处理放在临时限速右侧、日志告警左侧，形成连续的运行管理区。
            self._build_shared_request_page()
        if self.include_train_page:
            self._build_direction_page()
        if self.include_train_page:
            self._build_train_page()
        if self.include_train_page:
            self._build_network_page()
        self._build_log_page()
        self.operation_result = QLabel("就绪")
        self.operation_result.setObjectName("operationResult")
        root.addWidget(self.operation_result)
        self._configure_tables()

    def _configure_tables(self) -> None:
        """紧凑显示标识列，并让说明列占用剩余宽度且保留滚动能力。"""
        for table in self.findChildren(QTableWidget):
            header = table.horizontalHeader()
            if table.property("columnWidthRatios"):
                # 比例表由自身 resizeEvent 管理，不能再被通用的 Stretch 策略覆盖。
                header.setSectionResizeMode(QHeaderView.Fixed)
                continue
            header.setSectionResizeMode(QHeaderView.ResizeToContents)
            if table.columnCount() > 0:
                header.setSectionResizeMode(
                    table.columnCount() - 1, QHeaderView.Stretch
                )
            table.verticalHeader().setDefaultSectionSize(24)

    def _new_page(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.tabs.addTab(page, title)
        return page, layout

    def _build_overview_page(self) -> None:
        _, layout = self._new_page("总览拓扑")
        self.topology = TopologyWidget(self.controller.config.topology)
        self.topology.setMinimumHeight(230)
        self.topology.setMaximumHeight(300)
        layout.addWidget(self.topology)
        self.overview_summary = QLabel()
        layout.addWidget(self.overview_summary)
        route_group = QGroupBox("进路操作")
        route_controls = QHBoxLayout(route_group)
        self.route_selector = QComboBox()
        station_prefix = f"{self.controller.config.station.station_id}_"
        self.route_selector.addItems(
            [
                route.id
                for route in self.controller.config.topology.routes
                if route.id.startswith(station_prefix)
            ]
        )
        configure_combo_box(self.route_selector, "route")
        self.establish_route_button = QPushButton("建立进路")
        self.cancel_route_button = QPushButton("取消进路")
        self.establish_route_button.setObjectName("establishRouteButton")
        self.cancel_route_button.setObjectName("cancelRouteButton")
        self.establish_route_button.clicked.connect(self._establish_route)
        self.cancel_route_button.clicked.connect(self._cancel_route)
        route_controls.addWidget(self.route_selector)
        route_controls.addWidget(self.establish_route_button)
        route_controls.addWidget(self.cancel_route_button)
        route_controls.addStretch(1)
        layout.addWidget(route_group)

        if not self.include_train_page:
            operation_row = QHBoxLayout()
            operation_row.setSpacing(10)
            self._build_direction_section(operation_row)
            self._build_network_section(operation_row)
            layout.addLayout(operation_row)

    def _build_shared_request_page(self) -> None:
        """A/B 控制页的独立公共区段申请处理页面。"""
        _, layout = self._new_page("申请处理")
        self._build_shared_request_panel(layout)
        layout.addStretch(1)

    def _build_shared_request_panel(self, layout: QVBoxLayout) -> None:
        """在 A/B 控制页展示本站待确认和已处理的公共区段申请。"""
        group = QGroupBox("公共区段申请确认（A/B 双站）")
        group.setObjectName("sharedStateRequestGroup")
        group_layout = QVBoxLayout(group)
        self.shared_pending_table = _RatioTableWidget(5, (3, 3, 1, 8, 4))
        self.shared_pending_table.setHorizontalHeaderLabels(
            ["申请编号", "时间", "申请站", "内容", "操作"]
        )
        self.shared_pending_table.setWordWrap(True)
        self.shared_history_table = _RatioTableWidget(4, (3, 1, 3, 7))
        self.shared_history_table.setHorizontalHeaderLabels(
            ["申请编号", "结果", "处理时间", "内容"]
        )
        self.shared_history_table.setWordWrap(True)
        self._shared_pending_signature: tuple[tuple[str, str, str, str], ...] | None = None
        self._shared_history_signature: tuple[tuple[str, str, str, str], ...] | None = None
        group_layout.addWidget(QLabel("待处理申请"))
        group_layout.addWidget(self.shared_pending_table)
        group_layout.addWidget(QLabel("已处理申请记录"))
        group_layout.addWidget(self.shared_history_table)
        layout.addWidget(group)
        self._refresh_shared_requests()

    def _build_track_page(self) -> None:
        _, layout = self._new_page("轨道编码")
        controls = QHBoxLayout()
        self.track_selector = QComboBox()
        self.track_selector.addItems(
            [item.id for item in self.controller.config.topology.sections]
        )
        configure_combo_box(self.track_selector, "section")
        self.track_state_selector = QComboBox()
        for state, text in (
            (TrackState.CLEAR, "空闲"),
            (TrackState.OCCUPIED, "占用"),
            (TrackState.FAULT_OCCUPIED, "故障占用"),
            (TrackState.SHUNT_BAD, "分路不良"),
        ):
            self.track_state_selector.addItem(text, state)
        configure_combo_box(self.track_state_selector, "state")
        self.apply_track_button = QPushButton("应用轨道状态")
        self.apply_track_button.clicked.connect(self._apply_track)
        controls.addWidget(self.track_selector)
        controls.addWidget(self.track_state_selector)
        controls.addWidget(self.apply_track_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.track_table = QTableWidget(0, 5)
        self.track_table.setHorizontalHeaderLabels(["区段", "名称", "状态", "码序", "原因"])
        layout.addWidget(self.track_table)

    def _build_signal_page(self) -> None:
        _, layout = self._new_page("信号")
        controls = QHBoxLayout()
        self.signal_selector = QComboBox()
        self.signal_selector.addItems(
            [item.id for item in self.controller.config.topology.signals]
        )
        configure_combo_box(self.signal_selector, "signal")
        self.red_lamp_failure = QCheckBox("模拟红灯灯丝故障")
        button = QPushButton("应用灯丝状态")
        button.clicked.connect(self._apply_signal_fault)
        controls.addWidget(self.signal_selector)
        controls.addWidget(self.red_lamp_failure)
        controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.signal_table = QTableWidget(0, 5)
        self.signal_table.setHorizontalHeaderLabels(["信号机", "灯色", "HJ", "UJ", "LJ/原因"])
        layout.addWidget(self.signal_table)

    def _build_telegram_page(self) -> None:
        _, layout = self._new_page("应答器/LEU")
        self.telegram_summary = QLabel()
        layout.addWidget(self.telegram_summary)
        self.logical_text = QTextEdit()
        self.logical_text.setReadOnly(True)
        self.bit_text = QTextEdit()
        self.bit_text.setReadOnly(True)
        self.envelope_text = QTextEdit()
        self.envelope_text.setReadOnly(True)
        for title, widget in (
            ("逻辑报文（字段级教学内容）", self.logical_text),
            ("教学位流视图（由 UTF-8 仿真封装展开，非现场 1023 位报文）", self.bit_text),
            ("仿真封装（simulation_envelope / HEX / CRC32）", self.envelope_text),
        ):
            group = QGroupBox(title)
            group_layout = QVBoxLayout(group)
            group_layout.addWidget(widget)
            layout.addWidget(group)

    def _build_tsr_page(self) -> None:
        _, layout = self._new_page("临时限速")
        form = QFormLayout()
        self.tsr_id = QComboBox()
        self.tsr_id.setEditable(True)
        self.tsr_id.addItem("TSR-DEMO")
        configure_combo_box(self.tsr_id, "tsr")
        self.tsr_start = QDoubleSpinBox()
        self.tsr_start.setRange(0, 4800)
        self.tsr_start.setValue(1000)
        self.tsr_end = QDoubleSpinBox()
        self.tsr_end.setRange(0, 4800)
        self.tsr_end.setValue(3000)
        self.tsr_speed = QDoubleSpinBox()
        self.tsr_speed.setRange(1, 500)
        self.tsr_speed.setValue(80)
        self.tsr_duration = QSpinBox()
        self.tsr_duration.setRange(1, 86400)
        self.tsr_duration.setValue(3600)
        form.addRow("命令号", self.tsr_id)
        form.addRow("起点 m", self.tsr_start)
        form.addRow("终点 m", self.tsr_end)
        form.addRow("限速 km/h", self.tsr_speed)
        form.addRow("有效时长 s", self.tsr_duration)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for text, slot in (
            ("预存", self._prestore_tsr),
            ("执行", self._activate_tsr),
            ("撤销", self._cancel_tsr),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.tsr_table = QTableWidget(0, 5)
        self.tsr_table.setHorizontalHeaderLabels(["命令号", "起点", "终点", "限速", "状态"])
        layout.addWidget(self.tsr_table)

    def _build_direction_section(self, parent_layout: QLayout) -> None:
        group = QGroupBox("区间改方")
        group.setObjectName("directionSection")
        self.direction_section = group
        layout = QVBoxLayout(group)
        self.direction_status = QLabel()
        self.direction_target = QComboBox()
        self.direction_target.addItem("A站 → B站", RunningDirection.A_TO_B)
        self.direction_target.addItem("B站 → A站", RunningDirection.B_TO_A)
        configure_combo_box(self.direction_target, "direction")
        self.direction_button = QPushButton("申请区间改方")
        self.direction_button.setObjectName("requestDirectionButton")
        self.direction_button.clicked.connect(self._request_direction)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.direction_status)
        layout.addWidget(self.direction_target)
        layout.addWidget(self.direction_button)
        parent_layout.addWidget(group)

    def _build_direction_page(self) -> None:
        _, layout = self._new_page("区间改方")
        self._build_direction_section(layout)

    def _build_network_section(self, parent_layout: QLayout) -> None:
        group = QGroupBox("网络")
        group.setObjectName("networkSection")
        self.network_section = group
        layout = QVBoxLayout(group)
        self.network_status = QLabel()
        self.network_metrics = QLabel()
        self.network_metrics.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        network_controls = QHBoxLayout()
        suffix = self.controller.config.station.station_id
        self.inject_network_button = QPushButton("模拟网络中断")
        self.restore_network_button = QPushButton("恢复网络")
        self.inject_network_button.setObjectName(f"inject{suffix}NetworkFaultButton")
        self.restore_network_button.setObjectName(f"restore{suffix}NetworkButton")
        self.inject_network_button.clicked.connect(lambda: self._set_network_fault(True))
        self.restore_network_button.clicked.connect(lambda: self._set_network_fault(False))
        network_controls.addWidget(self.inject_network_button)
        network_controls.addWidget(self.restore_network_button)
        network_controls.addStretch(1)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.network_status)
        layout.addWidget(self.network_metrics)
        layout.addLayout(network_controls)
        parent_layout.addWidget(group)

    def _build_network_page(self) -> None:
        _, layout = self._new_page("网络")
        self._build_network_section(layout)

    def _build_train_page(self) -> None:
        _, layout = self._new_page("列车演示")
        controls = QHBoxLayout()
        self.create_train_button = QPushButton("创建列车")
        self.dispatch_train_button = QPushButton("发送选中列车")
        self.start_train_button = QPushButton("开始运行")
        self.pause_train_button = QPushButton("暂停")
        self.reset_train_button = QPushButton("复位列车")
        self.create_train_button.clicked.connect(self._create_train)
        self.dispatch_train_button.clicked.connect(self._dispatch_train)
        self.start_train_button.clicked.connect(self._start_trains)
        self.pause_train_button.clicked.connect(self._pause_trains)
        self.reset_train_button.clicked.connect(self._reset_trains)
        for button in (
            self.create_train_button,
            self.dispatch_train_button,
            self.start_train_button,
            self.pause_train_button,
            self.reset_train_button,
        ):
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.train_table = QTableWidget(0, 6)
        self.train_table.setHorizontalHeaderLabels(
            ["列车", "方向", "区段", "位置(m)", "速度(km/h)", "状态"]
        )
        layout.addWidget(self.train_table)
        note = QLabel(
            "教学演示：列车占用仅通过 TRAIN 来源写入控制器，不替代车载 ATP/测速定位。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

    def _build_log_page(self) -> None:
        _, layout = self._new_page("日志告警")
        self.operation_table = QTableWidget(0, 5)
        self.operation_table.setHorizontalHeaderLabels(
            ["时间(ms)", "操作", "结果", "原因", "状态版本"]
        )
        operation_group = QGroupBox("操作日志（最近 200 条）")
        operation_layout = QVBoxLayout(operation_group)
        operation_layout.addWidget(self.operation_table)
        layout.addWidget(operation_group)
        self.alarm_table = QTableWidget(0, 4)
        self.alarm_table.setHorizontalHeaderLabels(["级别", "代码", "来源", "说明"])
        alarm_group = QGroupBox("当前活动告警")
        alarm_layout = QVBoxLayout(alarm_group)
        alarm_layout.addWidget(self.alarm_table)
        layout.addWidget(alarm_group)

    def refresh(self, snapshot: TccSnapshot) -> None:
        role = self.controller.config.station.network.role.value
        self.station_label.setText(f"{snapshot.station_name} · {role}")
        self.topology.set_snapshot(snapshot)
        self.overview_summary.setText(
            f"状态版本：{snapshot.state_version}　方向：{snapshot.running_direction}　"
            f"活动进路：{', '.join(snapshot.active_route_ids) or '无'}"
        )
        self._fill_tracks(snapshot)
        self._fill_signals(snapshot)
        self._fill_telegram(snapshot)
        self._fill_tsr(snapshot)
        self._fill_operation_logs(snapshot)
        self._fill_alarms(snapshot)
        if self.include_train_page:
            self._fill_trains()
        self.direction_status.setText(
            f"当前方向：{snapshot.running_direction}；"
            f"作业状态：{'安全锁闭' if snapshot.direction_operation_locked else '允许'}"
        )
        self._refresh_direction_status(snapshot)
        self.network_status.setText(f"站间通信：{snapshot.connection_state.value}")
        set_semantic_state(
            self.network_status,
            "connectionState",
            snapshot.connection_state.value,
        )
        self.network_metrics.setText(
            f"协议报文：发送 {snapshot.network_sent:>8} / 接收 {snapshot.network_received:<8}\n"
            f"业务报文：发送 {snapshot.business_sent:>8} / 接收 {snapshot.business_received:<8}\n"
            f"心跳报文：发送 {snapshot.heartbeat_sent:>8} / 接收 {snapshot.heartbeat_received:<8}"
        )
        self._refresh_shared_requests()
        self._update_action_enabled(snapshot)

    def set_external_operation_lock(self, locked: bool, reason: str = "") -> None:
        """应用双站聚合安全门；不改变控制器内部业务状态。"""
        changed = locked != self._external_operation_locked
        self._external_operation_locked = locked
        self._external_lock_reason = reason
        self._update_action_enabled(self.controller.snapshot)
        if changed and locked:
            self.operation_result.setText(
                f"全局安全锁闭：{reason or '双站条件未满足'}"
            )

    def _update_action_enabled(self, snapshot: TccSnapshot) -> None:
        locally_available = not snapshot.direction_operation_locked
        globally_available = not self._external_operation_locked
        self.establish_route_button.setEnabled(
            locally_available and globally_available
        )
        current_direction = RunningDirection(snapshot.running_direction)
        requester_id = direction_requester_station(current_direction)
        self.direction_button.setEnabled(
            snapshot.station_id == requester_id
            and locally_available
            and globally_available
            and snapshot.connection_state.value == "HEALTHY"
        )
        # 安全复核按钮故意不受全局业务锁闭门禁影响；它只能重跑守卫，
        # 守卫不满足时会拒绝，不能将锁闭状态直接改成允许。
        if self.include_train_page:
            # 外部安全锁闭时列车按钮必须一致禁用（含创建/暂停/复位），
            # 与联合列车页的锁定行为保持一致，避免界面状态矛盾。
            self.create_train_button.setEnabled(globally_available)
            self.dispatch_train_button.setEnabled(globally_available)
            self.start_train_button.setEnabled(globally_available)
            self.pause_train_button.setEnabled(globally_available)
            self.reset_train_button.setEnabled(globally_available)

    def _fill_operation_logs(self, snapshot: TccSnapshot) -> None:
        self.operation_table.setRowCount(len(snapshot.operation_logs))
        for row, item in enumerate(snapshot.operation_logs):
            values = (
                item.event_time_ms,
                item.operation,
                "成功" if item.success else "拒绝",
                item.reason,
                item.state_version,
            )
            for column, value in enumerate(values):
                self.operation_table.setItem(
                    row, column, QTableWidgetItem(str(value))
                )

    def _fill_tracks(self, snapshot: TccSnapshot) -> None:
        rows = self.controller.config.topology.sections
        self.track_table.setRowCount(len(rows))
        for row, section in enumerate(rows):
            values = (
                section.id,
                section.name,
                snapshot.tracks[section.id].value,
                snapshot.codes[section.id].code.value,
                snapshot.codes[section.id].reason,
            )
            for column, value in enumerate(values):
                self.track_table.setItem(
                    row, column, QTableWidgetItem(str(value))
                )

    def _fill_signals(self, snapshot: TccSnapshot) -> None:
        rows = list(snapshot.signals.values())
        self.signal_table.setRowCount(len(rows))
        for row, signal in enumerate(rows):
            values = (
                signal.signal_id,
                signal.aspect.value,
                relay_text(signal.relay_hj),
                relay_text(signal.relay_uj),
                f"{relay_text(signal.relay_lj)} / {signal.reason}",
            )
            for column, value in enumerate(values):
                self.signal_table.setItem(
                    row, column, QTableWidgetItem(str(value))
                )

    def _fill_telegram(self, snapshot: TccSnapshot) -> None:
        item = snapshot.telegram
        self.telegram_summary.setText(
            f"{item.port_id} · {item.template_id} · {item.mode.value} · {item.reason}"
        )
        self.logical_text.setPlainText(
            json.dumps(item.logical_payload, ensure_ascii=False, indent=2)
        )
        self.bit_text.setPlainText(item.teaching_bit_view)
        self.envelope_text.setPlainText(
            f"format={item.simulation_format}\nHEX={item.simulation_hex}\nCRC32={item.crc32}"
        )

    def _fill_tsr(self, snapshot: TccSnapshot) -> None:
        self.tsr_table.setRowCount(len(snapshot.temporary_speeds))
        for row, item in enumerate(snapshot.temporary_speeds):
            values = (
                item.tsr_id,
                item.start_m,
                item.end_m,
                item.speed_kmh,
                item.state.value,
            )
            for column, value in enumerate(values):
                self.tsr_table.setItem(
                    row, column, QTableWidgetItem(str(value))
                )

    def _fill_alarms(self, snapshot: TccSnapshot) -> None:
        self.alarm_table.setRowCount(len(snapshot.alarms))
        for row, item in enumerate(snapshot.alarms):
            values = (item.level.value, item.code, item.source, item.message)
            for column, value in enumerate(values):
                self.alarm_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _fill_trains(self) -> None:
        trains = list(self.train_demo.trains.values())
        self.train_table.setRowCount(len(trains))
        for row, train in enumerate(trains):
            values = (
                train.train_id,
                train.direction.value,
                train.section_id or "—",
                f"{train.position_m:.1f}",
                f"{train.speed_kmh:.1f}",
                train.status.value,
            )
            for column, value in enumerate(values):
                self.train_table.setItem(
                    row, column, QTableWidgetItem(str(value))
                )

    def _show_result(self, result: OperationResult) -> None:
        status = "成功" if result.success else "拒绝"
        self.operation_result.setText(f"{status}：{result.reason}")
        self.operation_completed.emit(result)

    def _apply_track(self) -> None:
        section_id = self.track_selector.currentText()
        state = self.track_state_selector.currentData()
        if section_id.startswith("Q") and self.shared_request_service is not None:
            self._show_result(
                self.shared_request_service.submit(
                    section_id, state, self.controller.config.station.station_id
                )
            )
            return
        self._show_result(self.controller.set_track_state(section_id, TrackInputSource.OPERATOR, state))

    def _establish_route(self) -> None:
        self._show_result(
            self.controller.establish_route(self.route_selector.currentText())
        )

    def _cancel_route(self) -> None:
        self._show_result(
            self.controller.cancel_route(self.route_selector.currentText())
        )

    def _apply_signal_fault(self) -> None:
        self._show_result(
            self.controller.set_red_lamp_failure(
                self.signal_selector.currentText(),
                self.red_lamp_failure.isChecked(),
            )
        )

    def _prestore_tsr(self) -> None:
        now = self.controller.now_ms()
        self._show_result(
            self.controller.prestore_temporary_speed(
                self.tsr_id.currentText(),
                self.tsr_start.value(),
                self.tsr_end.value(),
                self.tsr_speed.value(),
                now,
                now + self.tsr_duration.value() * 1000,
            )
        )

    def _activate_tsr(self) -> None:
        self._show_result(
            self.controller.activate_temporary_speed(self.tsr_id.currentText())
        )

    def _cancel_tsr(self) -> None:
        self._show_result(
            self.controller.cancel_temporary_speed(self.tsr_id.currentText())
        )

    def _request_direction(self) -> None:
        target = self.direction_target.currentData()
        if self.shared_request_service is not None:
            requester_id = direction_requester_station(
                RunningDirection(self.controller.snapshot.running_direction)
            )
            if requester_id != self.controller.config.station.station_id:
                self._show_result(OperationResult(False, "本站不是当前运行方向的请求方"))
                return
            self._show_result(
                self.shared_request_service.submit_direction(
                    target, requester_id
                )
            )
            return
        self._show_result(
            self.controller.request_direction_change(target)
        )

    def _refresh_direction_status(self, snapshot: TccSnapshot) -> None:
        current_direction = RunningDirection(snapshot.running_direction)
        if self._last_direction is not current_direction:
            opposite = (
                RunningDirection.B_TO_A
                if current_direction is RunningDirection.A_TO_B
                else RunningDirection.A_TO_B
            )
            self.direction_target.setCurrentIndex(
                self.direction_target.findData(opposite)
            )
            self._last_direction = current_direction

    def _set_network_fault(self, enabled: bool) -> None:
        station_id = self.controller.config.station.station_id
        if self._network_fault_handler is None:
            self._show_result(OperationResult(False, "运行时不支持网络故障注入"))
            return
        self._show_result(self._network_fault_handler(station_id, enabled))

    def _approve_shared_request(self, request_id: str) -> None:
        if self.shared_request_service is None:
            return
        result = self.shared_request_service.approve(
            request_id, self.controller.config.station.station_id
        )
        self._show_result(result)

    def _reject_shared_request(self, request_id: str) -> None:
        if self.shared_request_service is None:
            return
        result = self.shared_request_service.reject(
            request_id,
            self.controller.config.station.station_id,
            "本站安全条件未满足，拒绝公共区段状态申请",
        )
        self._show_result(result)

    def _refresh_shared_requests(self) -> None:
        if not hasattr(self, "shared_pending_table"):
            return
        if self.shared_request_service is None:
            self.shared_pending_table.setRowCount(0)
            self.shared_history_table.setRowCount(0)
            self._shared_pending_signature = ()
            self._shared_history_signature = ()
            return
        station_id = self.controller.config.station.station_id
        pending = self.shared_request_service.pending_requests_for(station_id)
        pending_signature = tuple(
            (
                request.request_id,
                request.created_at,
                request.requester_station_id,
                request.content,
            )
            for request in pending
        )
        if pending_signature != self._shared_pending_signature:
            self._shared_pending_signature = pending_signature
            self.shared_pending_table.setRowCount(len(pending))
            for row, request in enumerate(pending):
                values = (
                    request.request_id,
                    request.created_at,
                    f"{request.requester_station_id}站",
                    request.content,
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
                        item.setData(Qt.UserRole, request.request_id)
                    self.shared_pending_table.setItem(row, column, item)
                actions = QWidget()
                action_layout = QHBoxLayout(actions)
                action_layout.setContentsMargins(2, 0, 2, 0)
                approve_button = QPushButton("同意")
                reject_button = QPushButton("拒绝")
                approve_button.setObjectName(
                    f"approveSharedRequestButton{station_id}_{request.request_id}"
                )
                reject_button.setObjectName(
                    f"rejectSharedRequestButton{station_id}_{request.request_id}"
                )
                approve_button.clicked.connect(
                    lambda _checked=False, rid=request.request_id: self._approve_shared_request(
                        rid
                    )
                )
                reject_button.clicked.connect(
                    lambda _checked=False, rid=request.request_id: self._reject_shared_request(
                        rid
                    )
                )
                action_layout.addWidget(approve_button)
                action_layout.addWidget(reject_button)
                self.shared_pending_table.setCellWidget(row, 4, actions)
                self.shared_pending_table.setRowHeight(row, 36)
        history = self.shared_request_service.history()
        history_signature = tuple(
            (
                request.request_id,
                request.status.value,
                request.processed_at or "—",
                request.content,
            )
            for request in history
        )
        if history_signature != self._shared_history_signature:
            self._shared_history_signature = history_signature
            self.shared_history_table.setRowCount(len(history))
            for row, request in enumerate(history):
                values = (
                    request.request_id,
                    request.status.value,
                    request.processed_at or "—",
                    request.content,
                )
                for column, value in enumerate(values):
                    self.shared_history_table.setItem(
                        row, column, QTableWidgetItem(str(value))
                    )

    def _create_train(self) -> None:
        train = self.train_demo.create_train()
        self.operation_result.setText(f"成功：已创建演示列车 {train.train_id}")
        self._fill_trains()

    def _dispatch_train(self) -> None:
        row = self.train_table.currentRow()
        if row < 0 and self.train_table.rowCount() > 0:
            row = 0
        if row < 0:
            self.operation_result.setText("拒绝：请先创建列车")
            return
        train_id = self.train_table.item(row, 0).text()
        self._show_result(self.train_demo.dispatch(train_id))
        self._fill_trains()

    def _train_tick(self) -> None:
        self.train_demo.tick(self.train_timer.interval() / 1000.0)
        self._fill_trains()

    def _start_trains(self) -> None:
        self.train_timer.start()

    def _pause_trains(self) -> None:
        self.train_timer.stop()

    def _reset_trains(self) -> None:
        self.train_timer.stop()
        self.train_demo.reset()
        self.operation_result.setText("成功：列车演示已复位")
        self._fill_trains()

    def stop_activity(self) -> None:
        """停止组件自己的动画；网络和仓储由顶层生命周期所有者关闭。"""
        self.train_timer.stop()
