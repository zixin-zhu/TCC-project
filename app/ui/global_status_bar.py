"""双站主窗口顶部的全局运行状态条。"""

from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel

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
        self.direction_label = QLabel("当前方向：--")
        self.lock_label = QLabel("作业状态：安全锁闭")
        self.alarm_label = QLabel("活动告警：--")
        for label in (
            self.lifecycle_label,
            self.communication_label,
            self.direction_label,
            self.lock_label,
            self.alarm_label,
        ):
            layout.addWidget(label)
        layout.addStretch(1)

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
        self.direction_label.setText(f"当前方向：{direction_text}（{consistency}）")
        self.lock_label.setText(
            "作业状态：安全锁闭"
            if snapshot.operation_locked
            else "作业状态：作业允许"
        )
        # 锁闭时把聚合器给出的具体原因作为悬浮提示，帮助用户定位「操作不了」根因。
        self.lock_label.setToolTip(
            snapshot.lock_reason if snapshot.operation_locked else ""
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
