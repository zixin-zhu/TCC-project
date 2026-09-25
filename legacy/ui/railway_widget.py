from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QPen, QBrush, QFont
from PyQt5.QtCore import Qt


class RailwayWidget(QWidget):
    """
    铁路线路可视化组件

    负责显示：
    1. A站、B站
    2. G01轨道区段
    3. S01信号机
    4. 轨道占用状态
    """

    def __init__(self):
        super().__init__()

        # 当前轨道状态
        self.track_status = "空闲"

        # 当前信号机状态
        self.signal_status = "红灯"

        self.setMinimumHeight(230)

    def set_status(self, track_status, signal_status):
        """
        接收外部传来的轨道和信号状态
        """
        self.track_status = track_status
        self.signal_status = signal_status

        # 要求PyQt重新绘制界面
        self.update()

    def paintEvent(self, event):
        """
        PyQt需要重绘组件时自动执行
        """

        painter = QPainter(self)

        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        center_y = 120

        # =========================
        # 1. 绘制站名
        # =========================

        painter.setPen(Qt.black)
        painter.setFont(QFont("Microsoft YaHei", 12))

        painter.drawText(60, center_y + 6, "A站")
        painter.drawText(width - 100, center_y + 6, "B站")

        # =========================
        # 2. 绘制G01轨道
        # =========================

        if self.track_status == "占用":
            track_pen = QPen(Qt.red, 6)
        else:
            track_pen = QPen(Qt.black, 4)

        painter.setPen(track_pen)

        track_start = 200
        track_end = width - 200

        painter.drawLine(
            track_start,
            center_y,
            track_end,
            center_y
        )

        # G01文字
        painter.setPen(Qt.black)
        painter.drawText(
            width // 2 - 20,
            center_y - 20,
            "G01"
        )

        # =========================
        # 3. 绘制S01信号机
        # =========================

        signal_x = 150
        signal_y = center_y

        # 信号机杆
        painter.setPen(QPen(Qt.black, 3))

        painter.drawLine(
            signal_x,
            signal_y,
            signal_x,
            signal_y + 55
        )

        # 信号机外壳
        painter.setBrush(QBrush(Qt.black))

        painter.drawRoundedRect(
            signal_x - 13,
            signal_y - 55,
            26,
            55,
            6,
            6
        )

        # 根据状态选择灯色
        if self.signal_status == "绿灯":
            light_color = Qt.green

        elif self.signal_status == "黄灯":
            light_color = Qt.yellow

        else:
            light_color = Qt.red

        painter.setBrush(QBrush(light_color))
        painter.setPen(Qt.NoPen)

        painter.drawEllipse(
            signal_x - 8,
            signal_y - 40,
            16,
            16
        )

        # S01编号
        painter.setPen(Qt.black)

        painter.drawText(
            signal_x - 18,
            signal_y + 75,
            "S01"
        )

        # =========================
        # 4. 显示轨道状态
        # =========================

        painter.drawText(
            width // 2 - 45,
            center_y + 40,
            f"状态：{self.track_status}"
        )