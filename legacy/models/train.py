class Train:

    def __init__(
        self,
        train_id,
        direction="A_TO_B"
    ):
        self.train_id = train_id

        self.direction = direction

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


    def enter_track(self, track_code):

        self.current_track = track_code

        self.position = 0.0

        self.status = "RUNNING"

    def leave_section(self):

        self.current_track = None

        self.position = 0.0

        self.speed = 0.0

        self.target_speed = 0.0

        self.status = "ARRIVED"

    def set_target_speed(self, speed):

        self.target_speed = max(
            0.0,
            float(speed)
        )

    def get_status(self):

        return {
            "train_id": self.train_id,
            "direction": self.direction,
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