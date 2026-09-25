"""可嵌入的 TCC 单站业务详情组件。"""

import json

from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
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
from app.services.tcc_controller import TccController, TccSnapshot
from app.services.train_demo_service import TrainDemoService
from app.ui.styles import set_semantic_state
from app.ui.topology_widget import TopologyWidget


class StationDetailWidget(QWidget):
    """展示并操作一个站的九类业务，不拥有网络或数据库生命周期。"""

    operation_completed = pyqtSignal(object)

    def __init__(
        self,
        controller: TccController,
        *,
        include_train_page: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.include_train_page = include_train_page
        self._external_operation_locked = False
        self._external_lock_reason = ""
        self.train_demo = TrainDemoService(controller)
        self.train_timer = QTimer(self)
        self.train_timer.setInterval(500)
        self.train_timer.timeout.connect(self._train_tick)
        self.setObjectName("stationDetailRoot")
        self._build_ui()
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
        self._build_direction_page()
        if self.include_train_page:
            self._build_train_page()
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
        self.establish_route_button = QPushButton("建立进路")
        self.cancel_route_button = QPushButton("取消进路")
        self.establish_route_button.clicked.connect(self._establish_route)
        self.cancel_route_button.clicked.connect(self._cancel_route)
        route_controls.addWidget(self.route_selector)
        route_controls.addWidget(self.establish_route_button)
        route_controls.addWidget(self.cancel_route_button)
        route_controls.addStretch(1)
        layout.addWidget(route_group)

    def _build_track_page(self) -> None:
        _, layout = self._new_page("轨道编码")
        controls = QHBoxLayout()
        self.track_selector = QComboBox()
        self.track_selector.addItems(
            [item.id for item in self.controller.config.topology.sections]
        )
        self.track_state_selector = QComboBox()
        for state, text in (
            (TrackState.CLEAR, "空闲"),
            (TrackState.OCCUPIED, "占用"),
            (TrackState.FAULT_OCCUPIED, "故障占用"),
            (TrackState.SHUNT_BAD, "分路不良"),
        ):
            self.track_state_selector.addItem(text, state)
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

    def _build_direction_page(self) -> None:
        _, layout = self._new_page("区间改方")
        self.direction_status = QLabel()
        self.direction_target = QComboBox()
        self.direction_target.addItem("A站 → B站", RunningDirection.A_TO_B)
        self.direction_target.addItem("B站 → A站", RunningDirection.B_TO_A)
        self.direction_button = QPushButton("申请区间改方")
        self.direction_button.clicked.connect(self._request_direction)
        layout.addWidget(self.direction_status)
        layout.addWidget(self.direction_target)
        layout.addWidget(self.direction_button)
        layout.addStretch(1)

    def _build_network_page(self) -> None:
        _, layout = self._new_page("网络")
        self.network_status = QLabel()
        self.network_metrics = QLabel()
        layout.addWidget(self.network_status)
        layout.addWidget(self.network_metrics)
        layout.addStretch(1)

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
        self.network_status.setText(f"站间通信：{snapshot.connection_state.value}")
        set_semantic_state(
            self.network_status,
            "connectionState",
            snapshot.connection_state.value,
        )
        self.network_metrics.setText(
            f"已接收业务消息：{snapshot.network_received}　"
            f"已发送业务消息：{snapshot.network_sent}"
        )
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
        self.direction_button.setEnabled(
            snapshot.station_id == "A"
            and locally_available
            and globally_available
            and snapshot.connection_state.value == "HEALTHY"
        )
        if self.include_train_page:
            self.dispatch_train_button.setEnabled(globally_available)
            self.start_train_button.setEnabled(globally_available)

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
                signal.relay_hj,
                signal.relay_uj,
                f"{signal.relay_lj} / {signal.reason}",
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
        self._show_result(
            self.controller.set_track_state(
                self.track_selector.currentText(),
                TrackInputSource.OPERATOR,
                self.track_state_selector.currentData(),
            )
        )

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
        self._show_result(
            self.controller.request_direction_change(
                self.direction_target.currentData()
            )
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
