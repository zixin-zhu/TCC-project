"""TCC 单站正式窗口；只发送命令并显示控制器快照。"""

import json
from typing import Protocol

from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
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
from app.ui.topology_widget import TopologyWidget


class NetworkThreadPort(Protocol):
    def stop(self, *, timeout_ms: int = 3000) -> bool: ...


class TccMainWindow(QMainWindow):
    """保留原软件蓝色标题和分组框风格，业务状态全部来自快照。"""

    def __init__(
        self,
        controller: TccController,
        *,
        network_thread: NetworkThreadPort | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.network_thread = network_thread
        self._closed = False
        self.setWindowTitle("高铁车站列控中心 TCC 功能仿真系统")
        self.resize(1280, 820)
        self.setStyleSheet(
            "QMainWindow{background:#eef3f8;}"
            "QGroupBox{font-weight:bold;border:1px solid #9eb7cf;border-radius:5px;"
            "margin-top:10px;padding-top:8px;background:white;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;color:#245b8f;}"
            "QPushButton{background:#3f8fce;color:white;border:0;border-radius:4px;"
            "padding:6px 14px;} QPushButton:disabled{background:#aab7c4;}"
            "QHeaderView::section{background:#dbe9f6;padding:5px;border:0;}"
        )
        self._build_ui()
        controller.add_snapshot_listener(self.refresh)
        self.refresh(controller.snapshot)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        header = QHBoxLayout()
        title = QLabel("高铁列控课程设计 · TCC 单站仿真")
        title.setStyleSheet("font-size:22px;font-weight:bold;color:#245b8f;padding:8px;")
        self.station_label = QLabel()
        self.station_label.setStyleSheet("font-size:15px;font-weight:bold;color:#245b8f;")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.station_label)
        root.addLayout(header)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_overview_page()
        self._build_track_page()
        self._build_signal_page()
        self._build_telegram_page()
        self._build_tsr_page()
        self._build_direction_page()
        self._build_network_page()
        self._build_log_page()
        self.operation_result = QLabel("就绪")
        self.operation_result.setStyleSheet("padding:6px;color:#37474f;")
        root.addWidget(self.operation_result)

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
        self.route_selector.addItems(
            [route.id for route in self.controller.config.topology.routes]
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
        self.direction_status.setText(
            f"当前方向：{snapshot.running_direction}；"
            f"作业状态：{'安全锁闭' if snapshot.direction_operation_locked else '允许'}"
        )
        self.network_status.setText(f"站间通信：{snapshot.connection_state.value}")
        self.network_metrics.setText(
            f"已接收业务消息：{snapshot.network_received}　"
            f"已发送业务消息：{snapshot.network_sent}"
        )
        self.establish_route_button.setEnabled(
            not snapshot.direction_operation_locked
        )
        self.direction_button.setEnabled(
            snapshot.station_id == "A"
            and not snapshot.direction_operation_locked
            and snapshot.connection_state.value == "HEALTHY"
        )

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

    def _show_result(self, result: OperationResult) -> None:
        status = "成功" if result.success else "拒绝"
        self.operation_result.setText(f"{status}：{result.reason}")

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

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closed:
            if self.network_thread is not None:
                if not self.network_thread.stop(timeout_ms=3000):
                    self.operation_result.setText(
                        "关闭被拒绝：网络线程未在超时内停止"
                    )
                    event.ignore()
                    return
            self.controller.close()
            self._closed = True
        event.accept()
