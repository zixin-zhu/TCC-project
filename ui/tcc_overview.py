from PyQt5.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPolygon
from PyQt5.QtWidgets import QScrollArea, QSizePolicy, QWidget


class HorizontalWheelScrollArea(QScrollArea):
    """普通滚轮直接控制横向滚动，适合超长站场图。"""

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - delta)
        event.accept()


class TccOverviewWidget(QWidget):
    """把 A站、38 个区间轨道区段和 B站绘成一张连续长图。"""

    balise_clicked = pyqtSignal(str)

    SECTION_COUNT = 38
    BLOCK_COUNT = 19
    SECTIONS_PER_BLOCK = 2
    SECTION_WIDTH = 66
    STATION_WIDTH = 470
    SIDE_MARGIN = 28

    background_color = QColor("#05070a")
    foreground_color = QColor("#d7e2ee")
    muted_color = QColor("#76879a")
    rail_color = QColor("#9eb2c7")

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
        total_width = (
            self.SIDE_MARGIN * 2
            + self.STATION_WIDTH * 2
            + self.SECTION_COUNT * self.SECTION_WIDTH
        )
        self.setMinimumWidth(total_width)
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Expanding)

        self.tracks = []
        self.trains = []
        self.restrictions = []
        self.direction = "A_TO_B"
        self.signal_a = "红灯"
        self.signal_b = "红灯"
        self._active_balise_hitboxes = {}

    @staticmethod
    def layout_contract():
        return {
            "source": "TCC整理_可编辑版.docx 7.1",
            "stations": ["A站", "B站"],
            "station_tracks": {"A站": ["1G", "3G"], "B站": ["1G", "3G"]},
            "approach_sections": {"A站SN外方": 3, "B站X外方": 3},
            "interval_section_count": 38,
            "block_section_count": 19,
            "track_sections_per_block": 2,
            "display_direction": "下行",
            "continuous_layout": True,
            "active_balise_groups": ["A站SN口_JZ", "区间_JZ", "B站X口_JZ"],
        }

    def set_state(
        self,
        tracks,
        trains,
        direction,
        signal_a="红灯",
        signal_b="红灯",
        restrictions=None,
    ):
        self.tracks = tracks or []
        self.trains = trains or []
        self.direction = direction
        self.signal_a = signal_a
        self.signal_b = signal_b
        self.restrictions = restrictions or []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.background_color)

        height = self.height()
        rail_y = max(145, int(height * 0.51))
        code_y = rail_y + 30
        a_left = self.SIDE_MARGIN
        interval_left = a_left + self.STATION_WIDTH
        interval_right = interval_left + self.SECTION_COUNT * self.SECTION_WIDTH
        b_right = interval_right + self.STATION_WIDTH

        painter.setPen(self.foreground_color)
        painter.setFont(QFont("PingFang SC", 13, QFont.Bold))
        painter.drawText(a_left, 29, "A站 — 下行区间 — B站列控状态总览")
        painter.setPen(QColor("#8ab7dd"))
        painter.setFont(QFont("PingFang SC", 9))
        direction = "A站 → B站" if self.direction == "A_TO_B" else "B站 → A站"
        painter.drawText(a_left, 50, f"当前方向：{direction}    滚轮横向查看完整站场")

        painter.setPen(QPen(self.rail_color, 2))
        painter.drawLine(a_left, rail_y, b_right, rail_y)

        self._active_balise_hitboxes = {}
        self._draw_station(painter, a_left, interval_left, rail_y, "A")
        self._draw_interval(painter, interval_left, rail_y, code_y)
        self._draw_station(painter, interval_right, b_right, rail_y, "B")
        self._draw_restrictions(painter, interval_left, code_y)
        self._draw_train_markers(painter, interval_left, rail_y)

    def _draw_station(self, painter, left, right, rail_y, station):
        station_center = (left + right) / 2
        side_y = rail_y - 68
        throat = 72
        siding_left = left + 82
        siding_right = right - 82

        painter.setPen(QPen(self.rail_color, 2))
        painter.drawLine(int(siding_left), side_y, int(siding_right), side_y)
        painter.drawLine(int(siding_left - throat), rail_y, int(siding_left), side_y)
        painter.drawLine(int(siding_right), side_y, int(siding_right + throat), rail_y)

        painter.setPen(self.foreground_color)
        painter.setFont(QFont("PingFang SC", 9, QFont.Bold))
        painter.drawText(int(station_center - 13), rail_y - 10, "1G")
        painter.drawText(int(station_center - 13), side_y - 10, "3G")
        painter.drawText(int(left + 18), 82, f"{station}站站场")

        if station == "A":
            signal_x = right - 22
            signal_name = "SN"
            signal_status = self.signal_a
            balise_x = signal_x - 28
        else:
            signal_x = left + 22
            signal_name = "X"
            signal_status = self.signal_b
            balise_x = signal_x + 28

        self._draw_signal(painter, signal_x, rail_y, signal_name, signal_status)
        self._draw_balise_group(
            painter,
            balise_x,
            rail_y + 60,
            f"{station}站{signal_name}口_JZ",
            active=True,
        )
        self._draw_balise_group(
            painter,
            station_center,
            side_y + 29,
            f"{station}站_DD",
            active=False,
        )

    def _draw_interval(self, painter, left, rail_y, code_y):
        state_by_code = {
            item.get("track_code") or item.get("code"): item for item in self.tracks
        }
        default_codes = ["L5", "L4", "L3", "L2", "L", "LU", "U", "HU"]

        painter.setPen(QColor("#8fa2b4"))
        painter.setFont(QFont("PingFang SC", 8, QFont.Bold))
        painter.drawText(int(left + 8), 82, "区间：38个轨道区段 / 19个闭塞分区")

        for index in range(self.SECTION_COUNT):
            x1 = left + index * self.SECTION_WIDTH
            x2 = x1 + self.SECTION_WIDTH
            track_id = f"G{index + 1:02d}"
            item = state_by_code.get(track_id, {})
            occupied = item.get("status") == "占用"
            code = item.get("signal_code") or item.get("code_level")
            if not code:
                distance_from_end = self.SECTION_COUNT - index - 1
                code = default_codes[min(distance_from_end, len(default_codes) - 1)]

            painter.setPen(QPen(self.CODE_COLORS["B"] if occupied else self.rail_color, 4 if occupied else 2))
            painter.drawLine(int(x1), rail_y, int(x2), rail_y)
            painter.setPen(QPen(QColor("#4b6072"), 1))
            painter.drawLine(int(x2), rail_y - 9, int(x2), rail_y + 9)

            painter.setBrush(self.CODE_COLORS.get(code, self.CODE_COLORS["-"]))
            painter.setPen(QPen(QColor("#101820"), 1))
            painter.drawRect(int(x1), code_y, self.SECTION_WIDTH, 22)
            painter.setPen(QColor("#071009") if code not in ("B", "-") else QColor("#ffffff"))
            painter.setFont(QFont("PingFang SC", 7, QFont.Bold))
            painter.drawText(int(x1 + 4), code_y + 15, str(code))
            painter.setPen(self.muted_color)
            painter.setFont(QFont("PingFang SC", 7))
            painter.drawText(int(x1 + 4), rail_y - 10, track_id)

            if (index + 1) % self.SECTIONS_PER_BLOCK == 0 and index < self.SECTION_COUNT - 1:
                block_no = (index + 1) // self.SECTIONS_PER_BLOCK
                boundary_x = x2
                self._draw_signal(painter, boundary_x, rail_y, f"S{block_no:02d}", "绿灯", compact=True)
                painter.setPen(QColor("#60798e"))
                painter.setFont(QFont("PingFang SC", 6))
                painter.drawText(int(x1 - self.SECTION_WIDTH + 4), code_y + 38, f"闭塞{block_no:02d}")

        interval_balise_x = left + self.SECTION_WIDTH * 34.5
        self._draw_balise_group(painter, interval_balise_x, rail_y + 60, "区间_JZ", active=True)

    def _draw_restrictions(self, painter, interval_left, code_y):
        for restriction in self.restrictions:
            if not restriction.get("active", True):
                continue
            try:
                start = int(restriction["start_section"][1:]) - 1
                end = int(restriction["end_section"][1:]) - 1
            except (KeyError, TypeError, ValueError):
                continue
            x = interval_left + start * self.SECTION_WIDTH
            width = (end - start + 1) * self.SECTION_WIDTH
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#ff3344"), 3))
            painter.drawRoundedRect(QRectF(x + 2, code_y - 5, width - 4, 32), 4, 4)
            painter.setPen(QColor("#ff7883"))
            painter.setFont(QFont("PingFang SC", 7, QFont.Bold))
            painter.drawText(int(x + 5), code_y - 9, f"限速 {restriction.get('speed_kmh', '--')} km/h")

    def _draw_signal(self, painter, x, rail_y, name, status, compact=False):
        stem_height = 26 if compact else 34
        radius = 4 if compact else 5
        painter.setPen(QPen(QColor("#aebdca"), 1))
        painter.drawLine(int(x), rail_y, int(x), rail_y - stem_height)
        colors = {
            "绿灯": [QColor("#35e463")],
            "黄灯": [QColor("#ffd930")],
            "黄绿灯": [QColor("#35e463"), QColor("#ffd930")],
        }.get(status, [QColor("#ff3b45")])
        for index, color in enumerate(colors):
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#dbe6ef"), 1))
            painter.drawEllipse(int(x - radius + index * 10), rail_y - stem_height - radius * 2, radius * 2, radius * 2)
        painter.setPen(QColor("#8fa2b4"))
        painter.setFont(QFont("PingFang SC", 6 if compact else 7))
        painter.drawText(int(x - 9), rail_y - stem_height - radius * 2 - 3, name)

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
        painter.setFont(QFont("PingFang SC", 6))
        painter.drawText(int(x - 28), int(y + 18), name)
        if active:
            self._active_balise_hitboxes[name] = QRectF(x - 20, y - 13, 40, 38)

    def _draw_train_markers(self, painter, interval_left, rail_y):
        for train in self.trains:
            if train.get("status") not in ("RUNNING", "STOPPED"):
                continue
            track_code = train.get("current_track") or ""
            try:
                index = int(track_code[1:]) - 1
            except (ValueError, TypeError):
                continue
            ratio = max(0.0, min(float(train.get("position", 0)) / 1000.0, 1.0))
            x = interval_left + (index + ratio) * self.SECTION_WIDTH
            painter.setBrush(QColor("#e8f1f8"))
            painter.setPen(QPen(QColor("#4aaee8"), 1))
            painter.drawRoundedRect(QRectF(x - 14, rail_y - 20, 28, 12), 3, 3)

    def mousePressEvent(self, event):
        for balise_id, hitbox in self._active_balise_hitboxes.items():
            if hitbox.contains(event.pos()):
                self.balise_clicked.emit(balise_id)
                event.accept()
                return
        super().mousePressEvent(event)
