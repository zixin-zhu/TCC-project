"""双站同屏模式的真实业务操作页。

页面只负责收集参数、选择目标控制器和展示结果；所有业务状态变化均调用
``TccController`` 公共命令，禁止从界面直接修改运行态字段。
"""

from __future__ import annotations

import json
from collections.abc import Callable

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
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
from app.services.alarm_service import AlarmLevel
from app.services.dual_train_coordinator import DualTrainCoordinator, DualTrainState
from app.services.tcc_controller import TccController
from app.ui.dual_snapshot import DualStationSnapshot


DUAL_OPERATION_BUTTON_OBJECTS = frozenset(
    {
        "establishRouteButton",
        "cancelRouteButton",
        "applyTrackStateButton",
        "applySignalFailureButton",
        "prestoreTsrButton",
        "activateTsrButton",
        "cancelTsrButton",
        "requestDirectionButton",
        "requestDirectionDisconnectButton",
        "injectBNetworkFaultButton",
        "restoreBNetworkButton",
        "createTrainButton",
        "dispatchTrainButton",
        "startTrainButton",
        "pauseTrainButton",
        "resetTrainButton",
    }
)


def _readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    # 安全状态表不能依赖用户悬停查看省略文本：关键列按内容展开，说明列占满余量。
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    header.setSectionResizeMode(len(headers) - 1, QHeaderView.Stretch)
    return table


class _OperationPage(QWidget):
    """统一操作结果格式，便于课堂演示和验收追踪。"""

    operation_completed = pyqtSignal(str, object)

    def __init__(self, station_a: TccController, station_b: TccController) -> None:
        super().__init__()
        self.station_a = station_a
        self.station_b = station_b
        self.result_label = QLabel("操作结果：尚未执行")
        self.result_label.setObjectName("operationResult")

    def _show_result(
        self,
        target: str,
        result: OperationResult,
        *,
        version: int | None = None,
    ) -> OperationResult:
        if version is None:
            snapshots = []
            dual_target = target in {"联合列车", "A/B双站"}
            if "A" in target or "共享" in target or dual_target:
                snapshots.append(self.station_a.snapshot.state_version)
            if "B" in target or "共享" in target or dual_target:
                snapshots.append(self.station_b.snapshot.state_version)
            version = max(snapshots, default=0)
        outcome = "成功" if result.success else "拒绝"
        self.result_label.setText(
            f"操作结果：目标={target}；{outcome}；原因={result.reason}；版本={version}"
        )
        self.operation_completed.emit(target, result)
        return result


class TrackOperationsPage(_OperationPage):
    """按 A/B/共享物理目标执行人工轨道状态输入。"""

    def __init__(self, station_a: TccController, station_b: TccController) -> None:
        super().__init__(station_a, station_b)
        layout = QVBoxLayout(self)
        heading = QLabel("双站轨道电路状态与人工输入")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        controls = QHBoxLayout()
        self.target_selector = QComboBox()
        self.target_selector.setObjectName("trackTargetSelector")
        self.target_selector.addItems(["A站", "B站", "共享区间"])
        self.section_selector = QComboBox()
        self.section_selector.setObjectName("trackSectionSelector")
        self.state_selector = QComboBox()
        for state, text in (
            (TrackState.CLEAR, "空闲"),
            (TrackState.OCCUPIED, "占用"),
            (TrackState.FAULT_OCCUPIED, "故障占用"),
            (TrackState.SHUNT_BAD, "分路不良"),
        ):
            self.state_selector.addItem(text, state)
        self.apply_button = QPushButton("应用轨道状态")
        self.apply_button.setObjectName("applyTrackStateButton")
        self.target_selector.currentTextChanged.connect(self._reload_sections)
        self.apply_button.clicked.connect(self._apply)
        for widget in (
            self.target_selector,
            self.section_selector,
            self.state_selector,
            self.apply_button,
        ):
            controls.addWidget(widget)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.table = _readonly_table(
            ["区段", "归属", "A站状态/码序", "B站状态/码序", "一致性"]
        )
        layout.addWidget(self.table)
        layout.addWidget(self.result_label)
        self._reload_sections()

    def _reload_sections(self) -> None:
        target = self.target_selector.currentText()
        all_ids = [item.id for item in self.station_a.config.topology.sections]
        if target == "A站":
            values = [item for item in all_ids if item.startswith("A_")]
        elif target == "B站":
            values = [item for item in all_ids if item.startswith("B_")]
        else:
            values = [item for item in all_ids if item.startswith("Q")]
        self.section_selector.clear()
        self.section_selector.addItems(values)

    def _apply(self) -> None:
        target = self.target_selector.currentText()
        section_id = self.section_selector.currentText()
        state = self.state_selector.currentData()
        if target == "A站":
            result = self.station_a.set_track_state(
                section_id, TrackInputSource.OPERATOR, state
            )
            self._show_result(target, result)
            return
        if target == "B站":
            result = self.station_b.set_track_state(
                section_id, TrackInputSource.OPERATOR, state
            )
            self._show_result(target, result)
            return

        # 人工共享输入仍分别经过两个控制器；部分成功时保持保守状态并报警。
        result_a = self.station_a.set_track_state(
            section_id, TrackInputSource.OPERATOR, state
        )
        if not result_a.success:
            self._show_result("共享区间", OperationResult(False, f"A站：{result_a.reason}"))
            return
        result_b = self.station_b.set_track_state(
            section_id, TrackInputSource.OPERATOR, state
        )
        if not result_b.success:
            compensation_text = ""
            if state is TrackState.CLEAR:
                compensation = self.station_a.set_track_state(
                    section_id,
                    TrackInputSource.OPERATOR,
                    TrackState.OCCUPIED,
                )
                compensation_text = (
                    "；A站已重新置为占用"
                    if compensation.success
                    else f"；A站重新占用失败：{compensation.reason}"
                )
            reason = (
                f"共享人工输入部分失败：{result_b.reason}{compensation_text}"
            )
            for controller in (self.station_a, self.station_b):
                controller.raise_external_alarm(
                    "SHARED_INPUT_PARTIAL_FAILURE",
                    AlarmLevel.CRITICAL,
                    reason,
                    "DUAL_TRACK_PAGE",
                )
            self._show_result("共享区间", OperationResult(False, reason))
            return
        self._show_result("共享区间", OperationResult(True, "双站轨道状态已更新"))

    def set_snapshot(self, model: DualStationSnapshot) -> None:
        self.table.setRowCount(len(model.sections))
        for row, item in enumerate(model.sections):
            code_a = model.station_a.codes[item.section_id].code.value
            code_b = model.station_b.codes[item.section_id].code.value
            owner = (
                "A站" if item.section_id.startswith("A_")
                else "B站" if item.section_id.startswith("B_")
                else "共享"
            )
            values = (
                item.section_id,
                owner,
                f"{item.station_a_state.value} / {code_a}",
                f"{item.station_b_state.value} / {code_b}",
                "一致" if item.consistent else item.reason,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))


class SignalOperationsPage(_OperationPage):
    """选择目标站后执行灯丝故障设置，并显示继电器状态。"""

    def __init__(self, station_a: TccController, station_b: TccController) -> None:
        super().__init__(station_a, station_b)
        layout = QVBoxLayout(self)
        heading = QLabel("双站信号机控制与继电器状态")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        controls = QHBoxLayout()
        self.station_selector = QComboBox()
        self.station_selector.addItems(["A站", "B站"])
        self.signal_selector = QComboBox()
        self.failure_checkbox = QCheckBox("模拟红灯灯丝故障")
        self.apply_button = QPushButton("应用灯丝状态")
        self.apply_button.setObjectName("applySignalFailureButton")
        self.station_selector.currentTextChanged.connect(self._reload_signals)
        self.apply_button.clicked.connect(self._apply)
        for widget in (
            self.station_selector,
            self.signal_selector,
            self.failure_checkbox,
            self.apply_button,
        ):
            controls.addWidget(widget)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.table = _readonly_table(
            ["站点", "信号机", "灯色", "HJ", "UJ", "LJ/原因"]
        )
        layout.addWidget(self.table)
        layout.addWidget(self.result_label)
        self._reload_signals()

    def _controller(self) -> TccController:
        return self.station_a if self.station_selector.currentText() == "A站" else self.station_b

    def _reload_signals(self) -> None:
        self.signal_selector.clear()
        self.signal_selector.addItems(
            [item.id for item in self._controller().config.topology.signals]
        )

    def _apply(self) -> None:
        target = self.station_selector.currentText()
        result = self._controller().set_red_lamp_failure(
            self.signal_selector.currentText(), self.failure_checkbox.isChecked()
        )
        self._show_result(target, result)

    def set_snapshot(self, model: DualStationSnapshot) -> None:
        rows = [
            (station_id, signal)
            for station_id, snapshot in (("A", model.station_a), ("B", model.station_b))
            for signal in snapshot.signals.values()
        ]
        self.table.setRowCount(len(rows))
        for row, (station_id, signal) in enumerate(rows):
            values = (
                f"{station_id}站",
                signal.signal_id,
                signal.aspect.value,
                str(signal.relay_hj),
                str(signal.relay_uj),
                f"{signal.relay_lj} / {signal.reason}",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))


class LeuComparisonPage(QWidget):
    """并列比较 A/B LEU 选择结果，详细编码放入子标签。"""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        heading = QLabel("A/B 应答器与 LEU 报文对照")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        self.summary_table = _readonly_table(
            ["站点", "LEU端口", "模板", "模式", "选择原因"]
        )
        layout.addWidget(self.summary_table)
        self.detail_tabs = QTabWidget()
        self.logical_text = QTextEdit()
        self.hex_text = QTextEdit()
        self.bit_text = QTextEdit()
        for title, widget in (
            ("逻辑字段", self.logical_text),
            ("HEX/CRC", self.hex_text),
            ("教学位流", self.bit_text),
        ):
            widget.setReadOnly(True)
            self.detail_tabs.addTab(widget, title)
        layout.addWidget(self.detail_tabs)
        note = QLabel("教学位流和 simulation_envelope 仅用于课程仿真，不冒充现场 1023 位报文。")
        note.setWordWrap(True)
        layout.addWidget(note)

    def set_snapshot(self, model: DualStationSnapshot) -> None:
        snapshots = (model.station_a, model.station_b)
        self.summary_table.setRowCount(2)
        for row, snapshot in enumerate(snapshots):
            item = snapshot.telegram
            values = (
                f"{snapshot.station_id}站",
                item.port_id,
                item.template_id,
                item.mode.value,
                item.reason,
            )
            for column, value in enumerate(values):
                self.summary_table.setItem(row, column, QTableWidgetItem(value))
        self.logical_text.setPlainText(
            "\n\n".join(
                f"{snapshot.station_id}站\n"
                + json.dumps(snapshot.telegram.logical_payload, ensure_ascii=False, indent=2)
                for snapshot in snapshots
            )
        )
        self.hex_text.setPlainText(
            "\n".join(
                f"{snapshot.station_id}站  {snapshot.telegram.simulation_format}  "
                f"CRC32={snapshot.telegram.crc32}\n{snapshot.telegram.simulation_hex}"
                for snapshot in snapshots
            )
        )
        self.bit_text.setPlainText(
            "\n\n".join(
                f"{snapshot.station_id}站\n{snapshot.telegram.teaching_bit_view}"
                for snapshot in snapshots
            )
        )


class TsrOperationsPage(_OperationPage):
    """明确目标站的临时限速预存、执行与撤销页。"""

    def __init__(self, station_a: TccController, station_b: TccController) -> None:
        super().__init__(station_a, station_b)
        layout = QVBoxLayout(self)
        heading = QLabel("双站临时限速命令")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        form = QFormLayout()
        self.station_selector = QComboBox()
        self.station_selector.addItems(["A站", "B站"])
        self.id_input = QComboBox()
        self.id_input.setEditable(True)
        self.id_input.addItem("TSR-DEMO")
        self.start_input = QDoubleSpinBox()
        self.start_input.setRange(0, 4800)
        self.start_input.setValue(1000)
        self.end_input = QDoubleSpinBox()
        self.end_input.setRange(0, 4800)
        self.end_input.setValue(3000)
        self.speed_input = QDoubleSpinBox()
        self.speed_input.setRange(1, 500)
        self.speed_input.setValue(80)
        self.duration_input = QSpinBox()
        self.duration_input.setRange(1, 86400)
        self.duration_input.setValue(3600)
        for label, widget in (
            ("目标站", self.station_selector),
            ("命令号", self.id_input),
            ("起点 m", self.start_input),
            ("终点 m", self.end_input),
            ("限速 km/h", self.speed_input),
            ("有效时长 s", self.duration_input),
        ):
            form.addRow(label, widget)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.prestore_button = QPushButton("预存限速")
        self.activate_button = QPushButton("执行限速")
        self.cancel_button = QPushButton("撤销限速")
        self.prestore_button.setObjectName("prestoreTsrButton")
        self.activate_button.setObjectName("activateTsrButton")
        self.cancel_button.setObjectName("cancelTsrButton")
        self.prestore_button.clicked.connect(self._prestore)
        self.activate_button.clicked.connect(self._activate)
        self.cancel_button.clicked.connect(self._cancel)
        for button in (self.prestore_button, self.activate_button, self.cancel_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.table = _readonly_table(
            ["站点", "命令号", "起点", "终点", "限速", "状态"]
        )
        layout.addWidget(self.table)
        layout.addWidget(self.result_label)

    def _controller(self) -> TccController:
        return self.station_a if self.station_selector.currentText() == "A站" else self.station_b

    def _prestore(self) -> None:
        controller = self._controller()
        now = controller.now_ms()
        result = controller.prestore_temporary_speed(
            self.id_input.currentText().strip(),
            self.start_input.value(),
            self.end_input.value(),
            self.speed_input.value(),
            now,
            now + self.duration_input.value() * 1000,
        )
        self._show_result(self.station_selector.currentText(), result)

    def _activate(self) -> None:
        result = self._controller().activate_temporary_speed(
            self.id_input.currentText().strip()
        )
        self._show_result(self.station_selector.currentText(), result)

    def _cancel(self) -> None:
        result = self._controller().cancel_temporary_speed(
            self.id_input.currentText().strip()
        )
        self._show_result(self.station_selector.currentText(), result)

    def set_snapshot(self, model: DualStationSnapshot) -> None:
        rows = [
            (snapshot.station_id, item)
            for snapshot in (model.station_a, model.station_b)
            for item in snapshot.temporary_speeds
        ]
        self.table.setRowCount(len(rows))
        for row, (station_id, item) in enumerate(rows):
            values = (
                f"{station_id}站",
                item.tsr_id,
                f"{item.start_m:g}",
                f"{item.end_m:g}",
                f"{item.speed_kmh:g}",
                item.state.value,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))


class DirectionOperationsPage(_OperationPage):
    """区间改方只由 A 站权威控制器发起。"""

    def __init__(
        self,
        station_a: TccController,
        station_b: TccController,
        fault_handler: Callable[[str, bool], OperationResult] | None = None,
    ) -> None:
        super().__init__(station_a, station_b)
        self._fault_handler = fault_handler
        layout = QVBoxLayout(self)
        heading = QLabel("权威方向、投影与改方事务")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.table = _readonly_table(
            ["站点角色", "当前方向", "通信状态", "状态版本", "事务阶段", "方向作业"]
        )
        layout.addWidget(self.table, 1)
        preconditions = QGroupBox("改方安全前置条件")
        precondition_layout = QVBoxLayout(preconditions)
        self.precondition_label = QLabel()
        self.precondition_label.setWordWrap(True)
        precondition_layout.addWidget(self.precondition_label)
        layout.addWidget(preconditions)
        controls = QHBoxLayout()
        self.direction_selector = QComboBox()
        self.direction_selector.addItem("A站 → B站", RunningDirection.A_TO_B)
        self.direction_selector.addItem("B站 → A站", RunningDirection.B_TO_A)
        self.request_button = QPushButton("由A站申请区间改方")
        self.request_button.setObjectName("requestDirectionButton")
        self.disconnect_drill_button = QPushButton("发起改方并立即中断B站")
        self.disconnect_drill_button.setObjectName("requestDirectionDisconnectButton")
        self.request_button.clicked.connect(self._request)
        self.disconnect_drill_button.clicked.connect(self._request_and_disconnect)
        self.disconnect_drill_button.setEnabled(fault_handler is not None)
        controls.addWidget(self.direction_selector)
        controls.addWidget(self.request_button)
        controls.addWidget(self.disconnect_drill_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        layout.addWidget(self.result_label)

    def _request(self) -> None:
        result = self.station_a.request_direction_change(
            self.direction_selector.currentData()
        )
        self._show_result("A站", result)

    def _request_and_disconnect(self) -> None:
        """确定性复现改方报文排队后 B 链路立即中断的教学场景。"""
        result = self.station_a.request_direction_change(
            self.direction_selector.currentData()
        )
        if not result.success:
            self._show_result("A/B双站", result)
            return
        if self._fault_handler is None:
            self._show_result(
                "A/B双站", OperationResult(False, "运行时不支持网络故障注入")
            )
            return
        fault_result = self._fault_handler("B", True)
        combined = OperationResult(
            fault_result.success,
            (
                f"改方请求已发出；{fault_result.reason}"
                if fault_result.success
                else f"改方请求已发出，但故障注入失败：{fault_result.reason}"
            ),
        )
        self._show_result("A/B双站", combined)

    def set_snapshot(self, model: DualStationSnapshot) -> None:
        phase = self.station_a.direction_phase.value
        self.status_label.setText(
            f"事务阶段：{phase}　权威方向：{model.station_a.running_direction}　"
            f"B站投影：{model.station_b.running_direction}　"
            f"方向一致：{'是' if model.direction_consistent else '否'}　"
            f"联合锁闭：{'是' if model.operation_locked else '否'}"
        )
        self.table.setRowCount(2)
        for row, (snapshot, role, controller) in enumerate(
            (
                (model.station_a, "A站（权威）", self.station_a),
                (model.station_b, "B站（投影）", self.station_b),
            )
        ):
            values = (
                role,
                snapshot.running_direction,
                snapshot.connection_state.value,
                str(snapshot.state_version),
                controller.direction_phase.value,
                "锁闭" if snapshot.direction_operation_locked else "允许",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        shared_clear = all(
            item.station_a_state is TrackState.CLEAR
            and item.station_b_state is TrackState.CLEAR
            for item in model.sections
            if item.section_id.startswith("Q")
        )
        no_routes = not (
            model.station_a.active_route_ids or model.station_b.active_route_ids
        )
        self.precondition_label.setText(
            "通信健康：{communication}　共享区段空闲：{shared}　"
            "两站无已建立进路：{routes}　方向一致：{direction}。\n"
            "仅 A 站能够发起改方；区段或进路条件不满足时请求会被明确拒绝，"
            "通信、方向一致性或事务异常时保持联合安全锁闭。".format(
                communication="是" if model.communication_healthy else "否",
                shared="是" if shared_clear else "否",
                routes="是" if no_routes else "否",
                direction="是" if model.direction_consistent else "否",
            )
        )
        self.request_button.setEnabled(not model.operation_locked)
        self.disconnect_drill_button.setEnabled(
            self._fault_handler is not None and not model.operation_locked
        )


class NetworkStatusPage(_OperationPage):
    """展示通信状态，并提供明确标注的可恢复教学故障注入。"""

    def __init__(
        self,
        station_a: TccController,
        station_b: TccController,
        fault_handler: Callable[[str, bool], OperationResult] | None,
    ) -> None:
        super().__init__(station_a, station_b)
        self._fault_handler = fault_handler
        layout = QVBoxLayout(self)
        heading = QLabel("站间通信状态与安全门")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        self.table = _readonly_table(
            ["站点", "角色", "连接状态", "发送", "接收", "状态版本", "作业锁闭"]
        )
        layout.addWidget(self.table)
        controls = QGroupBox("教学故障演练（真实断开并自动重连）")
        control_layout = QHBoxLayout(controls)
        self.inject_button = QPushButton("模拟B站网络中断")
        self.restore_button = QPushButton("恢复B站网络")
        self.inject_button.setObjectName("injectBNetworkFaultButton")
        self.restore_button.setObjectName("restoreBNetworkButton")
        self.inject_button.clicked.connect(lambda: self._set_fault(True))
        self.restore_button.clicked.connect(lambda: self._set_fault(False))
        enabled = fault_handler is not None
        self.inject_button.setEnabled(enabled)
        self.restore_button.setEnabled(enabled)
        control_layout.addWidget(self.inject_button)
        control_layout.addWidget(self.restore_button)
        control_layout.addStretch(1)
        layout.addWidget(controls)
        layout.addWidget(self.result_label)
        self.note = QLabel(
            "按钮仅用于课程故障演练：网络线程保持存活；恢复后自动重新握手、全量同步，"
            "不等同于现场安全通信设备。"
        )
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

    def _set_fault(self, enabled: bool) -> None:
        if self._fault_handler is None:
            self._show_result("B站", OperationResult(False, "运行时不支持网络故障注入"))
            return
        self._show_result("B站", self._fault_handler("B", enabled))

    def set_snapshot(self, model: DualStationSnapshot) -> None:
        self.table.setRowCount(2)
        for row, (snapshot, role) in enumerate(
            ((model.station_a, "SERVER"), (model.station_b, "CLIENT"))
        ):
            values = (
                f"{snapshot.station_id}站",
                role,
                snapshot.connection_state.value,
                str(snapshot.network_sent),
                str(snapshot.network_received),
                str(snapshot.state_version),
                "锁闭" if snapshot.direction_operation_locked else "允许",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))


class TrainOperationsPage(_OperationPage):
    """唯一联合列车协调器的控制和关键状态展示。"""

    def __init__(
        self,
        station_a: TccController,
        station_b: TccController,
        coordinator: DualTrainCoordinator,
    ) -> None:
        super().__init__(station_a, station_b)
        self.coordinator = coordinator
        layout = QVBoxLayout(self)
        heading = QLabel("A/B 跨站列车实时演示")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        controls = QHBoxLayout()
        self.create_button = QPushButton("添加待发列车")
        self.dispatch_button = QPushButton("发送选中列车")
        self.start_button = QPushButton("开始仿真")
        self.pause_button = QPushButton("暂停仿真")
        self.reset_button = QPushButton("复位列车")
        for name, button in (
            ("createTrainButton", self.create_button),
            ("dispatchTrainButton", self.dispatch_button),
            ("startTrainButton", self.start_button),
            ("pauseTrainButton", self.pause_button),
            ("resetTrainButton", self.reset_button),
        ):
            button.setObjectName(name)
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.train_table = _readonly_table(
            ["列车", "方向", "区段", "位置(m)", "当前速度", "目标速度", "前方距离", "最后应答器", "安全状态"]
        )
        layout.addWidget(self.train_table)
        layout.addWidget(self.result_label)
        note = QLabel("课程演示模型：轨道占用采用 TRAIN 独立来源，不替代车载 ATP、测速或定位设备。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.create_button.clicked.connect(self._create)
        self.dispatch_button.clicked.connect(self._dispatch)
        self.start_button.clicked.connect(self._start)
        self.pause_button.clicked.connect(self._pause)
        self.reset_button.clicked.connect(self._reset)
        coordinator.trains_changed.connect(self.set_trains)

    def _selected_train_id(self) -> str | None:
        row = self.train_table.currentRow()
        if row < 0 and self.train_table.rowCount() == 1:
            row = 0
        item = self.train_table.item(row, 0) if row >= 0 else None
        return item.text() if item is not None else None

    def _create(self) -> None:
        try:
            train = self.coordinator.create_train()
        except RuntimeError as exc:
            self._show_result("联合列车", OperationResult(False, str(exc)))
            return
        self._show_result("联合列车", OperationResult(True, f"已创建 {train.train_id}"))

    def _dispatch(self) -> None:
        train_id = self._selected_train_id()
        result = (
            self.coordinator.dispatch(train_id)
            if train_id is not None
            else OperationResult(False, "请选择待发列车")
        )
        self._show_result("联合列车", result)

    def _start(self) -> None:
        self._show_result("联合列车", self.coordinator.start())

    def _pause(self) -> None:
        self.coordinator.pause()
        self._show_result("联合列车", OperationResult(True, "仿真已暂停"))

    def _reset(self) -> None:
        self._show_result("联合列车", self.coordinator.reset())

    def set_trains(self, trains: tuple[DualTrainState, ...]) -> None:
        self.train_table.setRowCount(len(trains))
        for row, train in enumerate(trains):
            values = (
                train.train_id,
                train.direction.value,
                train.section_id or "--",
                f"{train.position_m:.1f}",
                f"{train.current_speed_kmh:.1f}",
                f"{train.target_speed_kmh:.1f}",
                f"{train.distance_ahead_m:.1f}",
                train.last_balise_id or "--",
                f"{train.status.value} / {train.safety_state}",
            )
            for column, value in enumerate(values):
                self.train_table.setItem(row, column, QTableWidgetItem(value))

    def set_snapshot(self, model: DualStationSnapshot) -> None:
        available = not model.operation_locked
        self.create_button.setEnabled(available)
        self.dispatch_button.setEnabled(available)
        self.start_button.setEnabled(available)
