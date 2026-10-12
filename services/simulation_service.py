from models.tcc import TCC
from models.track_circuit import TrackCircuit
from models.signal import Signal
from models.balise import Balise
from models.route import RouteState, RouteType


class SimulationService:
    """
    单个车站TCC的仿真业务服务。

    A站和B站分别拥有自己的SimulationService，
    两个进程之间不直接共享Python对象。
    """

    # ==========================================
    # 自动闭塞码序 -> 信号机灯色
    # ==========================================

    CODE_ASPECTS = {
        "L5": "绿灯",
        "L4": "绿灯",
        "L3": "绿灯",
        "L2": "绿灯",
        "L": "绿灯",
        "LU": "黄绿灯",
        "U": "黄灯",
        "U2S": "黄灯",
        "HU": "红灯",
        "UUS": "双黄灯",
    }

    CODE_RESTRICTIVENESS = {
        "HU": 0,
        "UUS": 1,
        "U2S": 1,
        "U": 1,
        "LU": 2,
        "L": 3,
        "L2": 3,
        "L3": 3,
        "L4": 3,
        "L5": 3,
    }

    def __init__(self, station_type, route_service=None):

        self.station_type = station_type
        self.route_service = route_service

        # =========================
        # 1. 先创建本站TCC
        # =========================

        if station_type == "A":

            self.tcc = TCC(
                "TCC_A",
                "A站"
            )

            self.signal = Signal(
                "S01",
                "A站出站口"
            )

            self.balise = Balise(
                balise_id="BA-A",
                balise_type="ACTIVE",
                location="A站区间入口",
                track_code="G01",
                line_speed=120.0,
                gradient=0.0
            )

        else:

            self.tcc = TCC(
                "TCC_B",
                "B站"
            )

            self.signal = Signal(
                "S02",
                "B站出站口"
            )

            self.balise = Balise(
                balise_id="BA-A",
                balise_type="ACTIVE",
                location="A站区间入口",
                track_code="G01",
                line_speed=120.0,
                gradient=0.0
            )
        # =========================
        # 两端信号机状态
        # =========================
        self.signal_states = {"S01": "红灯", "S02": "红灯", self.signal.code: self.signal.get_aspect()}

        # 将本站实际信号机状态写入状态表
        # =========================
        # 2. 设置初始运行方向
        # =========================

        self.tcc.set_direction(
            "A_TO_B"
        )

        # =========================
        # 3. 创建38个轨道区段（每2个组成1个闭塞分区）
        # =========================

        self.track_circuits = {}

        for i in range(1, 39):
            code = f"G{i:02d}"

            track = TrackCircuit(
                code,
                f"A站-B站第{i}闭塞分区"
            )

            self.track_circuits[
                code
            ] = track

            self.tcc.add_track_circuit(
                track
            )

        self.block_section_pairs = {
            f"BS{i:02d}": (
                f"G{i * 2 - 1:02d}",
                f"G{i * 2:02d}",
            )
            for i in range(1, 20)
        }

        # =========================
        # 4. 暂时兼容以前的G01代码
        # =========================

        self.track_g01 = (
            self.track_circuits["G01"]
        )

        # =========================
        # 5. 添加信号机和应答器
        # =========================

        self.tcc.add_signal(
            self.signal
        )

        self.tcc.add_balise(
            self.balise
        )

        # =========================
        # 列车仿真状态
        # =========================

        # None表示列车还没有进入区间
        self.train_position = None
        self._train_states = []

        # 初始化全部闭塞分区编码
        self.update_all_track_codes()

    def get_block_section_pairs(self):
        return dict(self.block_section_pairs)

    def set_train_states(self, trains):
        """缓存列车快照，供站内占用发码和信号联动使用。"""
        self._train_states = [dict(train) for train in (trains or [])]

    # ==========================================
    # G01状态
    # ==========================================

    def train_enter_track(self):
        """
        模拟列车从当前运行方向的起点进入区间。
        """

        # 本站不是当前方向的发车站
        if not self.can_control_train():
            return False

        # 已经有列车在区间内
        if self.train_position is not None:
            return False

        running_order = self.get_running_order()

        # 当前方向的第一个闭塞分区
        first_track_code = running_order[0]

        first_track = self.track_circuits[
            first_track_code
        ]

        # 第一分区已经被占用，禁止进入
        if first_track.occupied:
            return False

        # 列车进入第一闭塞分区
        first_track.occupy()

        self.train_position = first_track_code

        # 列车进入后入口信号关闭
        self.signal.set_red()
        self.signal_states[
            self.signal.code
        ] = self.signal.get_aspect()

        # 重新计算全部轨道编码
        self.update_all_track_codes()

        return True

    def train_leave_track(self):
        """
        兼容旧接口：
        现在表示列车向前运行一步。
        """

        return self.move_train_forward()

    def open_signal(self):
        """
        尝试开放本站信号机。

        仿真安全条件：
        1. G01必须空闲
        2. 当前区间方向必须允许本站向区间发车
        """

        # 条件1：区间被占用，禁止开放
        if self.track_g01.occupied:
            self.signal.set_red()
            return False

        direction = self.tcc.get_direction()

        # 条件2：检查运行方向
        if self.station_type == "A":

            if direction != "A_TO_B":
                self.signal.set_red()
                return False

        elif self.station_type == "B":

            if direction != "B_TO_A":
                self.signal.set_red()
                return False

        # 条件全部满足
        self.signal.set_green()
        self.signal_states[
            self.signal.code
        ] = self.signal.get_aspect()

        return True

    def close_signal(self):
        """
        关闭本站信号机。
        """

        self.signal.set_red()
        self.signal_states[
            self.signal.code
        ] = self.signal.get_aspect()

    def update_remote_track_status(self, status):
        """
        根据另一TCC发送的站间信息，
        更新本地掌握的G01状态。
        """
        if status == "占用":
            self.track_g01.occupy()

        elif status == "空闲":
            self.track_g01.release()

    def update_remote_tracks(
            self,
            tracks,
            train_position=None
    ):
        """
        根据邻站TCC发送的数据，
        更新G01～G38状态和列车位置。
        """

        for item in tracks:

            code = item.get("code")
            status = item.get("status")

            track = self.track_circuits.get(
                code
            )

            # 防止收到非法分区编号
            if track is None:
                continue

            if status == "占用":
                track.occupy()

            else:
                track.release()

        # 同步列车位置
        self.train_position = train_position

        # 根据新的占用状态重新计算编码
        self.update_all_track_codes()

    # ==========================================
    # 获取状态
    # ==========================================

    def get_system_status(self):

        return {
            "tcc_code": self.tcc.code,
            "station": self.tcc.station_name,

            "track_code": self.track_g01.code,
            "track_status": self.track_g01.get_status(),

            "signal_code": self.signal.code,
            "signal_status": self.signal.get_aspect(),

            "direction": self.tcc.get_direction(),

            "train_position": self.train_position
        }

    def calculate_track_code(self, free_count):
        """
        根据前方连续空闲闭塞分区数量，
        计算课程仿真的轨道电路编码。
        """

        if free_count >= 7:
            return "L5"

        elif free_count >= 6:
            return "L4"

        elif free_count >= 5:
            return "L3"

        elif free_count >= 4:
            return "L2"

        elif free_count >= 3:
            return "L"

        elif free_count == 2:
            return "LU"

        elif free_count == 1:
            return "U"

        else:
            return "HU"

    def get_running_order(self):
        """
        根据当前区间运行方向，
        返回闭塞分区的运行顺序。
        """

        track_codes = list(
            self.track_circuits.keys()
        )

        direction = self.tcc.get_direction()

        if direction == "A_TO_B":
            return track_codes

        else:
            return list(
                reversed(track_codes)
            )

    def count_forward_free_tracks(self, track_code):
        """
        计算指定闭塞分区前方
        连续空闲闭塞分区的数量。
        """

        running_order = self.get_running_order()

        # 找到当前分区的位置
        current_index = running_order.index(
            track_code
        )

        free_count = 0

        # 从当前分区的下一个分区开始检查
        blocked = False
        for code in running_order[
                    current_index + 1:
                    ]:

            track = self.track_circuits[
                code
            ]

            # 遇到占用立即停止
            if track.occupied:
                blocked = True
                break

            free_count += 1

        if not blocked and self.has_any_matching_receive_route():
            free_count += 1

        return free_count

    def update_all_track_codes(self):
        """按两个轨道区段一个闭塞分区计算低频码序。"""
        pairs = list(self.block_section_pairs.values())
        if self.tcc.get_direction() == "B_TO_A":
            pairs.reverse()

        arrival_station = "B" if self.tcc.get_direction() == "A_TO_B" else "A"
        receive_route = (
            self.route_service.receive_route(arrival_station)
            if self.route_service is not None
            else None
        )
        route_extends_codes = (
            receive_route is not None
            and receive_route.state == RouteState.ESTABLISHED
        )

        for block_index, pair in enumerate(pairs):
            free_blocks = 0
            blocked_ahead = False
            for ahead_pair in pairs[block_index + 1:]:
                if any(self.track_circuits[code].occupied for code in ahead_pair):
                    blocked_ahead = True
                    break
                free_blocks += 1

            code = self.calculate_track_code(free_blocks)
            if route_extends_codes and not blocked_ahead:
                distance_to_station = len(pairs) - block_index - 1
                if receive_route.route_type == RouteType.SIDE_RECEIVE:
                    if distance_to_station == 0:
                        code = "UUS"
                    elif distance_to_station == 1:
                        code = "U2S"
                else:
                    code = self.calculate_track_code(free_blocks + 3)

            for track_code in pair:
                self.track_circuits[track_code].set_track_code(code)

        # 码序变化后立即联动信号机
        self.update_signal_status()

    # ==========================================
    # 信号机自动联动
    # ==========================================

    def aspect_for_code(self, code):
        """
        根据轨道电路码序得到信号机灯色。

        未知码序和空值按故障安全原则显示红灯。
        """

        return self.CODE_ASPECTS.get(
            code,
            "红灯"
        )

    def get_aspect_by_code(self, code):
        """兼容旧调用，统一委托给码序灯色映射。"""

        return self.aspect_for_code(code)

    def get_entry_track_code(self):
        """
        返回当前运行方向上的入口闭塞分区编号。
        """

        if self.tcc.get_direction() == "A_TO_B":
            return "G01"

        return "G38"

    def get_station_track_codes(self):
        """返回本站股道和区间侧咽喉的低频编码。

        站内码由当前已建立进路决定，不由绘图层自行推断：
        无进路时全部采用限制码 HU；正线发车时 1G 与相邻区间
        入口码保持连续；侧线接发车按课程文档使用 UUS；接车
        进路以股道停车目标为边界，正线股道保持 HU。
        """
        codes = {"1G": "HU", "3G": "HU", "THROAT": "HU"}
        direction = self.tcc.get_direction()
        arrival_station = "B" if direction == "A_TO_B" else "A"
        arrival_here = self.station_type == arrival_station
        for train in self._train_states:
            train_arrival = "B" if train.get("direction") == "A_TO_B" else "A"
            if train_arrival != self.station_type:
                continue
            if train.get("movement_phase") not in (
                "RECEIVING",
                "STATION_RUNNING",
                "EXITING",
            ):
                continue
            codes["THROAT"] = "B"
            return codes

        if self.route_service is None:
            if arrival_here:
                codes["THROAT"] = "B"
            return codes

        routes = self.route_service.active_routes(self.station_type)
        if not routes:
            if arrival_here:
                codes["THROAT"] = "B"
            return codes

        route = routes[0]
        if route.movement == "RECEIVE":
            return codes
        if route.route_type == RouteType.MAIN_DEPART:
            adjacent_code = self.track_circuits[
                "G01" if self.station_type == "A" else "G38"
            ].signal_code
            codes["1G"] = adjacent_code
            codes["THROAT"] = adjacent_code
        elif route.route_type == RouteType.SIDE_DEPART:
            codes["3G"] = "UUS"
            codes["THROAT"] = "UUS"

        return codes

    def get_station_signal_aspects(self):
        """返回本站六架信号机的灯色快照。

        只有与当前区间方向一致的已建立进路才允许开放对应的
        两架信号机；无进路、方向冲突或发车口被占用时全部红灯。
        """
        signal_names = (
            ("X", "S3", "S1", "X3", "X1", "SN")
            if self.station_type == "A"
            else ("X", "S3", "S1", "X3", "X1", "S")
        )
        aspects = {name: "红灯" for name in signal_names}
        if self.route_service is None:
            return aspects

        routes = self.route_service.active_routes(self.station_type)
        if not routes:
            return aspects
        route = routes[0]

        direction = self.tcc.get_direction()
        allowed_movement = {
            ("A", "A_TO_B"): "DEPART",
            ("A", "B_TO_A"): "RECEIVE",
            ("B", "A_TO_B"): "RECEIVE",
            ("B", "B_TO_A"): "DEPART",
        }.get((self.station_type, direction))
        if route.movement != allowed_movement:
            return aspects

        if route.movement == "DEPART":
            exit_track = "G01" if self.station_type == "A" else "G38"
            if self.track_circuits[exit_track].occupied:
                return aspects

        endpoints = {
            ("A", RouteType.MAIN_DEPART): ("X1", "SN", "1G"),
            ("A", RouteType.SIDE_DEPART): ("X3", "SN", "3G"),
            ("A", RouteType.MAIN_RECEIVE): ("S1", "SN", "1G"),
            ("A", RouteType.SIDE_RECEIVE): ("S3", "SN", "3G"),
            ("B", RouteType.MAIN_RECEIVE): ("X1", "X", "1G"),
            ("B", RouteType.SIDE_RECEIVE): ("X3", "X", "3G"),
            ("B", RouteType.MAIN_DEPART): ("S1", "S", "1G"),
            ("B", RouteType.SIDE_DEPART): ("S3", "S", "3G"),
        }
        endpoint = endpoints.get((self.station_type, route.route_type))
        if endpoint is None:
            return aspects

        inner_signal, boundary_signal, station_track = endpoint
        codes = self.get_station_track_codes()
        if route.route_type in (
            RouteType.SIDE_RECEIVE,
            RouteType.SIDE_DEPART,
        ):
            aspects[inner_signal] = "L灯"
        else:
            aspects[inner_signal] = self.aspect_for_code(codes.get(station_track))
        aspects[boundary_signal] = self.aspect_for_code(codes.get("THROAT"))
        return aspects

    def get_interval_signal_aspects(self):
        """返回下行方向十八架区间信号机的灯色快照。

        每架信号机防护前方一个闭塞分区（两个轨道区段），取两段
        码序中更限制的一项；占用、未知码序和反方向均按红灯处理。
        """
        aspects = {f"S{i:02d}": "红灯" for i in range(1, 19)}
        if self.tcc.get_direction() != "A_TO_B":
            return aspects

        for signal_index in range(1, 19):
            protected = (
                self.track_circuits[f"G{signal_index * 2 - 1:02d}"],
                self.track_circuits[f"G{signal_index * 2:02d}"],
            )
            codes = [track.signal_code for track in protected]
            if any(code not in self.CODE_RESTRICTIVENESS for code in codes):
                continue
            restrictive_code = min(
                codes,
                key=self.CODE_RESTRICTIVENESS.__getitem__,
            )
            aspects[f"S{signal_index:02d}"] = self.aspect_for_code(
                restrictive_code
            )

        return aspects

    def update_signal_status(self):
        """
        根据闭塞分区占用状态计算 S01/S02 显示。

        发车站的入口信号机由入口分区及其前方
        连续空闲分区数量决定：
        入口分区被占用时为红灯；
        入口分区空闲时，把入口分区本身计入空闲数，
        再按码序表换算灯色。

        反方向的出站信号机因方向不允许，固定红灯。
        """

        direction = self.tcc.get_direction()

        entry_track_code = self.get_entry_track_code()

        entry_track = self.track_circuits[
            entry_track_code
        ]

        departure_route = self.get_matching_departure_route()

        if entry_track.occupied or (
            self.route_service is not None and departure_route is None
        ):

            # 入口分区已被占用 -> 红灯
            entry_aspect = "红灯"

        else:
            if (
                departure_route is not None
                and departure_route.route_type == RouteType.SIDE_DEPART
            ):
                entry_aspect = "L灯"
            else:
                entry_aspect = self.get_aspect_by_code(entry_track.signal_code)

        if direction == "A_TO_B":

            s01_aspect = entry_aspect
            s02_aspect = "红灯"

        else:

            s01_aspect = "红灯"
            s02_aspect = entry_aspect

        self.signal_states["S01"] = s01_aspect
        self.signal_states["S02"] = s02_aspect

        return {
            "S01": s01_aspect,
            "S02": s02_aspect
        }

    def get_matching_departure_route(self):
        if self.route_service is None:
            return None
        direction = self.tcc.get_direction()
        departure_station = "A" if direction == "A_TO_B" else "B"
        if self.station_type != departure_station:
            return None
        for track in ("1G", "3G"):
            route = self.route_service.departure_route_for(
                departure_station,
                track,
            )
            if route is not None and route.state in (
                RouteState.ESTABLISHED,
                RouteState.LOCKED,
            ):
                return route
        return None

    def has_matching_departure_route(self):
        return self.get_matching_departure_route() is not None

    def has_matching_receive_route(self, track):
        if self.route_service is None:
            return False
        direction = self.tcc.get_direction()
        arrival_station = "B" if direction == "A_TO_B" else "A"
        return self.route_service.receive_route_for(
            arrival_station,
            track,
        ) is not None

    def has_any_matching_receive_route(self):
        return self.has_matching_receive_route("1G") or self.has_matching_receive_route("3G")

    def occupy_track(self, track_code):
        """
        模拟指定闭塞分区被列车占用。
        """

        track = self.track_circuits.get(track_code)

        if track is None:
            return False

        track.occupy()

        # =========================
        # 列车仿真状态
        # =========================

        # None表示列车目前还没有进入区间
        self.train_position = None

        # 初始化轨道编码
        self.update_all_track_codes()
        # 状态改变后重新计算所有轨道编码
        self.update_all_track_codes()

        return True

    def release_track(self, track_code):
        """
        模拟指定闭塞分区恢复空闲。
        """

        track = self.track_circuits.get(track_code)

        if track is None:
            return False

        track.release()

        # 状态改变后重新计算所有轨道编码
        self.update_all_track_codes()

        return True

    def get_all_track_status(self):

        result = []

        for code, track in self.track_circuits.items():
            result.append({

                "track_code": code,

                "status": track.get_status(),

                "signal_code": track.signal_code

            })

        return result
    def move_train_forward(self):
        """
        让区间内列车沿当前运行方向
        向前移动一个闭塞分区。

        返回：
        MOVED   - 正常移动
        ARRIVED - 已驶出区间
        NO_TRAIN - 当前区间没有列车
        BLOCKED - 下一分区被占用
        """

        # 当前没有列车
        if self.train_position is None:
            return "NO_TRAIN"

        running_order = self.get_running_order()

        current_index = running_order.index(
            self.train_position
        )

        current_track = self.track_circuits[
            self.train_position
        ]

        # =========================
        # 当前已经是最后一个分区
        # 下一步就是驶出区间
        # =========================

        if current_index == len(running_order) - 1:
            current_track.release()

            self.train_position = None

            self.update_all_track_codes()

            return "ARRIVED"

        # =========================
        # 获取下一个闭塞分区
        # =========================

        next_code = running_order[
            current_index + 1
            ]

        next_track = self.track_circuits[
            next_code
        ]

        # 下一分区占用，禁止进入
        if next_track.occupied:
            return "BLOCKED"

        # =========================
        # 列车移动
        # =========================

        current_track.release()

        next_track.occupy()

        self.train_position = next_code

        # 状态改变后重新计算编码
        self.update_all_track_codes()

        return "MOVED"

    def can_control_train(self):
        """
        判断当前车站是否拥有列车运行控制权。

        A_TO_B：A站控制
        B_TO_A：B站控制
        """

        direction = self.tcc.get_direction()

        if direction == "A_TO_B":
            return self.station_type == "A"

        if direction == "B_TO_A":
            return self.station_type == "B"

        return False

    def update_remote_signal(
            self,
            signal_code,
            signal_status
    ):
        """
        更新从邻站TCC收到的信号机状态。
        """

        if signal_code not in (
                "S01",
                "S02"
        ):
            return False

        self.signal_states[
            signal_code
        ] = signal_status

        return True

    # ==========================================
    # 区间改方
    # ==========================================
    def can_change_direction(self):
        """
        判断当前是否允许区间改方。

        条件：
        1. G01～G38全部空闲
        2. 区间内没有列车
        3. 本站信号机处于红灯
        """

        # -------------------------
        # 1. 检查全部闭塞分区
        # -------------------------

        for track in self.track_circuits.values():

            if track.occupied:
                return False

        # -------------------------
        # 2. 检查列车位置
        # -------------------------

        if self.train_position is not None:
            return False

        # -------------------------
        # 3. 检查本站信号
        # -------------------------

        if self.signal.get_aspect() != "红灯":
            return False

        return True

    def set_direction(self, direction):
        """
        设置区间运行方向。
        """

        if direction not in [
            "A_TO_B",
            "B_TO_A"
        ]:
            return False

        self.tcc.set_direction(direction)
        self.update_all_track_codes()

        # 改方时保持信号关闭
        self.signal.set_red()

        return True

    def get_direction(self):
        return self.tcc.get_direction()
