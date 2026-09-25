from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QColor,
    QFont
)
from PyQt5.QtCore import Qt


class TrackView(QWidget):
    """
    A站—B站区间线路可视化控件。

    负责显示：
    1. A/B站
    2. S01/S02信号机
    3. G01～G08闭塞分区
    4. 自动闭塞编码
    5. 列车当前位置
    6. 当前运行方向
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setMinimumHeight(230)

        # 默认轨道状态
        self.tracks = []

        for i in range(1, 9):
            self.tracks.append({
                "track_code": f"G{i:02d}",
                "status": "空闲",
                "signal_code": "-"
            })

        # 列车默认在区间外
        self.train_position = None

        # 默认方向
        self.direction = "A_TO_B"

        # 两端信号机状态
        self.signal_a = "红灯"
        self.signal_b = "红灯"

    def set_state(
        self,
        tracks,
        train_position,
        direction,
        signal_a="红灯",
        signal_b="红灯"
    ):
        """
        接收SimulationService/UI提供的最新状态。
        """

        self.tracks = tracks
        self.train_position = train_position
        self.direction = direction
        self.signal_a = signal_a
        self.signal_b = signal_b

        # 通知Qt重新绘制
        self.update()

    def draw_signal(
        self,
        painter,
        x,
        y,
        aspect
    ):
        """
        绘制简化三显示信号机。
        """

        # 信号机外壳
        painter.setPen(
            QPen(Qt.black, 2)
        )

        painter.setBrush(
            QBrush(QColor(50, 50, 50))
        )

        painter.drawRoundedRect(
            x - 8,
            y - 32,
            16,
            64,
            5,
            5
        )

        # 灯位
        colors = [
            QColor(90, 20, 20),
            QColor(90, 80, 20),
            QColor(20, 80, 20)
        ]

        if aspect == "红灯":
            colors[0] = QColor(255, 40, 40)

        elif aspect == "黄灯":
            colors[1] = QColor(255, 210, 40)

        elif aspect == "绿灯":
            colors[2] = QColor(40, 220, 80)

        for index, color in enumerate(colors):

            painter.setBrush(
                QBrush(color)
            )

            painter.drawEllipse(
                x - 5,
                y - 26 + index * 20,
                10,
                10
            )

        # 信号机立柱
        painter.setPen(
            QPen(Qt.black, 2)
        )

        painter.drawLine(
            x,
            y + 32,
            x,
            y + 52
        )

    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing
        )

        width = self.width()

        # -------------------------
        # 基础位置
        # -------------------------

        line_y = 105

        left_margin = 130
        right_margin = 130

        usable_width = (
            width
            - left_margin
            - right_margin
        )

        section_width = (
            usable_width / 8
        )

        # =========================
        # 1. 绘制运行方向
        # =========================

        painter.setPen(Qt.black)

        painter.setFont(
            QFont("Microsoft YaHei", 11)
        )

        if self.direction == "A_TO_B":
            direction_text = "运行方向：A → B"
        else:
            direction_text = "运行方向：B → A"

        painter.drawText(
            0,
            10,
            width,
            30,
            Qt.AlignCenter,
            direction_text
        )
        arrow_y = 58

        painter.setPen(
            QPen(
                QColor(
                    60,
                    90,
                    150
                ),
                2
            )
        )

        if self.direction == "A_TO_B":

            painter.drawLine(
                300,
                arrow_y,
                width - 300,
                arrow_y
            )

            painter.drawLine(
                width - 300,
                arrow_y,
                width - 315,
                arrow_y - 7
            )

            painter.drawLine(
                width - 300,
                arrow_y,
                width - 315,
                arrow_y + 7
            )

        else:

            painter.drawLine(
                width - 300,
                arrow_y,
                300,
                arrow_y
            )

            painter.drawLine(
                300,
                arrow_y,
                315,
                arrow_y - 7
            )

            painter.drawLine(
                300,
                arrow_y,
                315,
                arrow_y + 7
            )

        # =========================
        # 2. 绘制A站/B站
        # =========================

        painter.setFont(
            QFont("Microsoft YaHei", 12)
        )

        painter.drawText(
            20,
            line_y - 10,
            60,
            30,
            Qt.AlignCenter,
            "A站"
        )

        painter.drawText(
            width - 80,
            line_y - 10,
            60,
            30,
            Qt.AlignCenter,
            "B站"
        )

        # =========================
        # 3. 绘制S01 / S02
        # =========================

        signal_a_x = 100
        signal_b_x = width - 100

        self.draw_signal(
            painter,
            signal_a_x,
            line_y,
            self.signal_a
        )

        self.draw_signal(
            painter,
            signal_b_x,
            line_y,
            self.signal_b
        )

        painter.setFont(
            QFont("Microsoft YaHei", 9)
        )

        painter.drawText(
            signal_a_x - 25,
            line_y + 58,
            50,
            20,
            Qt.AlignCenter,
            "S01"
        )

        painter.drawText(
            signal_b_x - 25,
            line_y + 58,
            50,
            20,
            Qt.AlignCenter,
            "S02"
        )

        # =========================
        # 4. 绘制G01～G08
        # =========================

        for index, track in enumerate(
            self.tracks
        ):

            start_x = (
                left_margin
                + index * section_width
            )

            end_x = (
                start_x
                + section_width
            )

            center_x = (
                start_x + end_x
            ) / 2

            if track["status"] == "占用":
                painter.setPen(
                    Qt.NoPen
                )

                painter.setBrush(
                    QBrush(
                        QColor(
                            255,
                            225,
                            225
                        )
                    )
                )

                painter.drawRoundedRect(
                    int(start_x + 2),
                    line_y - 58,
                    int(section_width - 4),
                    120,
                    6,
                    6
                )
            # ---------------------
            # 根据占用状态画轨道
            # ---------------------

            if track["status"] == "占用":

                pen = QPen(
                    QColor(220, 50, 50),
                    6
                )

            else:

                pen = QPen(
                    QColor(40, 40, 40),
                    4
                )

            painter.setPen(pen)

            painter.drawLine(
                int(start_x + 3),
                line_y,
                int(end_x - 3),
                line_y
            )

            painter.setPen(
                QPen(
                    QColor(
                        120,
                        120,
                        120
                    ),
                    1
                )
            )

            if index < 7:
                painter.drawLine(
                    int(end_x),
                    line_y - 7,
                    int(end_x),
                    line_y + 7
                )

            # ---------------------
            # 分区名称
            # ---------------------

            painter.setPen(Qt.black)

            painter.setFont(
                QFont(
                    "Microsoft YaHei",
                    9
                )
            )

            painter.drawText(
                int(start_x),
                line_y + 15,
                int(section_width),
                20,
                Qt.AlignCenter,
                track["track_code"]
            )

            # ---------------------
            # 自动闭塞编码
            # ---------------------

            painter.setFont(
                QFont(
                    "Arial",
                    10,
                    QFont.Bold
                )
            )
            code = track["signal_code"]

            painter.setPen(
                QPen(
                    self.get_code_color(code)
                )
            )
            painter.drawText(
                int(start_x),
                line_y + 38,
                int(section_width),
                20,
                Qt.AlignCenter,
                track["signal_code"]
            )

            # ---------------------
            # 列车
            # ---------------------

            if (
                self.train_position
                == track["track_code"]
            ):

                painter.setFont(
                    QFont(
                        "Segoe UI Emoji",
                        20
                    )
                )

                painter.drawText(
                    int(center_x - 25),
                    line_y - 52,
                    50,
                    40,
                    Qt.AlignCenter,
                    "🚆"
                )

    def get_code_color(self, code):
        """
        根据自动闭塞编码返回显示颜色。
        仅用于仿真界面状态区分。
        """

        if code in (
                "L5",
                "L3",
                "L2",
                "L"
        ):
            return QColor(
                30,
                160,
                70
            )

        if code == "LU":
            return QColor(
                120,
                160,
                40
            )

        if code == "U":
            return QColor(
                220,
                170,
                20
            )

        if code == "HU":
            return QColor(
                210,
                60,
                40
            )

        return QColor(
            50,
            50,
            50
        )