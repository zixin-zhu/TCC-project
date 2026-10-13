class Train:

    ALLOWED_MAX_SPEEDS = (80, 120, 160, 200, 250, 300, 350)

    def __init__(
        self,
        train_id,
        direction="A_TO_B",
        departure_mode=None,
        arrival_mode=None,
    ):
        self.train_id = train_id

        self.direction = direction

        self.departure_mode = None
        self.arrival_mode = None
        self.station_track = None
        self.arrival_track = None
        self.departure_route_id = None
        self.receive_route_id = None
        self.receive_waiting_reason = None
        self.stop_signal_id = None
        self.movement_phase = "WAITING"
        self.station_position = None
        self.receive_throat_cleared = False
        if departure_mode is not None:
            self.configure_operation_modes(
                departure_mode,
                arrival_mode or departure_mode,
            )
        self.route_id = None

        self.current_track = None

        self.position = 0.0

        self.speed = 0.0

        self.target_speed = 0.0
        # ==========================================
        # 各类速度约束
        # ==========================================

        # 列车自身/线路最高允许速度
        self.max_speed = 120.0

        # 自动闭塞码序对应的速度限制
        self.block_speed = 120.0

        # 无源应答器提供的线路固定限速
        # 这一轮暂时统一120，下一阶段正式使用
        self.line_speed = 120.0

        # 有源应答器/TCC动态速度限制
        # 这一轮先预留
        self.active_balise_speed = 120.0

        # 临时限速
        self.temporary_speed = 120.0

        # 当前轨道电路码序
        self.block_code = "L5"

        self.acceleration = 0.5

        self.deceleration = 0.8

        self.status = "WAITING"

        # 与前车距离
        self.distance_to_ahead = None

        # 当前估算制动距离
        self.braking_distance = 0.0

        # CLEAR / SAFE / WARNING / DANGER
        self.safety_status = "CLEAR"

        # 最后读取的应答器
        self.last_balise = None

        # 下一分区
        self.next_track = None

        # 下一分区线路限速
        self.next_line_speed = None

    def configure_operation_modes(self, departure_mode, arrival_mode=None):
        if departure_mode not in ("MAIN", "SIDE"):
            raise ValueError("非法发车方式")
        if arrival_mode is not None and arrival_mode not in ("MAIN", "SIDE"):
            raise ValueError("非法接车方式")
        self.departure_mode = departure_mode
        self.arrival_mode = arrival_mode
        self.station_track = "1G" if departure_mode == "MAIN" else "3G"
        self.arrival_track = (
            "1G" if arrival_mode == "MAIN" else
            "3G" if arrival_mode == "SIDE" else None
        )

    def configure_departure_route(self, route_id, track):
        self.departure_route_id = route_id
        self.departure_mode = "MAIN" if track == "1G" else "SIDE"
        self.station_track = track

    def configure_receive_route(self, route_id, track):
        self.receive_route_id = route_id
        self.arrival_mode = "MAIN" if track == "1G" else "SIDE"
        self.arrival_track = track
        self.receive_waiting_reason = None

    def set_max_speed(self, speed):
        speed = float(speed)
        if speed not in self.ALLOWED_MAX_SPEEDS:
            allowed = "、".join(str(value) for value in self.ALLOWED_MAX_SPEEDS)
            raise ValueError(
                f"最大速度 {speed:g} km/h 不可用，允许值为 {allowed} km/h"
            )
        self.max_speed = speed

    def reset_to_departure(self, preserve_configuration=True):
        departure_mode = self.departure_mode
        arrival_mode = self.arrival_mode
        max_speed = self.max_speed
        self.current_track = None
        self.position = 0.0
        self.speed = 0.0
        self.target_speed = 0.0
        self.status = "WAITING"
        self.route_id = None
        self.departure_route_id = None
        self.receive_route_id = None
        self.receive_waiting_reason = None
        self.stop_signal_id = None
        self.movement_phase = "WAITING"
        self.station_position = None
        self.receive_throat_cleared = False
        self.max_speed = max_speed
        self.block_speed = 120.0
        self.line_speed = 120.0
        self.active_balise_speed = 120.0
        self.temporary_speed = 120.0
        self.block_code = "L5"
        if preserve_configuration:
            self.departure_mode = departure_mode
            self.arrival_mode = arrival_mode
            self.station_track = "1G" if departure_mode == "MAIN" else (
                "3G" if departure_mode == "SIDE" else None
            )
            self.arrival_track = "1G" if arrival_mode == "MAIN" else (
                "3G" if arrival_mode == "SIDE" else None
            )
        else:
            self.departure_mode = None
            self.arrival_mode = None
            self.station_track = None
            self.arrival_track = None
        self.last_balise = None
        self.next_track = None
        self.next_line_speed = None
        self.distance_to_ahead = None
        self.braking_distance = 0.0
        self.safety_status = "CLEAR"


    def enter_track(self, track_code):

        self.current_track = track_code

        self.position = 0.0

        self.status = "RUNNING"
        self.movement_phase = "INTERVAL_RUNNING"
        self.stop_signal_id = None

    def enter_departure(self, route_id, track, initial_position=0.0):
        """从站内待发点进入发车进路，尚不占用区间轨道。"""
        self.current_track = None
        self.departure_route_id = route_id
        self.route_id = route_id
        self.station_track = track
        self.station_position = max(0.0, float(initial_position))
        self.position = self.station_position
        self.status = "RUNNING"
        self.movement_phase = "DEPARTING"
        self.receive_waiting_reason = None
        self.stop_signal_id = None

    def wait_for_receive_route(self, message):
        self.position = min(self.position, 999.9)
        self.speed = 0.0
        self.target_speed = 0.0
        self.status = "STOPPED"
        self.movement_phase = "WAITING_RECEIVE_ROUTE"
        self.receive_waiting_reason = message
        self.stop_signal_id = None

    def wait_at_signal(self, signal_id):
        """在当前运行方向的防护信号机前停车。"""
        self.speed = 0.0
        self.target_speed = 0.0
        self.status = "STOPPED"
        self.movement_phase = "WAITING_SIGNAL"
        self.stop_signal_id = signal_id
        self.receive_waiting_reason = None

    def wait_for_ahead_track(self):
        """在同一闭塞分区内因前方轨道区段占用停车。"""
        self.speed = 0.0
        self.target_speed = 0.0
        self.status = "STOPPED"
        self.movement_phase = "WAITING_AHEAD_TRACK"
        self.stop_signal_id = None
        self.receive_waiting_reason = None

    def enter_station(self, initial_position=0.0):
        self.current_track = None
        self.station_position = max(0.0, float(initial_position))
        self.position = self.station_position
        self.status = "RUNNING"
        self.movement_phase = "RECEIVING"
        self.receive_throat_cleared = False
        self.receive_waiting_reason = None
        self.stop_signal_id = None

    def leave_section(self):

        self.current_track = None

        self.position = 0.0

        self.speed = 0.0

        self.target_speed = 0.0

        self.status = "ARRIVED"
        self.movement_phase = "ARRIVED"

    def set_target_speed(self, speed):

        self.target_speed = max(
            0.0,
            float(speed)
        )

    def get_status(self):

        return {
            "train_id": self.train_id,
            "direction": self.direction,
            "departure_mode": self.departure_mode,
            "arrival_mode": self.arrival_mode,
            "station_track": self.station_track,
            "arrival_track": self.arrival_track,
            "route_id": self.route_id,
            "departure_route_id": self.departure_route_id,
            "receive_route_id": self.receive_route_id,
            "receive_waiting_reason": self.receive_waiting_reason,
            "stop_signal_id": self.stop_signal_id,
            "movement_phase": self.movement_phase,
            "station_position": (
                round(self.station_position, 2)
                if self.station_position is not None else None
            ),
            "receive_throat_cleared": self.receive_throat_cleared,
            "current_track": self.current_track,

            "position": round(
                self.position,
                2
            ),

            "speed": round(
                self.speed,
                2
            ),

            "target_speed": round(
                self.target_speed,
                2
            ),

            "max_speed": round(
                self.max_speed,
                2
            ),

            "block_code": self.block_code,

            "block_speed": round(
                self.block_speed,
                2
            ),

            "line_speed": round(
                self.line_speed,
                2
            ),

            "last_balise": (
                self.last_balise
            ),

            "distance_to_ahead": (
                round(
                    self.distance_to_ahead,
                    1
                )
                if self.distance_to_ahead
                   is not None
                else None
            ),

            "braking_distance": round(
                self.braking_distance,
                1
            ),

            "safety_status": (
                self.safety_status
            ),

            "status": self.status
        }
    def update(self, delta_time):
        """
        根据经过的时间更新列车速度和位置。

        delta_time:
            本次仿真经过的时间，单位：秒
        """

        # 只有运行中的列车才更新
        if self.status != "RUNNING":
            return

        # -------------------------
        # 1. 当前速度低于目标速度
        #    列车加速
        # -------------------------
        if self.speed < self.target_speed:

            # km/h 转换成 m/s
            current_speed_ms = self.speed / 3.6

            # 根据加速度计算新的速度
            current_speed_ms += (
                self.acceleration * delta_time
            )

            # 再转换回 km/h
            new_speed = current_speed_ms * 3.6

            # 防止超过目标速度
            self.speed = min(
                new_speed,
                self.target_speed
            )

        # -------------------------
        # 2. 当前速度高于目标速度
        #    列车减速
        # -------------------------
        elif self.speed > self.target_speed:

            current_speed_ms = self.speed / 3.6

            current_speed_ms -= (
                self.deceleration * delta_time
            )

            # 速度不能小于0
            current_speed_ms = max(
                0.0,
                current_speed_ms
            )

            new_speed = current_speed_ms * 3.6

            # 防止减速低于目标速度
            self.speed = max(
                new_speed,
                self.target_speed
            )

        # -------------------------
        # 3. 根据当前速度更新位置
        # -------------------------

        speed_ms = self.speed / 3.6

        self.position += (
            speed_ms * delta_time
        )

    def calculate_target_speed(self):
        """
        综合各种速度限制，
        取最严格的速度作为最终目标速度。
        """

        self.target_speed = min(
            self.max_speed,
            self.block_speed,
            self.line_speed,
            self.active_balise_speed,
            self.temporary_speed
        )

        return self.target_speed
