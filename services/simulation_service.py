from models.tcc import TCC
from models.track_circuit import TrackCircuit
from models.signal import Signal
from models.balise import Balise


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
        "L3": "绿灯",
        "L2": "绿灯",
        "L": "绿灯",
        "LU": "黄绿灯",
        "U": "黄灯",
        "HU": "红灯"
    }

    def __init__(self, station_type):

        self.station_type = station_type

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
        # 3. 创建8个闭塞分区
        # =========================

        self.track_circuits = {}

        for i in range(1, 9):
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

        # 初始化全部闭塞分区编码
        self.update_all_track_codes()

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
        更新G01～G08状态和列车位置。
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
        for code in running_order[
                    current_index + 1:
                    ]:

            track = self.track_circuits[
                code
            ]

            # 遇到占用立即停止
            if track.occupied:
                break

            free_count += 1

        return free_count

    def update_all_track_codes(self):
        """
        根据当前运行方向和各闭塞分区占用状态，
        更新全部轨道电路编码。
        """

        for track_code, track in self.track_circuits.items():

            # 当前分区本身被列车占用时，
            # 本仿真统一显示HU
            if track.occupied:
                track.set_track_code(
                    "HU"
                )

                continue

            # 计算前方连续空闲数量
            free_count = (
                self.count_forward_free_tracks(
                    track_code
                )
            )

            # 根据空闲数量计算编码
            code = self.calculate_track_code(
                free_count
            )

            track.set_track_code(
                code
            )

        # 码序变化后立即联动信号机
        self.update_signal_status()

    # ==========================================
    # 信号机自动联动
    # ==========================================

    def get_aspect_by_code(self, code):
        """
        根据自动闭塞码序得到信号机灯色。
        """

        return self.CODE_ASPECTS.get(
            code,
            "红灯"
        )

    def get_entry_track_code(self):
        """
        返回当前运行方向上的入口闭塞分区编号。
        """

        if self.tcc.get_direction() == "A_TO_B":
            return "G01"

        return "G08"

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

        if entry_track.occupied:

            # 入口分区已被占用 -> 红灯
            entry_aspect = "红灯"

        else:

            # 入口分区空闲，
            # 再统计其前方连续空闲分区，
            # 两者合计决定灯色
            free_count = (
                    self.count_forward_free_tracks(
                        entry_track_code
                    )
                    + 1
            )

            entry_aspect = self.get_aspect_by_code(
                self.calculate_track_code(
                    free_count
                )
            )

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
        1. G01～G08全部空闲
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
