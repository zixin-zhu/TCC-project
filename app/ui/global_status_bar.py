"""双站主窗口顶部的全局运行状态条。"""

from collections.abc import Callable

from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton

from app.core.interface_models import InterfaceHealth, InterfaceStatus
from app.core.models import OperationResult
from app.ui.dual_snapshot import DualStationSnapshot
from app.ui.styles import set_semantic_state


class GlobalStatusBar(QFrame):
    """始终以文字和语义色同时表达双站关键安全状态。"""

    def __init__(self, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setObjectName("globalStatusBar")
        layout = QHBoxLayout(self)
        self.lifecycle_label = QLabel("系统：启动中")
        self.communication_label = QLabel("站间通信：等待双站")
        self.interface_label = QLabel("接口：--")
        self.direction_label = QLabel("双方确认方向：--")
        self.lock_label = QLabel("作业状态：安全锁闭")
        self.alarm_label = QLabel("活动告警：--")
        self.recovery_button = QPushButton("安全复核并解除锁闭")
        self.recovery_button.setObjectName("globalRecoverDirectionButton")
        self.recovery_button.setEnabled(False)
        self._recovery_handler: Callable[[], OperationResult] | None = None
        for label in (
            self.lifecycle_label,
            self.communication_label,
            self.interface_label,
            self.direction_label,
            self.lock_label,
            self.alarm_label,
        ):
            layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(self.recovery_button)
        self.recovery_button.clicked.connect(self._recover)

    def set_recovery_handler(
        self, handler: Callable[[], OperationResult] | None
    ) -> None:
        """绑定顶部全局安全复核动作；按钮仍由快照锁闭状态控制。"""
        self._recovery_handler = handler
        self.recovery_button.setEnabled(handler is not None)

    def _recover(self) -> None:
        if self._recovery_handler is None:
            return
        result = self._recovery_handler()
        if result.success:
            QMessageBox.information(self, "安全复核成功", result.reason)
        else:
            QMessageBox.warning(self, "安全复核失败", result.reason)

    def set_lifecycle_text(self, text: str, *, failed: bool = False) -> None:
        self.lifecycle_label.setText(f"系统：{text}")
        set_semantic_state(
            self.lifecycle_label, "severity", "critical" if failed else "info"
        )

    def set_snapshot(self, snapshot: DualStationSnapshot) -> None:
        self.lifecycle_label.setText("系统：运行")
        connection = "HEALTHY" if snapshot.communication_healthy else "DEGRADED"
        self.communication_label.setText(
            "站间通信：通信健康"
            if snapshot.communication_healthy
            else "站间通信：异常/同步中"
        )
        set_semantic_state(
            self.communication_label, "connectionState", connection
        )
        direction_text = (
            "A→B"
            if snapshot.authoritative_direction.value == "A_TO_B"
            else "B→A"
        )
        consistency = "一致" if snapshot.direction_consistent else "方向不一致"
        self.direction_label.setText(f"双方确认方向：{direction_text}（{consistency}）")
        self.lock_label.setText(
            "作业状态：安全锁闭"
            if snapshot.operation_locked
            else "作业状态：作业允许"
        )
        # 锁闭时把聚合器给出的具体原因作为悬浮提示，帮助用户定位「操作不了」根因。
        self.lock_label.setToolTip(
            snapshot.lock_reason if snapshot.operation_locked else ""
        )
        self.recovery_button.setEnabled(
            self._recovery_handler is not None and snapshot.operation_locked
        )
        set_semantic_state(
            self.lock_label,
            "severity",
            "critical" if snapshot.operation_locked else "info",
        )
        self.alarm_label.setText(
            f"活动告警：{snapshot.active_alarm_count}　"
            f"严重：{snapshot.critical_alarm_count}"
        )
        set_semantic_state(
            self.alarm_label,
            "severity",
            "critical" if snapshot.critical_alarm_count else "info",
        )

    def set_interface_status(
        self,
        statuses: tuple[InterfaceStatus, ...] | list[InterfaceStatus],
        *,
        startup_complete: bool | None = None,
    ) -> None:
        """展示 P/Q/R/S/T/U/V/W 接口汇总，不用颜色替代具体状态文字。

        ``startup_complete`` 用来区分“首次启动尚未完成”与“运行中链路
        断开”。旧调用未提供该参数时保持兼容，仍按初始化状态显示自检。
        """
        if not statuses:
            self.interface_label.setText("接口：未接入诊断")
            set_semantic_state(self.interface_label, "severity", "warning")
            return
        failed = sum(item.health is InterfaceHealth.FAILED for item in statuses)
        degraded = sum(item.health is InterfaceHealth.DEGRADED for item in statuses)
        initializing = sum(
            item.health is InterfaceHealth.INITIALIZING for item in statuses
        )
        disconnected = sum(
            item.health is InterfaceHealth.DISCONNECTED for item in statuses
        )
        if failed:
            text = f"接口：{failed} 项故障"
            severity = "critical"
        elif degraded:
            text = f"接口：{degraded} 项降级"
            severity = "warning"
        elif initializing or (disconnected and startup_complete is not True):
            pending = initializing + disconnected
            text = f"接口：启动自检中（待检查 {pending} 项）"
            severity = "warning"
        elif disconnected:
            text = f"接口：{disconnected} 项断开"
            severity = "critical"
        else:
            text = f"接口：全部健康（{len(statuses)} 项）"
            severity = "info"
        self.interface_label.setText(text)
        set_semantic_state(self.interface_label, "severity", severity)
