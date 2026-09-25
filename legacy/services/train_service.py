from models.train import Train
from services.passive_balise_service import PassiveBaliseService

class TrainService:
    """
    负责多列车创建、发车、自动运行和跨闭塞分区。
    """
    # ==========================================
    # 自动闭塞码序对应的仿真速度约束
    # ==========================================
    SAFETY_MARGIN = 300.0
    BLOCK_SPEED_LIMITS = {
        "L5": 120.0,
        "L3": 120.0,
        "L2": 110.0,
        "L": 100.0,
        "LU": 80.0,
        "U": 45.0,
        "HU": 0.0
    }

    def __init__(self, simulation_service):
        self.passive_balise_service = (
            PassiveBaliseService()
        )
        self.simulation = simulation_service

        # 当前系统中的全部列车
        # {
        #     "T001": Train对象,
        #     "T002": Train对象
        # }
        self.trains = {}
        # 待发列车队列
        self.waiting_queue = []

        # 下一辆列车编号
        self.next_train_number = 1

        # 默认闭塞分区长度
        self.default_track_length = 1000.0

    # ==================================================
    # 创建列车
    # ==================================================

    def create_train(self):

        train_id = f"T{self.next_train_number:03d}"

        self.next_train_number += 1

        direction = self.simulation.get_direction()

        train = Train(
            train_id,
            direction
        )

        self.trains[train_id] = train

        return train

    # ==================================================
    # 获取运行方向对应的闭塞分区顺序
    # ==================================================

    def get_track_order(self, direction):

        if direction == "A_TO_B":
            return [
                "G01", "G02", "G03", "G04",
                "G05", "G06", "G07", "G08"
            ]

        return [
            "G08", "G07", "G06", "G05",
            "G04", "G03", "G02", "G01"
        ]

    # ==================================================
    # 判断入口分区
    # ==================================================

    def get_entrance_track(self, direction):

        if direction == "A_TO_B":
            return "G01"

        return "G08"

    # ==================================================
    # 判断某分区是否被列车占用
    # ==================================================

    def is_track_occupied_by_train(self, track_code):

        for train in self.trains.values():

            if (
                train.status == "RUNNING"
                and train.current_track == track_code
            ):
                return True

        return False

    # ==================================================
    # 发车
    # ==================================================

    def dispatch_train(self, train):
        if not self.can_dispatch_new_train(
                train.direction
        ):
            return False
        entrance_track = self.get_entrance_track(
            train.direction
        )
        train.max_speed = 120.0
        train.block_speed = 120.0
        train.line_speed = 120.0
        train.active_balise_speed = 120.0
        train.temporary_speed = 120.0
        train.enter_track(
            entrance_track
        )
        self.read_passive_balise(
            train,
            entrance_track
        )
        train.calculate_target_speed()
        return True
    # ==================================================
    # 获取下一闭塞分区
    # ==================================================

    def get_next_track(self, train):

        order = self.get_track_order(
            train.direction
        )

        if train.current_track not in order:
            return None

        index = order.index(
            train.current_track
        )

        # 当前已经是最后一个闭塞分区
        if index == len(order) - 1:
            return None

        return order[index + 1]

    # ==================================================
    # 单列车跨区判断
    # ==================================================

    def handle_track_transition(self, train):

        # 当前分区还没有跑完
        if train.position < self.default_track_length:
            return

        # 超过分区边界的距离
        remaining_distance = (
            train.position
            - self.default_track_length
        )

        next_track = self.get_next_track(
            train
        )

        # 没有下一分区
        # 说明已经驶出整个区间
        if next_track is None:

            train.leave_section()

            return

        # 下一分区被其他列车占用
        if self.is_track_occupied_by_train(
            next_track
        ):
            # 暂时停在当前分区末端
            train.position = (
                self.default_track_length - 0.1
            )

            train.speed = 0.0
            train.target_speed = 0.0

            train.status = "STOPPED"

            return

        # 正常进入下一闭塞分区
        train.current_track = next_track

        train.position = remaining_distance
        self.read_passive_balise(
            train,
            train.current_track
        )

    # ==================================================
    # 更新一辆列车
    # ==================================================

    def update_train(self, train, delta_time):

        if train.status != "RUNNING":
            return

        # ----------------------------------
        # HU时：
        # 当前分区末端作为停车边界
        # ----------------------------------

        if train.block_code == "HU":
            train.target_speed = 0.0

        # 正常运动
        train.update(
            delta_time
        )

        # 跨区判断
        self.handle_track_transition(
            train
        )

    # ==================================================
    # 更新所有列车
    # ==================================================

    def update_all(self, delta_time):

        # ==========================================
        # 1. 根据当前列车位置同步轨道状态
        # ==========================================

        self.sync_track_circuits()

        # ==========================================
        # 2. 尝试恢复之前停车的列车
        # ==========================================

        self.try_resume_stopped_trains()

        # ==========================================
        # 3. 根据最新自动闭塞码序
        #    更新每辆列车速度限制
        # ==========================================

        for train in self.trains.values():

            if train.status in (
                    "RUNNING",
                    "STOPPED"
            ):
                self.update_train_speed_limit(
                    train
                )

        # ==========================================
        # 4. 所有列车按照新的目标速度运动
        # ==========================================

        for train in list(
                self.trains.values()
        ):
            self.update_train(
                train,
                delta_time
            )

        # ==========================================
        # 5. 移动以后重新同步轨道状态
        # ==========================================

        self.sync_track_circuits()

        # ==========================================
        # 6. 判断是否可以自动发送下一辆列车
        # ==========================================

        dispatched_train = (
            self.try_auto_dispatch()
        )

        if dispatched_train is not None:
            self.sync_track_circuits()

            # 新列车进入以后立即计算一次速度约束
            self.update_train_speed_limit(
                dispatched_train
            )

        return dispatched_train

    # ==================================================
    # 获取所有列车状态
    # ==================================================

    def get_all_train_status(self):

        return [
            train.get_status()
            for train in self.trains.values()
        ]
    def sync_track_circuits(self):
        """
        根据所有列车位置同步轨道电路占用状态。
        """

        # 先释放所有闭塞分区
        for track in self.simulation.track_circuits.values():
            track.release()

        # 再根据运行中的列车重新占用
        for train in self.trains.values():

            if (
                train.status in ("RUNNING", "STOPPED")
                and train.current_track is not None
            ):

                track = self.simulation.track_circuits.get(
                    train.current_track
                )

                if track is not None:
                    track.occupy()

        # 重新计算L5/L3/L2/L/LU/U/HU
        self.simulation.update_all_track_codes()

    def can_dispatch_new_train(self, direction):
        """
        判断当前是否满足下一列车发车条件。

        简化规则：
        前车至少进入第3个闭塞分区，
        才允许下一列车进入入口分区。
        """

        order = self.get_track_order(
            direction
        )

        entrance_track = order[0]

        # 入口分区本身必须空闲
        if self.is_track_occupied_by_train(
            entrance_track
        ):
            return False

        running_trains = []

        for train in self.trains.values():

            if (
                train.direction == direction
                and train.status in (
                    "RUNNING",
                    "STOPPED"
                )
            ):
                running_trains.append(
                    train
                )

        # 区间没有列车
        if not running_trains:
            return True

        # 找到距离入口最近的列车
        nearest_index = None

        for train in running_trains:

            if train.current_track not in order:
                continue

            index = order.index(
                train.current_track
            )

            if (
                nearest_index is None
                or index < nearest_index
            ):
                nearest_index = index

        if nearest_index is None:
            return True

        # index:
        # G01 = 0
        # G02 = 1
        # G03 = 2
        #
        # 到G03及以后才允许下一列车发车
        return nearest_index >= 2
    def should_entry_signal_open(self, direction):
        """
        根据自动闭塞条件判断进站端发车信号是否允许开放。
        """

        return self.can_dispatch_new_train(
            direction
        )

    def add_waiting_train(self):
        """
        创建一辆列车，并加入待发队列。
        """

        train = self.create_train()

        self.waiting_queue.append(
            train.train_id
        )

        return train

    def try_auto_dispatch(self):
        """
        检查待发队列。

        如果满足自动闭塞发车条件，
        自动发送队首列车。
        """

        if not self.waiting_queue:
            return None

        train_id = self.waiting_queue[0]

        train = self.trains.get(
            train_id
        )

        if train is None:
            self.waiting_queue.pop(0)
            return None

        # 判断是否满足安全发车条件
        if not self.can_dispatch_new_train(
                train.direction
        ):
            return None

        # 正式发车
        result = self.dispatch_train(
            train
        )

        if not result:
            return None

        # 从待发队列删除
        self.waiting_queue.pop(0)

        return train

    def get_entry_signal_status(self):
        """
        根据当前运行方向和自动闭塞状态，
        返回入口信号机状态。
        """

        direction = self.simulation.get_direction()

        can_dispatch = self.can_dispatch_new_train(
            direction
        )

        if can_dispatch:
            return "绿灯"

        return "红灯"

    def try_resume_stopped_trains(self):
        """
        当前方闭塞分区重新空闲时，
        允许停车列车恢复运行。
        """

        for train in self.trains.values():

            if train.status != "STOPPED":
                continue

            next_track = self.get_next_track(
                train
            )

            if next_track is None:
                continue

            if not self.is_track_occupied_by_train(
                    next_track
            ):
                train.status = "RUNNING"

                # 暂时恢复到120km/h目标速度
                # 后面会由自动闭塞码序和应答器
                # 决定真正目标速度
                train.status = "RUNNING"

                self.update_train_speed_limit(
                    train
                )

    def get_free_sections_ahead(self, train):
        """
        计算列车前方连续空闲的闭塞分区数量。

        注意：
        不把列车自己当前占用的分区计算进去。
        """

        if train.current_track is None:
            return 0

        order = self.get_track_order(
            train.direction
        )

        if train.current_track not in order:
            return 0

        current_index = order.index(
            train.current_track
        )

        free_count = 0

        # 从当前列车的下一个分区开始检查
        for track_code in order[
                          current_index + 1:
                          ]:

            if self.is_track_occupied_by_train(
                    track_code
            ):
                break

            free_count += 1

        return free_count

    def calculate_train_block_code(self, train):
        """
        根据前方连续空闲分区数量，
        计算当前列车的追踪运行码序。

        前方有列车时，统计两车之间的空闲分区；
        前方没有列车时，统计到线路终点为止的空闲分区。
        """

        # ----------------------------------
        # 1. 找前车
        # ----------------------------------

        train_ahead = self.find_train_ahead(
            train
        )

        # ----------------------------------
        # 2. 获取运行方向上的分区顺序
        # ----------------------------------

        order = self.get_track_order(
            train.direction
        )

        if train.current_track not in order:
            return "L5"

        current_index = order.index(
            train.current_track
        )

        # ----------------------------------
        # 3. 前方连续空闲分区数量
        # ----------------------------------

        if train_ahead is None:

            # 前方没有列车时，
            # 直接统计到线路终点为止的空闲分区
            free_count = (
                    len(order)
                    - current_index
                    - 1
            )

        else:

            ahead_index = order.index(
                train_ahead.current_track
            )

            # 两辆列车之间完整空闲分区数量
            free_count = (
                    ahead_index
                    - current_index
                    - 1
            )

        # 列车已进入运行方向上的最后一个分区。
        # 该分区后面不再有分区，按分区表会算成HU，
        # 但列车需要驶出区间，必须留出放行余量，
        # 否则会被HU压到0km/h永久停在区间内。
        if (
                free_count == 0
                and current_index == len(order) - 1
        ):
            free_count = 1

        # ----------------------------------
        # 4. 生成码序
        # ----------------------------------

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

    def update_train_speed_limit(self, train):

        if train.current_track is None:
            return

        # ==================================
        # 1. 自动闭塞码序
        # ==================================

        block_code = (
            self.calculate_train_block_code(
                train
            )
        )

        train.block_code = block_code

        train.block_speed = (
            self.BLOCK_SPEED_LIMITS.get(
                block_code,
                120.0
            )
        )

        # ==================================
        # 2. 实际安全距离
        # ==================================

        safety = (
            self.get_safety_status(
                train
            )
        )

        train.distance_to_ahead = (
            safety["distance"]
        )

        train.braking_distance = (
            safety["braking_distance"]
        )

        train.safety_status = (
            safety["status"]
        )

        # ==================================
        # 3. 危险情况下进一步限制
        # ==================================

        if safety["status"] == "DANGER":

            # 要求停车
            train.block_speed = 0.0

        elif safety["status"] == "WARNING":

            # 预警区进一步限制
            train.block_speed = min(
                train.block_speed,
                45.0
            )

        # ==================================
        # 4. 综合目标速度
        # ==================================

        train.calculate_target_speed()
        # 根据下一分区限速，
        # 判断是否需要提前制动
        self.update_upcoming_speed_limit(
            train
        )

    def find_train_ahead(self, train):
        """
        查找当前列车前方最近的一辆列车。

        没有前车返回None。
        """

        if train.current_track is None:
            return None

        order = self.get_track_order(
            train.direction
        )

        if train.current_track not in order:
            return None

        current_index = order.index(
            train.current_track
        )

        nearest_train = None
        nearest_index = None

        for other in self.trains.values():

            # 不能把自己当成前车
            if other.train_id == train.train_id:
                continue

            if other.status not in (
                    "RUNNING",
                    "STOPPED"
            ):
                continue

            # 只考虑同方向列车
            if other.direction != train.direction:
                continue

            if other.current_track not in order:
                continue

            other_index = order.index(
                other.current_track
            )

            # 必须真的在当前列车前方
            if other_index <= current_index:
                continue

            if (
                    nearest_index is None
                    or other_index < nearest_index
            ):
                nearest_index = other_index
                nearest_train = other

        return nearest_train

    def get_absolute_position(self, train):
        """
        把“所在闭塞分区 + 分区内位置”
        转换成整条区间上的绝对位置。

        每个闭塞分区暂按1000m计算。
        """

        if train.current_track is None:
            return None

        try:
            track_number = int(
                train.current_track[1:]
            )
        except ValueError:
            return None

        if train.direction == "A_TO_B":

            return (
                    (track_number - 1) * 1000.0
                    + train.position
            )

        else:

            return (
                    (8 - track_number) * 1000.0
                    + train.position
            )

    def get_distance_to_train_ahead(self, train):
        """
        返回当前列车与前方最近列车之间的实际距离。

        没有前车返回None。
        """

        train_ahead = self.find_train_ahead(
            train
        )

        if train_ahead is None:
            return None

        current_position = (
            self.get_absolute_position(
                train
            )
        )

        ahead_position = (
            self.get_absolute_position(
                train_ahead
            )
        )

        if (
                current_position is None
                or ahead_position is None
        ):
            return None

        return max(
            0.0,
            ahead_position - current_position
        )

    def calculate_braking_distance(self, train):
        """
        根据当前速度估算制动距离。

        s = v² / (2a)

        speed单位：km/h
        转换成m/s后计算。
        """

        speed_ms = (
                train.speed / 3.6
        )

        # 仿真使用的制动减速度
        deceleration = 0.8

        if hasattr(
                train,
                "deceleration"
        ):
            deceleration = (
                train.deceleration
            )

        if deceleration <= 0:
            deceleration = 0.8

        braking_distance = (
                speed_ms ** 2
                / (2 * deceleration)
        )

        return braking_distance

    def get_safety_status(self, train):

        distance = (
            self.get_distance_to_train_ahead(
                train
            )
        )

        # 没有前车
        if distance is None:
            return {
                "distance": None,
                "braking_distance": 0.0,
                "required_distance": 0.0,
                "status": "CLEAR"
            }

        braking_distance = (
            self.calculate_braking_distance(
                train
            )
        )

        required_distance = (
                braking_distance
                + self.SAFETY_MARGIN
        )

        if distance <= required_distance:

            status = "DANGER"

        elif distance <= (
                required_distance + 500
        ):

            status = "WARNING"

        else:

            status = "SAFE"

        return {
            "distance": distance,
            "braking_distance": braking_distance,
            "required_distance": required_distance,
            "status": status
        }

    def read_passive_balise(
            self,
            train,
            track_code
    ):

        balise = (
            self.passive_balise_service
            .get_balise_by_track(
                track_code
            )
        )

        if balise is None:
            return None

        # 防止在同一个分区内
        # 每100ms重复读取
        if (
                train.last_balise
                == balise.balise_id
        ):
            return None

        message = (
            balise.get_message()
        )

        train.last_balise = (
            balise.balise_id
        )

        # 更新线路固定限速
        train.line_speed = (
            message["line_speed"]
        )

        train.next_track = message.get(
            "next_track"
        )

        train.next_line_speed = message.get(
            "next_speed"
        )

        # 重新计算最终目标速度
        train.calculate_target_speed()

        next_info = ""

        if train.next_track is not None:
            next_info = (
                f" | 前方 {train.next_track} "
                f"限速 {train.next_line_speed:.0f}km/h"
            )

        print(
            f"[应答器] "
            f"{train.train_id} "
            f"读取 {balise.balise_id} | "
            f"{track_code} | "
            f"当前限速 "
            f"{balise.line_speed:.0f}km/h"
            f"{next_info}"
        )

        return message

    def calculate_speed_change_distance(
            self,
            current_speed,
            target_speed,
            deceleration=0.8
    ):
        """
        计算从current_speed降到target_speed
        所需要的理论制动距离。

        s = (v1² - v2²) / (2a)
        """

        if current_speed <= target_speed:
            return 0.0

        v1 = current_speed / 3.6
        v2 = target_speed / 3.6

        distance = (
                (v1 ** 2 - v2 ** 2)
                / (2 * deceleration)
        )

        return max(
            0.0,
            distance
        )

    def update_upcoming_speed_limit(
            self,
            train
    ):

        # 没有下一分区信息
        if train.next_line_speed is None:
            return

        # 下一分区速度没有更低
        # 不需要提前制动
        if (
                train.next_line_speed
                >= train.line_speed
        ):
            return

        # 当前分区还剩多少米
        distance_to_boundary = (
                1000.0 - train.position
        )

        # 从当前实际速度降到
        # 下一分区限速需要多少距离
        braking_distance = (
            self.calculate_speed_change_distance(
                train.speed,
                train.next_line_speed,
                train.deceleration
            )
        )

        # 增加一个预留距离
        reserve_distance = 100.0

        start_braking_distance = (
                braking_distance
                + reserve_distance
        )

        # 已经进入应开始制动的位置
        if (
                distance_to_boundary
                <= start_braking_distance
        ):
            train.line_speed = min(
                train.line_speed,
                train.next_line_speed
            )

            train.calculate_target_speed()