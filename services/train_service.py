from models.train import Train
from models.route import RouteState
from services.operation_policy import OperationPolicy, OperationRuleError
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

    def __init__(self, simulation_service, route_service=None):
        self.passive_balise_service = (
            PassiveBaliseService()
        )
        self.simulation = simulation_service
        self.route_service = route_service

        # 当前系统中的全部列车
        # {
        #     "T001": Train对象,
        #     "T002": Train对象
        # }
        self.trains = {}
        # 待发列车队列
        self.waiting_queue = []
        # 只有用户在“查看列车”中选中并点击开始的列车才允许自动发车
        self.dispatch_target_id = None

        # 用户执行全局暂停后，即使误触发一次更新周期也不得自动恢复列车。
        self.globally_paused = False

        # 下一辆列车编号
        self.next_train_number = 1

        # 默认闭塞分区长度
        self.default_track_length = 1000.0

    # ==================================================
    # 创建列车
    # ==================================================

    def create_train(self, departure_mode=None, arrival_mode=None):

        train_id = f"T{self.next_train_number:03d}"

        self.next_train_number += 1

        direction = self.simulation.get_direction()

        train = Train(
            train_id,
            direction,
            departure_mode,
            arrival_mode,
        )

        self.trains[train_id] = train

        return train

    # ==================================================
    # 获取运行方向对应的闭塞分区顺序
    # ==================================================

    def get_track_order(self, direction):
        order = list(self.simulation.track_circuits.keys())
        return order if direction == "A_TO_B" else list(reversed(order))

    # ==================================================
    # 判断入口分区
    # ==================================================

    def get_entrance_track(self, direction):

        if direction == "A_TO_B":
            return "G01"

        return "G38"

    def clear_all_trains(self):
        """清除运行及待发列车，并释放由列车造成的区段占用。"""
        self.trains.clear()
        self.waiting_queue.clear()
        self.dispatch_target_id = None
        self.sync_track_circuits()

    def prepare_train_for_dispatch(
        self,
        train_id,
        departure_mode,
        arrival_mode,
    ):
        train = self.trains.get(train_id)
        if train is None or train.status != "WAITING":
            raise ValueError("所选列车不是待发列车")
        if train_id not in self.waiting_queue:
            self.waiting_queue.append(train_id)
        train.configure_operation_modes(departure_mode, arrival_mode)
        self.dispatch_target_id = train_id
        return train

    def dispatch_selected_train(
        self,
        train_id,
        departure_mode,
        arrival_mode,
        max_speed,
    ):
        """校验并立即发出用户明确选中的一辆待发列车。"""
        train = self.trains.get(train_id)
        if train is None:
            raise OperationRuleError(
                "没有选中有效列车",
                f"列车编号 {train_id or '为空'} 不存在。",
                "请在“查看列车”中选择一辆待发列车后重试。",
            )
        if train.status != "WAITING":
            raise OperationRuleError(
                f"列车{train_id}不能重复发车",
                f"列车当前状态为 {train.status}。",
                "请选择状态为待发的列车；如需重新发车，请先执行复位。",
            )
        if train_id not in self.waiting_queue:
            raise OperationRuleError(
                f"列车{train_id}不在待发队列",
                "列车状态与待发队列不一致。",
                "请复位该列车或重新添加待发列车后重试。",
            )

        OperationPolicy.validate_train_routes(
            train.direction,
            train_id,
            departure_mode,
            arrival_mode,
            self.route_service,
        )
        try:
            requested_speed = float(max_speed)
        except (TypeError, ValueError):
            requested_speed = -1.0
        if requested_speed not in Train.ALLOWED_MAX_SPEEDS:
            allowed = "、".join(str(value) for value in Train.ALLOWED_MAX_SPEEDS)
            raise OperationRuleError(
                f"列车{train_id}的最大速度无效",
                f"请求值为 {max_speed} km/h。",
                f"请选择 {allowed} km/h 中的一个固定速度。",
            )

        departure_station = self.get_departure_station(train.direction)
        arrival_station = self.get_arrival_station(train.direction)
        departure_track = self.mode_to_track(departure_mode)
        arrival_track = self.mode_to_track(arrival_mode)
        departure_route = self.route_service.departure_route_for(
            departure_station,
            departure_track,
        )
        receive_route = self.route_service.receive_route_for(
            arrival_station,
            arrival_track,
        )
        for route, movement in (
            (departure_route, "发车"),
            (receive_route, "接车"),
        ):
            if route.state == RouteState.LOCKED and route.train_id != train_id:
                raise OperationRuleError(
                    f"列车{train_id}使用的{movement}进路已被占用",
                    f"{route.station}站{route.display_name}正由列车"
                    f"{route.train_id}锁闭。",
                    "请等待前车通过并解除进路锁闭后重试。",
                )

        blocker = self._dispatch_spacing_blocker(train)
        if blocker is not None:
            raise blocker

        train.configure_operation_modes(departure_mode, arrival_mode)
        train.set_max_speed(requested_speed)
        if not self.dispatch_train(train):
            raise OperationRuleError(
                f"列车{train_id}未能发车",
                "发车条件在提交时发生变化。",
                "请检查入口区段和进路状态后重试。",
            )
        self.waiting_queue.remove(train_id)
        self.sync_track_circuits()
        self.update_train_speed_limit(train)
        return train

    def get_dispatch_blocker(self, train):
        if train is None:
            return OperationRuleError(
                "没有选中有效列车",
                "当前列车对象为空。",
                "请先选择一辆待发列车。",
            )
        return self._dispatch_spacing_blocker(train)

    def _dispatch_spacing_blocker(self, train):
        order = self.get_track_order(train.direction)
        entrance_track = order[0]
        occupying_train = next(
            (
                other
                for other in self.trains.values()
                if other.train_id != train.train_id
                and other.status in ("RUNNING", "STOPPED")
                and other.current_track == entrance_track
            ),
            None,
        )
        if occupying_train is not None:
            return OperationRuleError(
                f"列车{train.train_id}的出发入口被占用",
                f"列车{occupying_train.train_id}仍在入口区段{entrance_track}。",
                "请等待前车驶离入口并形成两个完整轨道区段的间隔后重试。",
            )

        nearest_train = None
        nearest_index = None
        for other in self.trains.values():
            if (
                other.train_id == train.train_id
                or other.direction != train.direction
                or other.status not in ("RUNNING", "STOPPED")
                or other.current_track not in order
            ):
                continue
            index = order.index(other.current_track)
            if nearest_index is None or index < nearest_index:
                nearest_train = other
                nearest_index = index
        if nearest_train is not None and nearest_index < 2:
            return OperationRuleError(
                f"列车{train.train_id}与前车间隔不足",
                f"前车{nearest_train.train_id}位于{nearest_train.current_track}，"
                "尚未越过第三个区段。",
                "请等待前车前进，入口后保留两个完整轨道区段后重试。",
            )
        return None

    def pause_all(self):
        self.globally_paused = True
        paused = []
        for train in self.trains.values():
            if train.status == "RUNNING":
                train.status = "STOPPED"
                paused.append(train)
        return paused

    def resume_all(self):
        self.globally_paused = False
        resumed = []
        for train in self.trains.values():
            if train.status == "STOPPED":
                train.status = "RUNNING"
                self.update_train_speed_limit(train)
                resumed.append(train)
        return resumed

    def reset_dispatched_trains(self):
        reset = [
            train
            for train in self.trains.values()
            if train.status in ("RUNNING", "STOPPED", "ARRIVED")
        ]
        for train in reset:
            if self.route_service is not None:
                self.route_service.unlock_routes_for_train(train.train_id)
            train.reset_to_departure(preserve_configuration=True)
            if train.train_id not in self.waiting_queue:
                self.waiting_queue.append(train.train_id)
        self.dispatch_target_id = None
        self.globally_paused = True
        self.sync_track_circuits()
        return reset

    def reset_train_to_departure(self, train_id):
        train = self.trains.get(train_id)
        if train is None:
            return None
        train.reset_to_departure()
        if train_id not in self.waiting_queue:
            self.waiting_queue.append(train_id)
        if self.dispatch_target_id == train_id:
            self.dispatch_target_id = None
        self.sync_track_circuits()
        return train

    # ==================================================
    # 判断某分区是否被列车占用
    # ==================================================

    def is_track_occupied_by_train(self, track_code):

        for train in self.trains.values():

            if (
                train.status in ("RUNNING", "STOPPED")
                and train.current_track == track_code
            ):
                return True

        return False

    # ==================================================
    # 发车
    # ==================================================

    def dispatch_train(self, train):
        if not self.can_dispatch_new_train(
                train.direction,
                train.departure_mode,
        ):
            return False
        departure_route = self.get_matching_departure_route(train)
        entrance_track = self.get_entrance_track(
            train.direction
        )
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
        if departure_route is not None:
            self.route_service.lock_route(
                departure_route.route_id,
                train.train_id,
            )
            train.route_id = departure_route.route_id
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
            self.release_train_route(train)
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
        current_track = train.current_track
        train.current_track = next_track

        train.position = remaining_distance
        order = self.get_track_order(train.direction)
        if current_track == order[0] and next_track == order[1]:
            self.release_train_route(train)
        if next_track == order[-1]:
            self.lock_matching_receive_route(train)
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

        if self.globally_paused:
            self.sync_track_circuits()
            return None

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

        snapshot = self.build_movement_snapshot()
        running_trains = [
            train
            for train in self.trains.values()
            if train.status == "RUNNING"
        ]
        running_trains.sort(
            key=lambda train: snapshot[train.train_id]["absolute_position"],
            reverse=True,
        )

        for train in running_trains:
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

    def can_dispatch_new_train(self, direction, departure_mode="MAIN"):
        """
        判断当前是否满足下一列车发车条件。

        简化规则：
        前车至少进入第3个闭塞分区，
        才允许下一列车进入入口分区。
        """

        if self.route_service is not None:
            departure_station = self.get_departure_station(direction)
            station_track = self.mode_to_track(departure_mode)
            route = self.route_service.departure_route_for(
                departure_station,
                station_track,
            )
            if route is None or route.state != RouteState.ESTABLISHED:
                return False

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

    def add_waiting_train(self, departure_mode=None, arrival_mode=None):
        """
        创建一辆列车，并加入待发队列。
        """

        train = self.create_train(departure_mode, arrival_mode)

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

        if not self.waiting_queue or self.dispatch_target_id is None:
            return None

        train_id = self.dispatch_target_id

        if train_id not in self.waiting_queue:
            self.dispatch_target_id = None
            return None

        train = self.trains.get(
            train_id
        )

        if train is None:
            self.waiting_queue.remove(train_id)
            self.dispatch_target_id = None
            return None

        # 判断是否满足安全发车条件
        if not self.can_dispatch_new_train(
                train.direction,
                train.departure_mode,
        ):
            return None

        # 正式发车
        result = self.dispatch_train(
            train
        )

        if not result:
            return None

        # 从待发队列删除
        self.waiting_queue.remove(train_id)
        self.dispatch_target_id = None

        return train

    @staticmethod
    def mode_to_track(mode):
        if mode not in ("MAIN", "SIDE"):
            raise ValueError("非法接发车方式")
        return "1G" if mode == "MAIN" else "3G"

    @staticmethod
    def get_departure_station(direction):
        return "A" if direction == "A_TO_B" else "B"

    @staticmethod
    def get_arrival_station(direction):
        return "B" if direction == "A_TO_B" else "A"

    def get_matching_departure_route(self, train):
        if self.route_service is None:
            return None
        return self.route_service.departure_route_for(
            self.get_departure_station(train.direction),
            train.station_track,
        )

    def lock_matching_receive_route(self, train):
        if self.route_service is None:
            return None
        route = self.route_service.receive_route_for(
            self.get_arrival_station(train.direction),
            train.arrival_track,
        )
        if route is None or route.state != RouteState.ESTABLISHED:
            return None
        self.route_service.lock_route(route.route_id, train.train_id)
        train.route_id = route.route_id
        return route

    def release_train_route(self, train):
        if self.route_service is not None and train.route_id is not None:
            self.route_service.unlock_route(train.route_id)
        train.route_id = None

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

        order = self.get_track_order(train.direction)
        if train.current_track not in order:
            return None

        return (
            order.index(train.current_track) * self.default_track_length
            + train.position
        )

    def build_movement_snapshot(self):
        """冻结本周期全部活动列车的位置，供统一排序和安全判断。"""
        snapshot = {}
        for train in self.trains.values():
            if train.status not in ("RUNNING", "STOPPED"):
                continue
            absolute_position = self.get_absolute_position(train)
            if absolute_position is None:
                continue
            snapshot[train.train_id] = {
                "track": train.current_track,
                "position": train.position,
                "absolute_position": absolute_position,
                "status": train.status,
                "direction": train.direction,
            }
        return snapshot

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
