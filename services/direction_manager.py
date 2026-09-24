from network.message_protocol import MessageProtocol


class DirectionManager:
    """
    单线区间改方管理器。

    负责改方申请、批准、拒绝的状态机与站间报文构造。

    安全检查委托给 SimulationService.can_change_direction()，
    方向应用委托给 SimulationService.set_direction()，
    本模块不复制既有的闭塞判定逻辑。
    """

    # 改方状态
    IDLE = "空闲"
    REQUESTING = "申请中"
    APPROVED = "改方成功"
    DENIED = "区间未清空"

    def __init__(
            self,
            simulation_service,
            tcc_code,
            station_type
    ):
        self.simulation = simulation_service
        self.tcc_code = tcc_code
        self.station_type = station_type

        # 当前改方状态
        self.status = self.IDLE

        # 最近一次的提示/拒绝原因
        self.reason = None

    # ==========================================
    # 方向查询
    # ==========================================

    def get_direction(self):

        return self.simulation.get_direction()

    def get_direction_text(self):
        """
        当前区间运行方向的显示文字。
        """

        if self.get_direction() == "A_TO_B":
            return "A站 → B站"

        return "B站 → A站"

    def get_target_direction(self):
        """
        本站希望申请的运行方向。
        """

        if self.station_type == "A":
            return "A_TO_B"

        return "B_TO_A"

    # ==========================================
    # 申请方：构造改方申请
    # ==========================================

    def create_request(self):
        """
        本站申请改方。

        返回：
        (报文, None) 表示可以发送申请；
        (None, 原因) 表示本站不满足条件。
        """

        if not self.simulation.can_change_direction():

            self.status = self.DENIED
            self.reason = "区间未清空"

            return None, self.reason

        target_direction = self.get_target_direction()

        # 已经是目标方向，无需改方
        if target_direction == self.get_direction():

            self.reason = "当前区间已经是本站申请的运行方向"

            return None, self.reason

        self.status = self.REQUESTING
        self.reason = None

        message = MessageProtocol.create_message(
            MessageProtocol.DIRECTION_REQUEST,
            self.tcc_code,
            {
                "current_direction": self.get_direction(),
                "target_direction": target_direction
            }
        )

        return message, None

    # ==========================================
    # 被申请方：判定并构造应答
    # ==========================================

    def evaluate_request(self, target_direction):
        """
        对邻站的改方申请做安全判定。

        返回：
        (True, None) 表示批准；
        (False, 原因) 表示拒绝。
        """

        if not self.simulation.can_change_direction():

            self.status = self.DENIED
            self.reason = "区间未清空"

            return False, self.reason

        # 条件满足，本站先切到目标方向
        self.simulation.set_direction(
            target_direction
        )

        self.status = self.APPROVED
        self.reason = None

        return True, None

    def create_reply(
            self,
            approved,
            target_direction,
            reason=None
    ):
        """
        构造批准/拒绝报文。
        """

        if approved:

            message_type = (
                MessageProtocol.DIRECTION_APPROVE
            )

            data = {
                "current_direction": self.get_direction(),
                "target_direction": target_direction
            }

        else:

            message_type = (
                MessageProtocol.DIRECTION_DENY
            )

            data = {
                "target_direction": target_direction,
                "reason": reason or self.DENIED
            }

        return MessageProtocol.create_message(
            message_type,
            self.tcc_code,
            data
        )

    # ==========================================
    # 申请方：处理应答
    # ==========================================

    def apply_reply(self, message_type, data):
        """
        处理邻站的批准/拒绝报文。

        返回：
        (显示文字, 是否成功)
        """

        if message_type == MessageProtocol.DIRECTION_APPROVE:

            self.simulation.set_direction(
                data.get("target_direction")
            )

            self.status = self.APPROVED
            self.reason = None

            return self.APPROVED, True

        self.status = self.DENIED
        self.reason = data.get(
            "reason",
            self.DENIED
        )

        return self.reason, False
