from PyQt5.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
)


class StationPanel(QGroupBox):

    def __init__(self, station_type, parent=None):
        super().__init__(parent)

        self.station_type = station_type
        self.setObjectName(f"station_panel_{station_type.lower()}")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        if station_type == "A":
            self.setTitle("A站通信")
            self.signal_code = "S01"
            self.balise_code = "BA-A"
        else:
            self.setTitle("B站通信")
            self.signal_code = "S02"
            self.balise_code = "BA-B"

        self.init_ui()

    def init_ui(self):

        layout = QVBoxLayout(self)

        self.tcc_label = QLabel(
            f"TCC节点：TCC_{self.station_type}"
        )

        layout.addWidget(self.tcc_label)

        self.network_status_label = QLabel("通信状态：● 未启动")
        self.network_button = QPushButton("启动通信")

        layout.addWidget(
            self.network_status_label
        )

        network_buttons = QHBoxLayout()
        network_buttons.addWidget(self.network_button)
        self.disconnect_button = QPushButton("断开连接")
        self.disconnect_button.setEnabled(False)
        network_buttons.addWidget(self.disconnect_button)
        layout.addLayout(network_buttons)

        self.signal_label = QLabel(
            f"{self.signal_code}：🔴 红灯"
        )

        # 当前区间运行方向（只读显示）
        self.direction_label = QLabel(
            "当前区间方向：A站 → B站"
        )

        self.balise_label = QLabel(
            f"有源应答器：{self.balise_code}"
        )

        self.direction_button = QPushButton(
            "申请区间改方"
        )

        # 本界面为单进程仿真，无站间通信，
        # 改方需在C/S界面（main.py A / B）完成
        self.direction_button.setEnabled(False)
        self.direction_button.setToolTip(
            "本界面无站间通信，改方请在C/S界面操作"
        )


    def set_network_status(self, text):

        self.network_status_label.setText(
            text
        )

    def set_signal_status(self, status):

        if status in ("绿灯", "L灯"):
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
