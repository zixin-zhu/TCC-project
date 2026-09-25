from PyQt5.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton
)


class StationPanel(QGroupBox):

    def __init__(self, station_type, parent=None):
        super().__init__(parent)

        self.station_type = station_type

        if station_type == "A":
            self.setTitle("A站控制中心 · TCC-A")
            self.network_role = "Client"
            self.signal_code = "S01"
            self.balise_code = "BA-A"
        else:
            self.setTitle("B站控制中心 · TCC-B")
            self.network_role = "Server"
            self.signal_code = "S02"
            self.balise_code = "BA-B"

        self.init_ui()

    def init_ui(self):

        layout = QVBoxLayout(self)

        self.tcc_label = QLabel(
            f"TCC节点：TCC_{self.station_type}"
        )

        self.role_label = QLabel(
            f"通信角色：{self.network_role}"
        )

        layout.addWidget(self.tcc_label)
        layout.addWidget(self.role_label)

        if self.station_type == "A":

            self.network_status_label = QLabel(
                "通信状态：● 未连接"
            )

            self.network_button = QPushButton(
                "连接服务器"
            )

        else:

            self.network_status_label = QLabel(
                "服务器状态：● 未启动"
            )

            self.network_button = QPushButton(
                "开启服务器"
            )

        layout.addWidget(
            self.network_status_label
        )

        layout.addWidget(
            self.network_button
        )

        self.signal_label = QLabel(
            f"{self.signal_code}：🔴 红灯"
        )

        layout.addWidget(
            self.signal_label
        )

        # 当前区间运行方向（只读显示）
        self.direction_label = QLabel(
            "当前区间方向：A站 → B站"
        )

        layout.addWidget(
            self.direction_label
        )

        self.balise_label = QLabel(
            f"有源应答器：{self.balise_code}"
        )

        layout.addWidget(
            self.balise_label
        )

        button_layout = QHBoxLayout()

        self.direction_button = QPushButton(
            "申请区间改方"
        )

        # 本界面为单进程仿真，无站间通信，
        # 改方需在C/S界面（main.py A / B）完成
        self.direction_button.setEnabled(False)
        self.direction_button.setToolTip(
            "本界面无站间通信，改方请在C/S界面操作"
        )

        self.balise_button = QPushButton(
            "查看应答器报文"
        )

        button_layout.addWidget(
            self.direction_button
        )

        button_layout.addWidget(
            self.balise_button
        )

        layout.addLayout(
            button_layout
        )

        layout.addStretch()

    def set_network_status(self, text):

        self.network_status_label.setText(
            text
        )

    def set_signal_status(self, status):

        if status == "绿灯":
            icon = "🟢"

        elif status == "黄绿灯":
            icon = "🟢🟡"

        elif status == "黄灯":
            icon = "🟡"

        else:
            icon = "🔴"

        self.signal_label.setText(
            f"{self.signal_code}："
            f"{icon} {status}"
        )

    def set_direction_status(self, direction):
        """
        显示当前区间运行方向（只读）。
        """

        if direction == "A_TO_B":

            direction_text = "A站 → B站"

        else:

            direction_text = "B站 → A站"

        self.direction_label.setText(
            f"当前区间方向：{direction_text}"
        )