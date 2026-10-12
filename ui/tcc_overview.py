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
    STATION_SECTION_WIDTH = 184
    STATION_OUTER_MARGIN = 32
    STATION_WIDTH = STATION_OUTER_MARGIN + STATION_SECTION_WIDTH * 3
    APPROACH_SECTION_WIDTH = 34
    SIDE_MARGIN = 28
    BALISE_HALF_WIDTH = 3
    BALISE_HEIGHT = 6
    BALISE_GROUP_SPACING = 6
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
    occupied_rail_color = QColor("#ef3d48")

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
        "B": QColor("#f5f7fa"),
        "-": QColor("#394552"),
    }
    CODE_SPEEDS = {
        "HU": 0,
        "UUS": 45,
        "U": 45,
        "LU": 80,
        "L": 100,
        "L2": 110,
        "L3": 120,
        "L4": 120,
        "L5": 120,
        "B": 0,
        "-": 0,
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
        self._station_code_rects = {}
        self._station_signal_positions = {}
        self._balise_symbols = []
        self._interval_boundary_markers = []
        self._interval_code_segments = []
        self._train_marker_symbols = []

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
            "active_balise_groups": [
                "A站3G_DD",
                "A站_SN_FJZ",
                "B站3G_DD",
                "B站_X_JZ",
            ],
            "displayed_balise_groups": [
                "A站3G_DD",
                "A站_SN_FJZ",
                "B站3G_DD",
                "B站_X_JZ",
            ],
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
        if station == "A":
            return {
                "signals": {**common_signals, "SN": "LEFT"},
                "approach_sections": ["X1LQ", "X2LQ", "X3LQ"],
                "approach_side": "AFTER_SN",
                "active_balise_count": 3,
                "displayed_balise_groups": {
                    "3G_DD": {"track": "3G", "count": 2},
                    "SN_FJZ": {"signal": "SN", "side": "RIGHT", "count": 3},
                },
                "active_balise_groups": {
                    "3G_DD": {"track": "3G", "count": 2},
                    "SN_FJZ": {"signal": "SN", "side": "RIGHT", "count": 3},
                },
                "passive_balise_count": 2,
            }
        return {
            "signals": {**common_signals, "S": "LEFT"},
            "approach_sections": ["X1JG", "X2JG", "X3JG"],
            "approach_side": "BEFORE_X",
            "active_balise_count": 3,
            "displayed_balise_groups": {
                "3G_DD": {"track": "3G", "count": 2},
                "X_JZ": {"signal": "X", "side": "LEFT", "count": 3},
            },
            "active_balise_groups": {
                "3G_DD": {"track": "3G", "count": 2},
                "X_JZ": {"signal": "X", "side": "LEFT", "count": 3},
            },
            "passive_balise_count": 2,
        }

    @staticmethod
    def station_render_contract(station):
        if station not in ("A", "B"):
            raise ValueError("非法车站")
        outer_right_name = "SN" if station == "A" else "S"
        return {
            "signal_styles": {
                "X": "MAIN_EXTENDED",
                "S3": "SIDE_SHORT",
                "S1": "MAIN_EXTENDED",
                "X3": "SIDE_SHORT",
                "X1": "MAIN_EXTENDED",
                outer_right_name: "MAIN_EXTENDED",
            },
            "rail_at_signal": "CONTINUOUS",
            "signal_head_post": "GAPPED",
            "turnout_upper_connection": "CONTINUOUS",
            "turnout_lower_connection": "GAPPED",
            "side_signal_head": "FLUSH_TO_POST",
            "balise_fill_patterns": {
                "A_3G_DD": (False, True),
                "A_SN_FJZ": (True, False, False),
                "B_3G_DD": (True, False),
                "B_X_JZ": (False, False, True),
            },
            "clickable_balise": "FILLED_ONLY",
        }

    @classmethod
    def station_geometry_contract(cls, station):
        if station not in ("A", "B"):
            raise ValueError("非法车站")
        span = cls.STATION_SECTION_WIDTH
        if station == "A":
            signals = {
                "X": cls.STATION_OUTER_MARGIN,
                "S1": cls.STATION_OUTER_MARGIN + span,
                "X1": cls.STATION_OUTER_MARGIN + span * 2,
                "SN": cls.STATION_WIDTH,
            }
            code_sections = {
                "TRACK": ("S1", "X1"),
                "THROAT": ("X1", "SN"),
            }
            interval_boundary_signal = "SN"
        else:
            signals = {
                "X": 0,
                "S1": span,
                "X1": span * 2,
                "S": span * 3,
            }
            code_sections = {
                "THROAT": ("X", "S1"),
                "TRACK": ("S1", "X1"),
            }
            interval_boundary_signal = "X"
        return {
            "signals": signals,
            "section_spans": (span, span, span),
            "code_sections": code_sections,
            "interval_boundary_signal": interval_boundary_signal,
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
        endpoints = {
            ("A", RouteType.MAIN_DEPART): ("X1", "SN"),
            ("A", RouteType.SIDE_DEPART): ("X3", "SN"),
            ("A", RouteType.MAIN_RECEIVE): ("SN", "S1"),
            ("A", RouteType.SIDE_RECEIVE): ("SN", "S3"),
            ("B", RouteType.MAIN_RECEIVE): ("X", "X1"),
            ("B", RouteType.SIDE_RECEIVE): ("X", "X3"),
            ("B", RouteType.MAIN_DEPART): ("S1", "X"),
            ("B", RouteType.SIDE_DEPART): ("S3", "X"),
        }
        start_signal, end_signal = endpoints[(station, route_type)]
        return {
            "station": station,
            "route_type": route_type,
            "track": route_tracks[route_type],
            "interval_throat": "RIGHT" if station == "A" else "LEFT",
            "start_signal": start_signal,
            "end_signal": end_signal,
        }

    @staticmethod
    def train_marker_contract(train, waiting_index=0):
        direction = train.get("direction", "A_TO_B")
        status = train.get("status")
        phase = train.get("movement_phase")
        if status == "WAITING":
            return {
                "region": "WAITING",
                "station": "A" if direction == "A_TO_B" else "B",
                "signal": "X" if direction == "A_TO_B" else "S",
                "side": "RIGHT" if direction == "A_TO_B" else "LEFT",
                "label": f"x{waiting_index + 1}",
            }
        if phase in ("RECEIVING", "STATION_RUNNING", "EXITING"):
            position = max(0.0, min(float(train.get("station_position") or 0), 3000.0))
            return {
                "region": "STATION",
                "station": "B" if direction == "A_TO_B" else "A",
                "progress": position / 3000.0,
                "track": train.get("arrival_track") or "1G",
            }
        return {"region": "INTERVAL"}

    @classmethod
    def balise_geometry_contract(cls):
        return {
            "triangle_half_width": cls.BALISE_HALF_WIDTH,
            "triangle_height": cls.BALISE_HEIGHT,
            "group_spacing": cls.BALISE_GROUP_SPACING,
            "placement": "BETWEEN_RAIL_AND_CODE_BAND",
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
        self._station_code_rects = {}
        self._station_signal_positions = {}
        self._balise_symbols = []
        self._interval_boundary_markers = []
        self._interval_code_segments = []
        self._train_marker_symbols = []
        self._draw_station(painter, a_left, interval_left, rail_y, code_y, "A")
        self._draw_interval(painter, interval_left, rail_y, code_y)
        self._draw_station(painter, interval_right, b_right, rail_y, code_y, "B")
        self._draw_restrictions(painter, interval_left, code_y)
        self._draw_train_markers(painter, interval_left, rail_y)

    def _draw_station(self, painter, left, right, rail_y, code_y, station):
        contract = self.station_layout_contract(station)
        render_contract = self.station_render_contract(station)
        geometry = self.station_geometry_contract(station)
        signal_positions = {
            name: left + offset
            for name, offset in geometry["signals"].items()
        }
        self._station_signal_positions[station] = dict(signal_positions)

        outer_right_name = "SN" if station == "A" else "S"
        outer_left_x = signal_positions["X"]
        inner_left_x = signal_positions["S1"]
        inner_right_x = signal_positions["X1"]
        outer_right_x = signal_positions[outer_right_name]
        core_left = outer_left_x
        core_right = outer_right_x
        station_center = (inner_left_x + inner_right_x) / 2
        side_y = rail_y - 68
        siding_left = inner_left_x - 20
        siding_right = inner_right_x + 20
        main_left_throat = inner_left_x - 50
        main_right_throat = inner_right_x + 50

        painter.setPen(QPen(self.rail_color, 2))
        connection_gap = 5
        painter.drawLine(int(siding_left), side_y, int(siding_right), side_y)
        self._draw_lower_gapped_connection(
            painter,
            main_left_throat,
            rail_y,
            siding_left,
            side_y,
            connection_gap,
        )
        self._draw_lower_gapped_connection(
            painter,
            main_right_throat,
            rail_y,
            siding_right,
            side_y,
            connection_gap,
        )

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
                extend_below_track=(track_y == rail_y),
            )

        self._draw_station_code_bands(
            painter,
            station,
            core_left,
            core_right,
            station_center,
            rail_y,
            side_y,
            left,
            right,
            code_y,
        )

        if station == "A":
            balise_specs = (
                (station_center, side_y + 15, "A站3G_DD", "", "A_3G_DD"),
                (outer_right_x + 34, rail_y + 15, "A站_SN_FJZ", "FJZ", "A_SN_FJZ"),
            )
        else:
            balise_specs = (
                (station_center, side_y + 15, "B站3G_DD", "", "B_3G_DD"),
                (outer_left_x - 34, rail_y + 15, "B站_X_JZ", "JZ", "B_X_JZ"),
            )
        for balise_x, balise_y, balise_id, label, pattern_key in balise_specs:
            fill_pattern = render_contract["balise_fill_patterns"][pattern_key]
            self._draw_balise_group(
                painter,
                balise_x,
                balise_y,
                balise_id,
                active=True,
                count=len(fill_pattern),
                spacing=self.BALISE_GROUP_SPACING,
                label=label,
                fill_pattern=fill_pattern,
            )

    def _draw_lower_gapped_connection(
        self, painter, lower_x, lower_y, upper_x, upper_y, gap
    ):
        dx = upper_x - lower_x
        dy = upper_y - lower_y
        length = max((dx * dx + dy * dy) ** 0.5, 1.0)
        ux = dx / length
        uy = dy / length
        painter.drawLine(
            int(lower_x + ux * gap),
            int(lower_y + uy * gap),
            int(upper_x),
            int(upper_y),
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
        left,
        right,
        code_y,
    ):
        codes = self.station_codes.get(station, {})
        band_height = 22

        def draw_band(key, rect, code):
            self._station_code_rects[key] = QRectF(rect)
            painter.setBrush(self.CODE_COLORS.get(code, self.CODE_COLORS["-"]))
            painter.setPen(QPen(QColor("#101820"), 1))
            painter.drawRect(rect)
            painter.setPen(self._code_text_color(code))
            painter.setFont(QFont("PingFang SC", 7, QFont.Bold))
            painter.drawText(int(rect.x() + 4), int(rect.y() + 15), str(code))

        geometry = self.station_geometry_contract(station)
        positions = {
            name: left + offset
            for name, offset in geometry["signals"].items()
        }

        def section_rect(section_name):
            start_name, end_name = geometry["code_sections"][section_name]
            start_x = positions[start_name]
            end_x = positions[end_name]
            return QRectF(start_x, code_y, end_x - start_x, band_height)

        track_rect = section_rect("TRACK")
        throat_rect = section_rect("THROAT")

        route = next(
            (item for item in self.routes if item.get("station") == station),
            None,
        )
        route_track = route.get("track") if route else None
        track_code = codes.get(route_track, "HU") if route_track in ("1G", "3G") else "HU"
        draw_band(f"{station}_TRACK", track_rect, track_code)
        draw_band(f"{station}_THROAT", throat_rect, codes.get("THROAT", "HU"))

    @staticmethod
    def _code_text_color(code):
        return QColor("#071009") if code != "-" else QColor("#ffffff")

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
            positions = self._station_signal_positions[station]
            start_x = positions[contract["start_signal"]]
            end_x = positions[contract["end_signal"]]
            if contract["track"] == "1G":
                painter.drawLine(int(start_x), rail_y, int(end_x), rail_y)
                continue

            side_signal_x = (
                positions["X3"]
                if "X3" in (contract["start_signal"], contract["end_signal"])
                else positions["S3"]
            )
            outer_x = end_x if contract["end_signal"] in ("X", "SN", "S") else start_x
            if outer_x > side_signal_x:
                painter.drawLine(int(side_signal_x), side_y, int(siding_right), side_y)
                self._draw_lower_gapped_connection(
                    painter,
                    main_right_throat,
                    rail_y,
                    siding_right,
                    side_y,
                    5,
                )
                painter.drawLine(int(main_right_throat), rail_y, int(outer_x), rail_y)
            else:
                painter.drawLine(int(outer_x), rail_y, int(main_left_throat), rail_y)
                self._draw_lower_gapped_connection(
                    painter,
                    main_left_throat,
                    rail_y,
                    siding_left,
                    side_y,
                    5,
                )
                painter.drawLine(int(siding_left), side_y, int(side_signal_x), side_y)

    def _draw_interval(self, painter, left, rail_y, code_y):
        state_by_code = {
            item.get("track_code") or item.get("code"): item for item in self.tracks
        }

        painter.setPen(QColor("#8fa2b4"))
        painter.setFont(QFont("PingFang SC", 8, QFont.Bold))
        painter.drawText(int(left + 8), 82, "区间：38个轨道区段 / 19个闭塞分区")

        for index in range(self.SECTION_COUNT):
            x1 = left + index * self.SECTION_WIDTH
            x2 = x1 + self.SECTION_WIDTH
            track_id = f"G{index + 1:02d}"
            item = state_by_code.get(track_id, {})
            occupied = item.get("status") == "占用"

            painter.setPen(QPen(self.occupied_rail_color if occupied else self.rail_color, 4 if occupied else 2))
            painter.drawLine(int(x1), rail_y, int(x2), rail_y)
            painter.setPen(self.muted_color)
            painter.setFont(QFont("PingFang SC", 7))
            painter.drawText(int(x1 + 4), rail_y - 10, track_id)
            equipment_name = self.SECTION_EQUIPMENT_ALIASES.get(track_id)
            if equipment_name:
                painter.setPen(QColor("#8fa2b4"))
                painter.setFont(QFont("PingFang SC", 6, QFont.Bold))
                painter.drawText(int(x1 + 2), rail_y + 17, equipment_name)

            if index < self.SECTION_COUNT - 1:
                self._draw_interval_boundary(painter, x2, rail_y)

        for segment in self.interval_code_layout():
            x = left + segment["start_index"] * self.SECTION_WIDTH
            width = segment["span_sections"] * self.SECTION_WIDTH
            code = segment["code"]
            rect = QRectF(x, code_y, width, 22)
            painter.setBrush(self.CODE_COLORS.get(code, self.CODE_COLORS["-"]))
            painter.setPen(QPen(QColor("#101820"), 1))
            painter.drawRect(rect)
            painter.setPen(self._code_text_color(code))
            painter.setFont(QFont("PingFang SC", 7, QFont.Bold))
            painter.drawText(int(x + 5), code_y + 15, str(code))
            self._interval_code_segments.append({**segment, "rect": QRectF(rect)})

        for block_index in range(self.BLOCK_COUNT):
            block_left = left + block_index * self.SECTIONS_PER_BLOCK * self.SECTION_WIDTH
            block_right = block_left + self.SECTIONS_PER_BLOCK * self.SECTION_WIDTH
            block_no = block_index + 1
            if block_no < self.BLOCK_COUNT:
                self._draw_signal(
                    painter,
                    block_right,
                    rail_y,
                    f"S{block_no:02d}",
                    "绿灯",
                    compact=True,
                    direction="RIGHT",
                    extend_below_track=True,
                )
            painter.setPen(QColor("#60798e"))
            painter.setFont(QFont("PingFang SC", 6))
            painter.drawText(int(block_left + 4), code_y + 38, f"闭塞{block_no:02d}")

    def _draw_interval_boundary(self, painter, x, rail_y):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#b9c9d8"))
        radius = 2
        points = ((x, rail_y - 5), (x, rail_y + 5))
        for center_x, center_y in points:
            painter.drawEllipse(
                int(center_x - radius),
                int(center_y - radius),
                radius * 2,
                radius * 2,
            )
        self._interval_boundary_markers.append(
            {"kind": "DOUBLE_DOT", "points": points}
        )

    def interval_code_layout(self):
        state_by_code = {
            item.get("track_code") or item.get("code"): item for item in self.tracks
        }
        default_codes = ["L5", "L4", "L3", "L2", "L", "LU", "U", "HU"]

        def track_code(index):
            track_id = f"G{index + 1:02d}"
            item = state_by_code.get(track_id, {})
            code = item.get("signal_code") or item.get("code_level")
            if code:
                return code
            distance_from_end = self.SECTION_COUNT - index - 1
            return default_codes[min(distance_from_end, len(default_codes) - 1)]

        layout = []
        active_trains = [
            train
            for train in self.trains
            if train.get("status") in ("RUNNING", "STOPPED")
        ]
        for block_index in range(self.BLOCK_COUNT):
            start_index = block_index * self.SECTIONS_PER_BLOCK
            physical_indices = (start_index, start_index + 1)
            track_ids = tuple(f"G{index + 1:02d}" for index in physical_indices)
            codes = [track_code(index) for index in physical_indices]
            block_code = min(codes, key=lambda code: self.CODE_SPEEDS.get(code, 0))

            split_train = None
            passed_index = None
            current_index = None
            for train in active_trains:
                current_track = train.get("current_track")
                if current_track not in track_ids:
                    continue
                direction = train.get("direction") or self.direction
                ordered_indices = (
                    physical_indices
                    if direction == "A_TO_B"
                    else tuple(reversed(physical_indices))
                )
                train_index = int(current_track[1:]) - 1
                if train_index == ordered_indices[1]:
                    split_train = train
                    passed_index = ordered_indices[0]
                    current_index = ordered_indices[1]
                    break

            if split_train is None:
                layout.append(
                    {
                        "block_no": block_index + 1,
                        "track_ids": track_ids,
                        "start_index": start_index,
                        "span_sections": 2,
                        "code": block_code,
                        "role": "BLOCK",
                    }
                )
                continue

            split_segments = (
                {
                    "block_no": block_index + 1,
                    "track_ids": (f"G{passed_index + 1:02d}",),
                    "start_index": passed_index,
                    "span_sections": 1,
                    "code": "B",
                    "role": "PASSED",
                },
                {
                    "block_no": block_index + 1,
                    "track_ids": (f"G{current_index + 1:02d}",),
                    "start_index": current_index,
                    "span_sections": 1,
                    "code": block_code,
                    "role": "CURRENT",
                },
            )
            layout.extend(sorted(split_segments, key=lambda item: item["start_index"]))
        return layout

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
        extend_below_track=True,
    ):
        stem_height = 26 if compact else 34
        radius = 4 if compact else 5
        direction_sign = 1 if direction == "RIGHT" else -1
        is_side_signal = not extend_below_track
        arm_length = 0 if is_side_signal else (9 if compact else 12)
        lamp_center_x = x + direction_sign * (arm_length + radius)
        lamp_center_y = rail_y - stem_height
        lower_stem_top = lamp_center_y + (8 if compact else 10)
        upper_stem_bottom = lamp_center_y + (4 if compact else 5)
        stem_bottom = rail_y + (5 if extend_below_track else 0)

        painter.setPen(QPen(QColor("#aebdca"), 1))
        painter.drawLine(int(x), int(stem_bottom), int(x), int(lower_stem_top))
        painter.drawLine(
            int(x),
            int(upper_stem_bottom),
            int(x),
            int(lamp_center_y - radius - 2),
        )
        if arm_length:
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
        fill_pattern=None,
    ):
        spacing = self.BALISE_GROUP_SPACING if active else spacing
        half_width = self.BALISE_HALF_WIDTH
        half_height = self.BALISE_HEIGHT / 2
        offsets = [(index - (count - 1) / 2) * spacing for index in range(count)]
        pattern = tuple(fill_pattern or ((active,) * count))
        if len(pattern) != count:
            raise ValueError("应答器填充样式数量与应答器数量不一致")
        filled_offsets = []
        for index, (offset, filled) in enumerate(zip(offsets, pattern)):
            points = QPolygon(
                [
                    QPoint(int(x + offset), int(y - half_height)),
                    QPoint(int(x + offset - half_width), int(y + half_height)),
                    QPoint(int(x + offset + half_width), int(y + half_height)),
                ]
            )
            painter.setPen(QPen(QColor("#7dd3fc") if filled else QColor("#bdcad5"), 1))
            painter.setBrush(QColor("#38bdf8") if filled else Qt.NoBrush)
            painter.drawPolygon(points)
            self._balise_symbols.append(
                {
                    "group": name,
                    "index": index,
                    "filled": bool(filled),
                    "center": (x + offset, y),
                }
            )
            if filled:
                filled_offsets.append(offset)
        display_label = name if label is None else label
        if display_label:
            painter.setPen(QColor("#83a2ba"))
            painter.setFont(QFont("PingFang SC", 5))
            painter.drawText(int(x + 13), int(y + 3), display_label)
        if filled_offsets:
            filled_offset = filled_offsets[0]
            self._active_balise_hitboxes[name] = QRectF(
                x + filled_offset - 3.5,
                y - 6,
                7,
                12,
            )

    def _draw_train_markers(self, painter, interval_left, rail_y):
        waiting_count = 0
        for train in self.trains:
            contract = self.train_marker_contract(train, waiting_count)
            if contract["region"] == "WAITING":
                waiting_count += 1
                signal_x = self._station_signal_positions[contract["station"]][
                    contract["signal"]
                ]
                direction_sign = 1 if contract["side"] == "RIGHT" else -1
                x = signal_x + direction_sign * (18 + (waiting_count - 1) * 22)
                y = rail_y
                self._draw_train_marker(painter, x, y, contract["label"])
                continue

            if train.get("status") not in ("RUNNING", "STOPPED"):
                continue

            if contract["region"] == "STATION":
                positions = self._station_signal_positions[contract["station"]]
                if train.get("direction") == "A_TO_B":
                    start_x, end_x = positions["X"], positions["S"]
                else:
                    start_x, end_x = positions["SN"], positions["X"]
                progress = contract["progress"]
                x = start_x + (end_x - start_x) * progress
                side_progress = 0.18 < progress < 0.82
                y = rail_y - 68 if contract["track"] == "3G" and side_progress else rail_y
                self._draw_train_marker(painter, x, y, train.get("train_id", ""))
                continue

            track_code = train.get("current_track") or ""
            try:
                index = int(track_code[1:]) - 1
            except (ValueError, TypeError):
                continue
            ratio = max(0.0, min(float(train.get("position", 0)) / 1000.0, 1.0))
            x = interval_left + (index + ratio) * self.SECTION_WIDTH
            self._draw_train_marker(painter, x, rail_y, train.get("train_id", ""))

    def _draw_train_marker(self, painter, x, rail_y, label):
        rect = QRectF(x - 13, rail_y - 21, 26, 11)
        painter.setBrush(QColor("#e8f1f8"))
        painter.setPen(QPen(QColor("#4aaee8"), 1))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QColor("#8fd7ff"))
        painter.setFont(QFont("PingFang SC", 7, QFont.Bold))
        painter.drawText(int(x - 11), int(rail_y - 25), str(label))
        self._train_marker_symbols.append({"x": x, "rail_y": rail_y, "label": str(label)})

    def mousePressEvent(self, event):
        for balise_id, hitbox in self._active_balise_hitboxes.items():
            if hitbox.contains(event.pos()):
                self.balise_clicked.emit(balise_id)
                event.accept()
                return
        super().mousePressEvent(event)
