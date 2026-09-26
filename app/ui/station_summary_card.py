"""双站首页中的单站关键状态摘要卡。"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QGridLayout, QGroupBox, QLabel, QPushButton

from app.core.models import ProjectConfig
from app.services.tcc_controller import TccSnapshot
from app.ui.styles import relay_text, set_semantic_state


class StationSummaryCard(QGroupBox):
    """显示一站关键数据；卡片按钮只请求导航，不执行任何业务命令。"""

    navigate_requested = pyqtSignal(str)

    def __init__(self, config: ProjectConfig, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.config = config
        self.station_id = config.station.station_id
        self.setTitle(f"{config.station.station_name} · TCC-{self.station_id}")
        layout = QGridLayout(self)
        self.identity_label = QLabel(
            f"{config.station.station_name}　站点 {self.station_id}　"
            f"角色 {config.station.network.role.value}"
        )
        self.communication_label = QLabel("通信：等待快照")
        self.version_label = QLabel("状态版本：--")
        self.direction_label = QLabel("方向：--　作业状态：--")
        self.route_label = QLabel("活动进路：--")
        self.boundary_label = QLabel("边界区段/码序：--")
        self.signal_label = QLabel("主信号：--")
        self.leu_label = QLabel("LEU/报文：--")
        self.tsr_alarm_label = QLabel("临时限速：--　活动告警：--")
        self.metrics_label = QLabel("发送/接收：--/--")
        fields = (
            self.identity_label,
            self.communication_label,
            self.version_label,
            self.direction_label,
            self.route_label,
            self.boundary_label,
            self.signal_label,
            self.leu_label,
            self.tsr_alarm_label,
            self.metrics_label,
        )
        for index, label in enumerate(fields):
            label.setWordWrap(True)
            layout.addWidget(label, index // 2, index % 2)
        self.navigate_button = QPushButton(f"进入 {self.station_id}站控制")
        self.navigate_button.clicked.connect(
            lambda: self.navigate_requested.emit(self.station_id)
        )
        layout.addWidget(self.navigate_button, 5, 0, 1, 2)

    def set_snapshot(self, snapshot: TccSnapshot) -> None:
        if snapshot.station_id != self.station_id:
            raise ValueError(f"摘要卡 {self.station_id} 收到其他站快照")
        connection = snapshot.connection_state.value
        self.communication_label.setText(f"通信：{connection}")
        set_semantic_state(self.communication_label, "connectionState", connection)
        self.version_label.setText(f"状态版本：{snapshot.state_version}")
        self.direction_label.setText(
            f"方向：{snapshot.running_direction}　"
            "作业状态："
            f"{'安全锁闭' if snapshot.direction_operation_locked else '作业允许'}"
        )
        self.route_label.setText(
            f"活动进路：{', '.join(snapshot.active_route_ids) or '无'}"
        )
        boundary = next(
            (
                item
                for item in self.config.topology.boundaries
                if item.id.startswith(self.station_id)
            ),
            None,
        )
        if boundary is None:
            self.boundary_label.setText("边界区段/码序：未配置")
        else:
            state = snapshot.tracks[boundary.local_section].value
            code = snapshot.codes[boundary.local_section].code.value
            self.boundary_label.setText(
                f"边界区段/码序：{boundary.local_section} {state} / {code}"
            )
            set_semantic_state(
                self.boundary_label,
                "trackState",
                snapshot.tracks[boundary.local_section].value,
            )
        main_signal_id = f"S{self.station_id}"
        signal = snapshot.signals.get(main_signal_id)
        if signal is None:
            self.signal_label.setText("主信号：未配置")
        else:
            self.signal_label.setText(
                f"主信号 {signal.signal_id}：{signal.aspect.value}　"
                f"HJ/UJ/LJ={relay_text(signal.relay_hj)}/"
                f"{relay_text(signal.relay_uj)}/{relay_text(signal.relay_lj)}"
            )
        telegram = snapshot.telegram
        self.leu_label.setText(
            f"LEU/报文：{telegram.port_id} · {telegram.template_id} · "
            f"{telegram.mode.value}"
        )
        self.tsr_alarm_label.setText(
            f"临时限速：{len(snapshot.temporary_speeds)}　"
            f"活动告警：{len(snapshot.alarms)}"
        )
        severity = "critical" if any(
            item.level.value == "CRITICAL" for item in snapshot.alarms
        ) else ("warning" if snapshot.alarms else "info")
        set_semantic_state(self.tsr_alarm_label, "severity", severity)
        self.metrics_label.setText(
            f"发送/接收：{snapshot.network_sent}/{snapshot.network_received}"
        )
