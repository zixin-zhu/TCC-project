from PyQt5.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPolygon
from PyQt5.QtWidgets import QScrollArea, QSizePolicy, QWidget

from models.route import RouteType


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
    SECTION_WIDTH = 34
    STATION_WIDTH = 390
    APPROACH_SECTION_WIDTH = 34
    SIDE_MARGIN = 28
    SECTION_EQUIPMENT_ALIASES = {
        "G01": "X1LQ",
        "G02": "X2LQ",
        "G03": "X3LQ",
        "G36": "X1JG",
        "G37": "X2JG",
        "G38": "X3JG",
    }

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
        self.routes = ()
        self.station_codes = {
            "A": {"1G": "HU", "3G": "HU", "THROAT": "HU"},
            "B": {"1G": "HU", "3G": "HU", "THROAT": "HU"},
        }
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
            "interval_signal_direction": "RIGHT_FIXED",
            "section_equipment_aliases": dict(
                TccOverviewWidget.SECTION_EQUIPMENT_ALIASES
            ),
            "active_balise_groups": ["JZ", "FJZ", "CZ", "FCZ"],
        }

    @staticmethod
    def station_layout_contract(station):
        common_signals = {
            "X": "RIGHT",
            "S3": "LEFT",
            "S1": "LEFT",
            "X3": "RIGHT",
            "X1": "RIGHT",
        }
        active_balise_groups = {
            "JZ": {"signal": "X", "side": "LEFT", "count": 3},
            "FJZ": {"signal": "S", "side": "RIGHT", "count": 3},
            "X1_CZ": {"signal": "X1", "side": "LEFT", "count": 3},
            "X3_CZ": {"signal": "X3", "side": "LEFT", "count": 3},
            "S1_FCZ": {"signal": "S1", "side": "RIGHT", "count": 3},
            "S3_FCZ": {"signal": "S3", "side": "RIGHT", "count": 3},
        }
        if station == "A":
            return {
                "signals": {**common_signals, "SN": "LEFT"},
                "approach_sections": ["X1LQ", "X2LQ", "X3LQ"],
                "approach_side": "AFTER_SN",
                "active_balise_count": 3,
                "active_balise_groups": active_balise_groups,
                "passive_balise_count": 2,
            }
        return {
            "signals": {**common_signals, "S": "LEFT"},
            "approach_sections": ["X1JG", "X2JG", "X3JG"],
            "approach_side": "BEFORE_X",
            "active_balise_count": 3,
            "active_balise_groups": active_balise_groups,
            "passive_balise_count": 2,
        }

    @staticmethod
    def route_highlight_contract(station, route_type):
        if station not in ("A", "B"):
            raise ValueError("非法车站")
        route_tracks = {
            RouteType.MAIN_RECEIVE: "1G",
            RouteType.MAIN_DEPART: "1G",
            RouteType.SIDE_RECEIVE: "3G",
            RouteType.SIDE_DEPART: "3G",
        }
        if route_type not in route_tracks:
            raise ValueError("非法进路类型")
        return {
            "station": station,
            "route_type": route_type,
            "track": route_tracks[route_type],
            "interval_throat": "RIGHT" if station == "A" else "LEFT",
        }

    def set_state(
        self,
        tracks,
        trains,
        direction,
        signal_a="红灯",
        signal_b="红灯",
        restrictions=None,
        routes=None,
        station_codes=None,
    ):
        self.tracks = tracks or []
        self.trains = trains or []
        self.direction = direction
        self.signal_a = signal_a
        self.signal_b = signal_b
        self.restrictions = restrictions or []
        self.routes = tuple(dict(route) for route in (routes or []))
        if station_codes is not None:
            self.station_codes = {
                station: dict(codes)
                for station, codes in station_codes.items()
            }
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
        contract = self.station_layout_contract(station)
        core_left = left + 10
        core_right = right - 10

        station_center = (core_left + core_right) / 2
        side_y = rail_y - 68
        siding_left = core_left + 78
        siding_right = core_right - 78
        main_left_throat = core_left + 48
        main_right_throat = core_right - 48

        painter.setPen(QPen(self.rail_color, 2))
        painter.drawLine(int(siding_left), side_y, int(siding_right), side_y)
        painter.drawLine(int(main_left_throat), rail_y, int(siding_left), side_y)
        painter.drawLine(int(siding_right), side_y, int(main_right_throat), rail_y)

        self._draw_route_highlights(
            painter,
            station,
            core_left,
            core_right,
            rail_y,
            side_y,
            siding_left,
            siding_right,
            main_left_throat,
            main_right_throat,
        )

        painter.setPen(self.foreground_color)
        painter.setFont(QFont("PingFang SC", 8, QFont.Bold))
        painter.drawText(int(station_center - 13), rail_y - 10, "1G")
        painter.drawText(int(station_center - 13), side_y - 10, "3G")
        painter.drawText(int(core_left + 4), 82, f"{station}站站场")

        outer_left_x = core_left + 22
        inner_left_x = core_left + 98
        inner_right_x = core_right - 98
        outer_right_x = core_right - 22
        outer_right_name = "SN" if station == "A" else "S"

        signal_specs = [
            (outer_left_x, rail_y, "X", "RIGHT"),
            (inner_left_x, side_y, "S3", "LEFT"),
            (inner_left_x, rail_y, "S1", "LEFT"),
            (inner_right_x, side_y, "X3", "RIGHT"),
            (inner_right_x, rail_y, "X1", "RIGHT"),
            (outer_right_x, rail_y, outer_right_name, "LEFT"),
        ]
        for signal_x, track_y, signal_name, signal_direction in signal_specs:
            signal_status = "红灯"
            if station == "A" and signal_name == "SN":
                signal_status = self.signal_a
            elif station == "B" and signal_name == "X":
                signal_status = self.signal_b
            self._draw_signal(
                painter,
                signal_x,
                track_y,
                signal_name,
                signal_status,
                direction=signal_direction,
            )

        self._draw_station_code_bands(
            painter,
            station,
            core_left,
            core_right,
            station_center,
            rail_y,
            side_y,
        )

        balise_specs = (
            (outer_left_x - 34, rail_y + 55, f"{station}站_X_JZ", "JZ"),
            (outer_right_x + 34, rail_y + 55, f"{station}站_{outer_right_name}_FJZ", "FJZ"),
            (inner_right_x - 32, rail_y + 55, f"{station}站_X1_CZ", "CZ"),
            (inner_right_x - 32, side_y + 40, f"{station}站_X3_CZ", "CZ"),
            (inner_left_x + 32, rail_y + 55, f"{station}站_S1_FCZ", "FCZ"),
            (inner_left_x + 32, side_y + 40, f"{station}站_S3_FCZ", "FCZ"),
        )
        for balise_x, balise_y, balise_id, label in balise_specs:
            self._draw_balise_group(
                painter,
                balise_x,
                balise_y,
                balise_id,
                active=True,
                count=contract["active_balise_count"],
                spacing=8,
                label=label,
            )
        self._draw_balise_group(
            painter,
            station_center,
            side_y + 45,
            f"{station}站3G_DD",
            active=False,
            count=contract["passive_balise_count"],
            label="",
        )

    def _draw_station_code_bands(
        self,
        painter,
        station,
        core_left,
        core_right,
        station_center,
        rail_y,
        side_y,
    ):
        codes = self.station_codes.get(station, {})
        band_width = 70
        band_height = 17
        throat_width = 46

        def draw_band(x, y, width, code):
            painter.setBrush(self.CODE_COLORS.get(code, self.CODE_COLORS["-"]))
            painter.setPen(QPen(QColor("#101820"), 1))
            painter.drawRect(int(x), int(y), int(width), band_height)
            painter.setPen(QColor("#071009") if code not in ("B", "-") else QColor("#ffffff"))
            painter.setFont(QFont("PingFang SC", 6, QFont.Bold))
            painter.drawText(int(x + 4), int(y + 12), str(code))

        draw_band(station_center - band_width / 2, rail_y + 17, band_width, codes.get("1G", "HU"))
        draw_band(station_center - band_width / 2, side_y + 14, band_width, codes.get("3G", "HU"))
        throat_x = core_right - throat_width if station == "A" else core_left
        draw_band(throat_x, rail_y + 17, throat_width, codes.get("THROAT", "HU"))

    def _draw_route_highlights(
        self,
        painter,
        station,
        core_left,
        core_right,
        rail_y,
        side_y,
        siding_left,
        siding_right,
        main_left_throat,
        main_right_throat,
    ):
        painter.setPen(
            QPen(
                QColor("#8de6ff"),
                4,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        )
        for route in self.routes:
            if route.get("station") != station:
                continue
            contract = self.route_highlight_contract(
                station,
                route.get("route_type"),
            )
            if contract["track"] == "1G":
                painter.drawLine(int(core_left), rail_y, int(core_right), rail_y)
                continue

            painter.drawLine(int(siding_left), side_y, int(siding_right), side_y)
            if contract["interval_throat"] == "RIGHT":
                painter.drawLine(
                    int(siding_right),
                    side_y,
                    int(main_right_throat),
                    rail_y,
                )
                painter.drawLine(int(main_right_throat), rail_y, int(core_right), rail_y)
            else:
                painter.drawLine(int(core_left), rail_y, int(main_left_throat), rail_y)
                painter.drawLine(
                    int(main_left_throat),
                    rail_y,
                    int(siding_left),
                    side_y,
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
            equipment_name = self.SECTION_EQUIPMENT_ALIASES.get(track_id)
            if equipment_name:
                painter.setPen(QColor("#8fa2b4"))
                painter.setFont(QFont("PingFang SC", 6, QFont.Bold))
                painter.drawText(int(x1 + 2), rail_y + 17, equipment_name)

            if (index + 1) % self.SECTIONS_PER_BLOCK == 0 and index < self.SECTION_COUNT - 1:
                block_no = (index + 1) // self.SECTIONS_PER_BLOCK
                boundary_x = x2
                self._draw_signal(
                    painter,
                    boundary_x,
                    rail_y,
                    f"S{block_no:02d}",
                    "绿灯",
                    compact=True,
                    direction="RIGHT",
                )
                painter.setPen(QColor("#60798e"))
                painter.setFont(QFont("PingFang SC", 6))
                painter.drawText(int(x1 - self.SECTION_WIDTH + 4), code_y + 38, f"闭塞{block_no:02d}")

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

    def _draw_signal(
        self,
        painter,
        x,
        rail_y,
        name,
        status,
        compact=False,
        direction="RIGHT",
    ):
        stem_height = 26 if compact else 34
        radius = 4 if compact else 5
        direction_sign = 1 if direction == "RIGHT" else -1
        arm_length = 9 if compact else 12
        lamp_center_x = x + direction_sign * (arm_length + radius)
        lamp_center_y = rail_y - stem_height
        painter.setPen(QPen(QColor("#aebdca"), 1))
        painter.drawLine(int(x), rail_y + 5, int(x), rail_y - stem_height)
        painter.drawLine(
            int(x),
            int(lamp_center_y),
            int(x + direction_sign * arm_length),
            int(lamp_center_y),
        )
        colors = {
            "绿灯": [QColor("#35e463")],
            "L灯": [QColor("#35e463")],
            "黄灯": [QColor("#ffd930")],
            "黄绿灯": [QColor("#35e463"), QColor("#ffd930")],
        }.get(status, [QColor("#ff3b45")])
        for index, color in enumerate(colors):
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#dbe6ef"), 1))
            center_x = lamp_center_x + direction_sign * index * (radius * 2 + 2)
            painter.drawEllipse(
                int(center_x - radius),
                int(lamp_center_y - radius),
                radius * 2,
                radius * 2,
            )
        painter.setPen(QColor("#8fa2b4"))
        painter.setFont(QFont("PingFang SC", 6 if compact else 7))
        label_x = x - 9 if direction == "RIGHT" else x - 22
        painter.drawText(int(label_x), int(lamp_center_y - radius - 4), name)

    def _draw_balise_group(
        self,
        painter,
        x,
        y,
        name,
        active,
        count=2,
        spacing=14,
        label=None,
    ):
        offsets = [(index - (count - 1) / 2) * spacing for index in range(count)]
        for offset in offsets:
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
        display_label = name if label is None else label
        if display_label:
            painter.setPen(QColor("#83a2ba"))
            painter.setFont(QFont("PingFang SC", 6))
            painter.drawText(int(x - 10), int(y + 18), display_label)
        if active:
            hit_width = max(40, (count - 1) * spacing + 24)
            self._active_balise_hitboxes[name] = QRectF(
                x - hit_width / 2,
                y - 13,
                hit_width,
                38,
            )

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
