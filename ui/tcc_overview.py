from PyQt5.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPolygon
from PyQt5.QtWidgets import QWidget


class TccOverviewWidget(QWidget):
    """按课程 Word 7.1 绘制的 A站—区间—B站总览图。"""

    balise_clicked = pyqtSignal(str)

    background_color = QColor("#05070a")
    foreground_color = QColor("#d7e2ee")
    muted_color = QColor("#76879a")
    rail_color = QColor("#9eb2c7")
    accent_color = QColor("#39a9ff")

    CODE_COLORS = {
        "L5": QColor("#087f32"),
        "L4": QColor("#0f9f3a"),
        "L3": QColor("#12b844"),
        "L2": QColor("#19ca4b"),
        "L": QColor("#23df53"),
        "LU": QColor("#9eea2d"),
        "U": QColor("#f5dc32"),
        "HU": QColor("#ef6c26"),
        "UUS": QColor("#d8c936"),
        "B": QColor("#ef3d48"),
        "-": QColor("#394552"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tcc_overview")
        self.setMinimumHeight(300)
        self.setMouseTracking(True)

        self.tracks = []
        self.trains = []
        self.direction = "A_TO_B"
        self.signal_a = "红灯"
        self.signal_b = "红灯"
        self._active_balise_hitboxes = {}

    @staticmethod
    def layout_contract():
        """暴露视图结构，供测试和后续配置化改造使用。"""
        return {
            "source": "TCC整理_可编辑版.docx 7.1",
            "stations": ["A站", "B站"],
            "station_tracks": {"A站": ["1G", "3G"], "B站": ["1G", "3G"]},
            "approach_sections": {"A站SN外方": 3, "B站X外方": 3},
            "interval_section_count": 8,
            "display_direction": "下行",
            "active_balise_groups": ["A站SN口_JZ", "B站X口_JZ"],
        }

    def set_state(
        self,
        tracks,
        trains,
        direction,
        signal_a="红灯",
        signal_b="红灯",
    ):
        self.tracks = tracks or []
        self.trains = trains or []
        self.direction = direction
        self.signal_a = signal_a
        self.signal_b = signal_b
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.background_color)

        width = self.width()
        height = self.height()
        margin = 24

        painter.setPen(self.foreground_color)
        painter.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        painter.drawText(margin, 28, "A站—区间—B站列控状态总览")

        direction_text = "A站 → B站" if self.direction == "A_TO_B" else "B站 → A站"
        painter.setPen(QColor("#8ab7dd"))
        painter.setFont(QFont("Microsoft YaHei", 9))
        painter.drawText(width - 238, 27, f"显示线路：下行   当前方向：{direction_text}")

        upper_top = 48
        upper_bottom = max(190, int(height * 0.54))
        gutter = 14
        card_width = (width - margin * 2 - gutter) / 2
        a_rect = QRectF(margin, upper_top, card_width, upper_bottom - upper_top)
        b_rect = QRectF(margin + card_width + gutter, upper_top, card_width, upper_bottom - upper_top)
        interval_rect = QRectF(
            margin,
            upper_bottom + gutter,
            width - margin * 2,
            height - upper_bottom - gutter - 18,
        )

        self._draw_card(painter, a_rect, "A站站场（SN 外方三段）")
        self._draw_card(painter, b_rect, "B站站场（X 外方三段）")
        self._draw_card(painter, interval_rect, "A—B 区间（下行）")

        self._active_balise_hitboxes = {}
        self._draw_station(painter, a_rect.adjusted(12, 29, -12, -9), "A")
        self._draw_station(painter, b_rect.adjusted(12, 29, -12, -9), "B")
        self._draw_interval(painter, interval_rect.adjusted(14, 27, -14, -8))

    def _draw_card(self, painter, rect, title):
        painter.setBrush(QColor("#0b1016"))
        painter.setPen(QPen(QColor("#263544"), 1))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor("#b9c9d8"))
        painter.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        painter.drawText(int(rect.left() + 12), int(rect.top() + 20), title)

    def _draw_station(self, painter, rect, station):
        left = rect.left() + 12
        right = rect.right() - 12
        main_y = rect.top() + rect.height() * 0.58
        side_y = rect.top() + rect.height() * 0.28

        painter.setPen(QPen(self.rail_color, 2))
        painter.drawLine(int(left), int(main_y), int(right), int(main_y))
        painter.drawLine(int(left + rect.width() * 0.20), int(side_y), int(right - rect.width() * 0.20), int(side_y))
        painter.drawLine(int(left + rect.width() * 0.12), int(main_y), int(left + rect.width() * 0.20), int(side_y))
        painter.drawLine(int(right - rect.width() * 0.12), int(main_y), int(right - rect.width() * 0.20), int(side_y))

        painter.setFont(QFont("Microsoft YaHei", 8, QFont.Bold))
        painter.setPen(self.foreground_color)
        painter.drawText(int(rect.center().x() - 10), int(main_y - 8), "1G")
        painter.drawText(int(rect.center().x() - 10), int(side_y - 8), "3G")

        section_prefix = "X" if station == "A" else "X"
        suffix = "LQ" if station == "A" else "JG"
        section_width = rect.width() * 0.115
        section_start = right - section_width * 3 if station == "A" else left
        band_y = main_y + 17
        for index in range(3):
            x = section_start + section_width * index
            painter.setBrush(QColor("#17374c"))
            painter.setPen(QPen(QColor("#3d6d8d"), 1))
            painter.drawRect(int(x), int(band_y), int(section_width), 20)
            painter.setPen(QColor("#c7d8e6"))
            painter.setFont(QFont("Microsoft YaHei", 7))
            painter.drawText(int(x + 4), int(band_y + 14), f"{section_prefix}{index + 1}{suffix}")

        signal_x = right - 36 if station == "A" else left + 22
        signal_status = self.signal_a if station == "A" else self.signal_b
        signal_name = "SN" if station == "A" else "X"
        self._draw_signal(painter, signal_x, main_y, signal_name, signal_status)

        balise_x = signal_x - 28 if station == "A" else signal_x + 28
        balise_id = f"{station}站{signal_name}口_JZ"
        self._draw_balise_group(painter, balise_x, main_y + 53, balise_id, active=True)

        passive_x = left + rect.width() * 0.42 if station == "A" else right - rect.width() * 0.42
        self._draw_balise_group(painter, passive_x, side_y + 28, f"{station}站_DD", active=False)

    def _draw_interval(self, painter, rect):
        left = rect.left() + 10
        right = rect.right() - 10
        line_y = rect.top() + rect.height() * 0.43
        section_width = (right - left) / 8

        codes = ["L4", "L3", "L2", "L", "LU", "U", "HU", "L5"]
        state_by_code = {
            item.get("track_code") or item.get("code"): item for item in self.tracks
        }

        for index in range(8):
            x1 = left + section_width * index
            x2 = x1 + section_width
            track_id = f"G{index + 1:02d}"
            item = state_by_code.get(track_id, {})
            occupied = item.get("status") == "占用"
            code = (
                item.get("signal_code")
                or item.get("code_level")
                or ("B" if occupied else codes[index])
            )

            painter.setPen(QPen(self.CODE_COLORS["B"] if occupied else self.rail_color, 4 if occupied else 2))
            painter.drawLine(int(x1), int(line_y), int(x2), int(line_y))
            painter.setPen(QPen(self.muted_color, 1))
            painter.drawLine(int(x2), int(line_y - 8), int(x2), int(line_y + 8))

            band_y = line_y + 17
            painter.setBrush(self.CODE_COLORS.get(code, self.CODE_COLORS["-"]))
            painter.setPen(QPen(QColor("#101820"), 1))
            painter.drawRect(int(x1), int(band_y), int(section_width), 22)
            painter.setPen(QColor("#071009") if code not in ("B", "-") else QColor("#ffffff"))
            painter.setFont(QFont("Microsoft YaHei", 8, QFont.Bold))
            painter.drawText(int(x1 + 5), int(band_y + 15), str(code))
            painter.setPen(self.muted_color)
            painter.setFont(QFont("Microsoft YaHei", 7))
            painter.drawText(int(x1 + 4), int(line_y - 8), track_id)

            if index < 7:
                aspect = "绿灯"
                if code == "U":
                    aspect = "黄灯"
                elif code == "LU":
                    aspect = "黄绿灯"
                elif code in ("HU", "B"):
                    aspect = "红灯"
                self._draw_signal(painter, x2 - 7, line_y, f"S{index + 1}", aspect, compact=True)

        self._draw_train_markers(painter, left, section_width, line_y)

    def _draw_signal(self, painter, x, rail_y, name, status, compact=False):
        stem_height = 25 if compact else 31
        radius = 4 if compact else 5
        painter.setPen(QPen(QColor("#aebdca"), 1))
        painter.drawLine(int(x), int(rail_y), int(x), int(rail_y - stem_height))

        colors = []
        if status == "黄绿灯":
            colors = [QColor("#35e463"), QColor("#ffd930")]
        elif status == "绿灯":
            colors = [QColor("#35e463")]
        elif status == "黄灯":
            colors = [QColor("#ffd930")]
        else:
            colors = [QColor("#ff3b45")]

        for index, color in enumerate(colors):
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#dbe6ef"), 1))
            painter.drawEllipse(int(x - radius + index * 10), int(rail_y - stem_height - radius * 2), radius * 2, radius * 2)

        painter.setPen(QColor("#8fa2b4"))
        painter.setFont(QFont("Microsoft YaHei", 6 if compact else 7))
        painter.drawText(int(x - 9), int(rail_y - stem_height - radius * 2 - 3), name)

    def _draw_balise_group(self, painter, x, y, name, active):
        for offset in (-7, 7):
            points = QPolygon(
                [
                    QPoint(int(x + offset), int(y - 6)),
                    QPoint(int(x + offset - 6), int(y + 5)),
                    QPoint(int(x + offset + 6), int(y + 5)),
                ]
            )
            painter.setPen(QPen(QColor("#7dd3fc") if active else QColor("#bdcad5"), 1))
            painter.setBrush(QColor("#38bdf8") if active else Qt.NoBrush)
            painter.drawPolygon(points)

        painter.setPen(QColor("#83a2ba"))
        painter.setFont(QFont("Microsoft YaHei", 6))
        painter.drawText(int(x - 27), int(y + 18), name)
        if active:
            self._active_balise_hitboxes[name] = QRectF(x - 18, y - 12, 36, 36)

    def _draw_train_markers(self, painter, left, section_width, rail_y):
        for train in self.trains:
            if train.get("status") not in ("RUNNING", "STOPPED"):
                continue
            track_code = train.get("current_track") or ""
            try:
                index = int(track_code[1:]) - 1
            except (ValueError, TypeError):
                continue
            ratio = max(0.0, min(float(train.get("position", 0)) / 1000.0, 1.0))
            x = left + (index + ratio) * section_width
            painter.setBrush(QColor("#e8f1f8"))
            painter.setPen(QPen(QColor("#4aaee8"), 1))
            painter.drawRoundedRect(QRectF(x - 13, rail_y - 17, 26, 11), 3, 3)

    def mousePressEvent(self, event):
        for balise_id, hitbox in self._active_balise_hitboxes.items():
            if hitbox.contains(event.pos()):
                self.balise_clicked.emit(balise_id)
                event.accept()
                return
        super().mousePressEvent(event)
