from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QFont,
    QColor,
    QPolygon
)
from PyQt5.QtCore import Qt, QPoint


class SimulationView(QWidget):
    """
    列车运行实时仿真窗口。

    纵向布局全部以轨道中心线 LINE_Y 为基准，
    修改 LINE_Y 时各元素的偏移量会自动跟随。
    """

    # ==========================================
    # 纵向布局参数（单位：像素，相对轨道中心线）
    # ==========================================

    # 轨道中心线
    LINE_Y = 370

    # 标题与运行方向
    TITLE_OFFSET = -330
    DIRECTION_TEXT_OFFSET = -295

    # 运行方向箭头
    # 该偏移量决定箭头下方可供列车分层的竖向空间。
    # 实测区间内同时最多 4 辆列车，按 4 层列车不重叠反解：
    # 偏移小于 -264 时第 4 层的标签会穿过箭头。
    ARROW_OFFSET = -270

    # 列车图形（QPainter 绘制，侧视图，车头朝运行方向）
    TRAIN_LENGTH = 56            # 车体总长
    TRAIN_BODY_HEIGHT = 26       # 车体高度（不含车轮与受电弓）
    TRAIN_WHEEL_RADIUS = 4       # 车轮半径
    TRAIN_PANTOGRAPH_HEIGHT = 8  # 受电弓高度

    # 列车图形总高
    TRAIN_TOTAL_HEIGHT = (
            TRAIN_BODY_HEIGHT
            + TRAIN_WHEEL_RADIUS * 2
            + TRAIN_PANTOGRAPH_HEIGHT
    )

    # 车轮底部相对轨道中心线的位置（贴轨）
    TRAIN_BOTTOM_OFFSET = -1

    # 列车分层与标签
    # 约束关系：
    #   TRAIN_LABEL_GAP > TRAIN_TOTAL_HEIGHT（标签落在列车上方）
    #   TRAIN_LAYER_GAP > TRAIN_LABEL_GAP + 标签字高
    #                      （上层列车不压到下层标签）
    TRAIN_LAYER_GAP = 62
    TRAIN_LABEL_GAP = 48

    # 标签最多伸出区间端点的距离，避免压到车站信号机
    LABEL_EDGE_ALLOWANCE = 6

    # 信号机
    SIGNAL_OFFSET = -60

    # 信号机距区间端点的水平距离（需大于列车半长）
    SIGNAL_X_GAP = 58

    # 轨道下方各行
    STATION_OFFSET = 5
    TRACK_NAME_OFFSET = 45
    TRACK_CODE_OFFSET = 75
    BALISE_OFFSET = 130

    def __init__(self, parent=None):
        super().__init__(parent)

        # 保证 LINE_Y 下方各行（含应答器名称）不被裁掉
        self.setMinimumHeight(570)

        self.tracks = []
        self.trains = []

        self.direction = "A_TO_B"

        self.signal_a = "红灯"
        self.signal_b = "红灯"

    # ==========================================
    # 接收实时状态
    # ==========================================

    def set_state(
        self,
        tracks,
        trains,
        direction,
        signal_a="红灯",
        signal_b="红灯"
    ):

        self.tracks = tracks
        self.trains = trains
        self.direction = direction

        self.signal_a = signal_a
        self.signal_b = signal_b

        self.update()

    # ==========================================
    # 信号颜色
    # ==========================================

    def get_signal_color(self, status):

        if status == "绿灯":
            return QColor(45, 180, 85)

        if status == "黄绿灯":
            return QColor(150, 200, 60)

        if status == "黄灯":
            return QColor(235, 180, 35)

        return QColor(215, 65, 65)

    # ==========================================
    # 码序颜色
    # ==========================================

    def get_code_color(self, code):

        if code in (
            "L5",
            "L3",
            "L2",
            "L"
        ):
            return QColor(
                30,
                155,
                75
            )

        if code == "LU":
            return QColor(
                150,
                155,
                35
            )

        if code == "U":
            return QColor(
                220,
                155,
                25
            )

        if code == "HU":
            return QColor(
                210,
                55,
                55
            )

        return QColor(
            100,
            100,
            100
        )

    # ==========================================
    # 主绘图
    # ==========================================

    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing
        )

        width = self.width()

        left = 135
        right = width - 135

        line_y = self.LINE_Y

        section_width = (
            right - left
        ) / 8.0

        # --------------------------------------
        # 标题
        # --------------------------------------

        painter.setPen(
            QColor(30, 30, 30)
        )

        painter.setFont(
            QFont(
                "Microsoft YaHei",
                12,
                QFont.Bold
            )
        )

        painter.drawText(
            20,
            line_y + self.TITLE_OFFSET,
            "列车运行实时仿真"
        )

        # --------------------------------------
        # 运行方向
        # --------------------------------------

        painter.setFont(
            QFont(
                "Microsoft YaHei",
                10
            )
        )

        if self.direction == "A_TO_B":

            direction_text = (
                "当前运行方向：A站 → B站"
            )

        else:

            direction_text = (
                "当前运行方向：B站 → A站"
            )

        painter.drawText(
            20,
            line_y + self.DIRECTION_TEXT_OFFSET,
            direction_text
        )

        # --------------------------------------
        # 方向箭头（位置跟随轨道中心线）
        # --------------------------------------

        painter.setPen(
            QPen(
                QColor(50, 110, 190),
                2
            )
        )

        arrow_y = line_y + self.ARROW_OFFSET

        if self.direction == "A_TO_B":

            painter.drawLine(
                left,
                arrow_y,
                right,
                arrow_y
            )

            painter.drawLine(
                right,
                arrow_y,
                right - 12,
                arrow_y - 6
            )

            painter.drawLine(
                right,
                arrow_y,
                right - 12,
                arrow_y + 6
            )

        else:

            painter.drawLine(
                right,
                arrow_y,
                left,
                arrow_y
            )

            painter.drawLine(
                left,
                arrow_y,
                left + 12,
                arrow_y - 6
            )

            painter.drawLine(
                left,
                arrow_y,
                left + 12,
                arrow_y + 6
            )

        # --------------------------------------
        # 车站
        # --------------------------------------

        painter.setPen(
            QColor(30, 30, 30)
        )

        painter.setFont(
            QFont(
                "Microsoft YaHei",
                10,
                QFont.Bold
            )
        )

        painter.drawText(
            35,
            line_y + self.STATION_OFFSET,
            "A站"
        )

        painter.drawText(
            width - 65,
            line_y + self.STATION_OFFSET,
            "B站"
        )

        # --------------------------------------
        # 8个闭塞分区
        # --------------------------------------

        for i in range(8):

            track_code = (
                f"G{i + 1:02d}"
            )

            x1 = (
                left
                + i * section_width
            )

            x2 = (
                x1
                + section_width
            )

            track_info = (
                self.find_track(
                    track_code
                )
            )

            occupied = False
            block_code = "-"

            if track_info:

                occupied = (
                    track_info.get(
                        "status"
                    )
                    == "占用"
                )

                block_code = (
                    track_info.get(
                        "signal_code"
                    )
                    or track_info.get("code")
                    or track_info.get(
                        "code_level"
                    )
                    or "-"
                )

            # ----------------------------------
            # 占用背景
            # ----------------------------------

            if occupied:

                painter.setBrush(
                    QColor(
                        255,
                        235,
                        235
                    )
                )

                painter.setPen(
                    Qt.NoPen
                )

                painter.drawRoundedRect(
                    int(x1 + 2),
                    line_y - 18,
                    int(
                        section_width - 4
                    ),
                    36,
                    6,
                    6
                )

            # ----------------------------------
            # 钢轨
            # ----------------------------------

            if occupied:

                rail_color = QColor(
                    205,
                    65,
                    60
                )

            else:

                rail_color = QColor(
                    65,
                    65,
                    65
                )

            painter.setPen(
                QPen(
                    rail_color,
                    5
                )
            )

            painter.drawLine(
                int(x1),
                line_y,
                int(x2),
                line_y
            )

            # ----------------------------------
            # 分区边界
            # ----------------------------------

            painter.setPen(
                QPen(
                    QColor(
                        155,
                        155,
                        155
                    ),
                    1
                )
            )

            painter.drawLine(
                int(x2),
                line_y - 14,
                int(x2),
                line_y + 14
            )

            center_x = (
                x1
                + section_width / 2
            )

            # ----------------------------------
            # G01
            # ----------------------------------

            painter.setPen(
                QColor(30, 30, 30)
            )

            painter.setFont(
                QFont(
                    "Microsoft YaHei",
                    9,
                    QFont.Bold
                )
            )

            painter.drawText(
                int(center_x - 18),
                line_y + self.TRACK_NAME_OFFSET,
                track_code
            )

            # ----------------------------------
            # 自动闭塞码序
            # ----------------------------------

            painter.setPen(
                self.get_code_color(
                    block_code
                )
            )

            painter.setFont(
                QFont(
                    "Microsoft YaHei",
                    10,
                    QFont.Bold
                )
            )

            painter.drawText(
                int(center_x - 12),
                line_y + self.TRACK_CODE_OFFSET,
                str(block_code)
            )

            # ----------------------------------
            # 无源应答器：对准所属闭塞分区中部
            # ----------------------------------

            balise_x = int(
                x1 + section_width / 2
            )

            balise_y = (
                line_y + self.BALISE_OFFSET
            )

            self.draw_balise(
                painter,
                balise_x,
                balise_y,
                f"B{i + 1:02d}",
                active=False
            )

        # --------------------------------------
        # S01 / S02
        # --------------------------------------

        self.draw_signal(
            painter,
            int(left - self.SIGNAL_X_GAP),
            line_y + self.SIGNAL_OFFSET,
            "S01",
            self.signal_a
        )

        self.draw_signal(
            painter,
            int(right + self.SIGNAL_X_GAP - 28),
            line_y + self.SIGNAL_OFFSET,
            "S02",
            self.signal_b
        )

        # --------------------------------------
        # BA-A / BA-B 有源应答器
        # 属车站设备，横向位于闭塞分区之外，
        # 与 B01～B08 同行构成最下面一行
        # --------------------------------------

        self.draw_balise(
            painter,
            int(left - 60),
            line_y + self.BALISE_OFFSET,
            "BA-A",
            active=True
        )

        self.draw_balise(
            painter,
            int(right + 45),
            line_y + self.BALISE_OFFSET,
            "BA-B",
            active=True
        )

        # --------------------------------------
        # 列车
        # --------------------------------------

        self.draw_trains(
            painter,
            left,
            section_width,
            line_y
        )

    # ==========================================
    # 查找轨道
    # ==========================================

    def find_track(
        self,
        track_code
    ):

        for track in self.tracks:

            code = (
                track.get("track_code")
                or track.get("code")
            )

            if code == track_code:
                return track

        return None

    # ==========================================
    # 画信号机
    # ==========================================

    def draw_signal(
        self,
        painter,
        x,
        y,
        signal_code,
        status
    ):

        painter.setPen(
            QColor(40, 40, 40)
        )

        painter.setFont(
            QFont(
                "Microsoft YaHei",
                8,
                QFont.Bold
            )
        )

        painter.drawText(
            x - 4,
            y - 10,
            signal_code
        )

        painter.setBrush(
            QColor(55, 55, 55)
        )

        painter.setPen(
            Qt.NoPen
        )

        painter.drawRoundedRect(
            x,
            y,
            26,
            38,
            6,
            6
        )

        painter.setBrush(
            self.get_signal_color(
                status
            )
        )

        painter.drawEllipse(
            x + 6,
            y + 9,
            14,
            14
        )

    # ==========================================
    # 画应答器
    # ==========================================

    def draw_balise(
        self,
        painter,
        x,
        y,
        name,
        active=False
    ):

        if active:

            color = QColor(
                135,
                75,
                185
            )

        else:

            color = QColor(
                45,
                120,
                190
            )

        painter.setBrush(
            QBrush(color)
        )

        painter.setPen(
            QPen(
                color,
                1
            )
        )

        polygon = QPolygon([
            QPoint(
                x,
                y - 7
            ),
            QPoint(
                x + 7,
                y
            ),
            QPoint(
                x,
                y + 7
            ),
            QPoint(
                x - 7,
                y
            )
        ])

        painter.drawPolygon(
            polygon
        )

        painter.setPen(
            QColor(40, 40, 40)
        )

        painter.setFont(
            QFont(
                "Microsoft YaHei",
                8
            )
        )

        painter.drawText(
            x - 15,
            y + 25,
            name
        )

    # ==========================================
    # 画多列车
    # ==========================================

    def draw_trains(
        self,
        painter,
        left,
        section_width,
        line_y
    ):

        for index, train in enumerate(
            self.trains
        ):

            if train.get(
                "status"
            ) not in (
                "RUNNING",
                "STOPPED"
            ):
                continue

            track_code = train.get(
                "current_track"
            )

            if not track_code:
                continue

            try:

                track_number = int(
                    track_code[1:]
                )

            except ValueError:
                continue

            position = float(
                train.get(
                    "position",
                    0.0
                )
            )

            ratio = max(
                0.0,
                min(
                    position / 1000.0,
                    1.0
                )
            )

            section_index = (
                track_number - 1
            )

            if train.get(
                "direction"
            ) == "A_TO_B":

                x = (
                    left
                    + section_index
                    * section_width
                    + ratio
                    * section_width
                )

            else:

                x = (
                    left
                    + section_index
                    * section_width
                    + (
                        1.0 - ratio
                    )
                    * section_width
                )

            # 多辆车自下而上分层，避免标签互相重叠
            y_offset = (
                    index
                    * self.TRAIN_LAYER_GAP
            )

            # 列车底部（车轮底部）位置
            train_y = (
                    line_y
                    + self.TRAIN_BOTTOM_OFFSET
                    - y_offset
            )

            safety = train.get(
                "safety_status",
                "CLEAR"
            )

            if safety == "DANGER":

                train_color = QColor(
                    210,
                    50,
                    50
                )

            elif safety == "WARNING":

                train_color = QColor(
                    220,
                    145,
                    30
                )

            else:

                train_color = QColor(
                    30,
                    95,
                    185
                )

            # ----------------------------------
            # 列车图形（QPainter 绘制，车头朝运行方向）
            # ----------------------------------

            self.draw_train(
                painter,
                x,
                train_y,
                train_color,
                train.get("direction") == "A_TO_B"
            )

            # ----------------------------------
            # 列车文字（位于列车上方的分层带内）
            # ----------------------------------

            painter.setFont(
                QFont(
                    "Microsoft YaHei",
                    8,
                    QFont.Bold
                )
            )

            current_speed = (
                train.get(
                    "speed",
                    0
                )
            )

            target_speed = (
                train.get(
                    "target_speed",
                    0
                )
            )

            block_code = (
                train.get(
                    "block_code",
                    "-"
                )
            )

            text = (
                f"{train.get('train_id')}  "
                f"{current_speed:.0f}"
                f"→"
                f"{target_speed:.0f} "
                f"[{block_code}]"
            )

            label_y = (
                    train_y
                    - self.TRAIN_LABEL_GAP
            )

            metrics = painter.fontMetrics()

            text_width = metrics.horizontalAdvance(
                text
            )

            # 标签居中于列车，但不伸出区间两端，
            # 避免压到车站信号机
            right_edge = (
                    left
                    + section_width * 8
            )

            label_x = int(
                x - text_width / 2
            )

            label_x = max(
                int(
                    left
                    - self.LABEL_EDGE_ALLOWANCE
                ),
                min(
                    label_x,
                    int(
                        right_edge
                        - text_width
                        + self.LABEL_EDGE_ALLOWANCE
                    )
                )
            )

            painter.drawText(
                label_x,
                label_y,
                text
            )

    # ==========================================
    # 画列车（QPainter 图形，侧视高速列车）
    # ==========================================

    def draw_train(
        self,
        painter,
        center_x,
        bottom_y,
        train_color,
        facing_right=True
    ):
        """
        绘制一辆高速列车。

        center_x     车体水平中心
        bottom_y     车轮底部（贴轨道）
        train_color  车体主色，按安全状态取值
        facing_right 车头是否朝右（A→B 朝右）
        """

        length = self.TRAIN_LENGTH

        sign = 1.0 if facing_right else -1.0

        wheel_r = self.TRAIN_WHEEL_RADIUS

        # 车轮底部在 bottom_y，车体坐在车轮之上
        body_bottom = bottom_y - wheel_r * 2

        body_top = (
                body_bottom
                - self.TRAIN_BODY_HEIGHT
        )

        half = length / 2.0

        def px(offset):
            """车体横向偏移 -> 屏幕x（朝左时自动镜像）"""
            return int(center_x + sign * offset)

        def rect(offset, y, width, height):
            """按车体横向偏移绘制矩形（镜像时自动换向）"""
            x_a = px(offset)
            x_b = px(offset + width)

            painter.drawRect(
                min(x_a, x_b),
                int(y),
                abs(x_b - x_a),
                int(height)
            )

        # ----------------------------------
        # 受电弓
        # ----------------------------------

        painter.setPen(
            QPen(
                QColor(95, 95, 100),
                2
            )
        )

        panto_y = int(
            body_top
            - self.TRAIN_PANTOGRAPH_HEIGHT
        )

        painter.drawLine(
            px(-6),
            int(body_top),
            px(-1),
            panto_y
        )

        painter.drawLine(
            px(-7),
            panto_y,
            px(5),
            panto_y
        )

        # ----------------------------------
        # 车体：带流线型车头的多边形
        # ----------------------------------

        nose = 16

        painter.setPen(
            QPen(
                train_color.darker(150),
                1
            )
        )

        painter.setBrush(
            QBrush(train_color)
        )

        painter.drawPolygon(
            QPolygon([
                QPoint(px(-half + 5), int(body_top)),
                QPoint(px(half - nose), int(body_top)),
                QPoint(px(half), int(body_top + 9)),
                QPoint(px(half), int(body_bottom)),
                QPoint(px(-half), int(body_bottom)),
                QPoint(px(-half), int(body_top + 7)),
            ])
        )

        # ----------------------------------
        # 车体下部腰带
        # ----------------------------------

        painter.setPen(Qt.NoPen)

        painter.setBrush(
            QBrush(train_color.darker(135))
        )

        rect(
            -half,
            body_bottom - 6,
            length,
            6
        )

        # ----------------------------------
        # 司机室前窗
        # ----------------------------------

        painter.setBrush(
            QBrush(QColor(200, 235, 255))
        )

        painter.drawPolygon(
            QPolygon([
                QPoint(px(half - nose + 1), int(body_top + 3)),
                QPoint(px(half - 6), int(body_top + 4)),
                QPoint(px(half - 3), int(body_top + 10)),
                QPoint(px(half - nose + 1), int(body_top + 10)),
            ])
        )

        # ----------------------------------
        # 客室侧窗
        # ----------------------------------

        window_y = body_top + 5

        for i in range(5):

            offset = -half + 12 + i * 9

            if offset > half - nose - 4:
                break

            rect(
                offset,
                window_y,
                6,
                8
            )

        # ----------------------------------
        # 前照灯
        # ----------------------------------

        painter.setBrush(
            QBrush(QColor(255, 228, 120))
        )

        painter.drawEllipse(
            px(half - 6),
            int(body_top + 6),
            4,
            4
        )

        # ----------------------------------
        # 转向架车轮
        # ----------------------------------

        painter.setBrush(
            QBrush(QColor(45, 45, 48))
        )

        for offset in (-half + 12, half - 15):

            painter.drawEllipse(
                px(offset) - wheel_r,
                int(bottom_y - wheel_r * 2),
                wheel_r * 2,
                wheel_r * 2
            )