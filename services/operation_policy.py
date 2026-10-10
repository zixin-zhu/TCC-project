from dataclasses import dataclass

from models.route import RouteType


@dataclass
class OperationRuleError(ValueError):
    summary: str
    current_state: str
    suggestion: str

    def __post_init__(self):
        super().__init__(self.format_message())

    def format_message(self) -> str:
        return (
            f"操作失败：{self.summary}\n"
            f"当前状态：{self.current_state}\n"
            f"处理建议：{self.suggestion}"
        )


class OperationPolicy:
    DIRECTION_LABELS = {
        "A_TO_B": "A站→B站",
        "B_TO_A": "B站→A站",
    }
    ROUTE_NAMES = {
        RouteType.MAIN_RECEIVE: "正线接车",
        RouteType.SIDE_RECEIVE: "侧线接车",
        RouteType.MAIN_DEPART: "正线发车",
        RouteType.SIDE_DEPART: "侧线发车",
    }
    ALLOWED_ROUTES = {
        "A_TO_B": {
            ("A", RouteType.MAIN_DEPART),
            ("A", RouteType.SIDE_DEPART),
            ("B", RouteType.MAIN_RECEIVE),
            ("B", RouteType.SIDE_RECEIVE),
        },
        "B_TO_A": {
            ("B", RouteType.MAIN_DEPART),
            ("B", RouteType.SIDE_DEPART),
            ("A", RouteType.MAIN_RECEIVE),
            ("A", RouteType.SIDE_RECEIVE),
        },
    }

    @classmethod
    def validate_route_request(
        cls, direction: str, station: str, route_type: str
    ) -> None:
        if direction not in cls.ALLOWED_ROUTES:
            raise OperationRuleError(
                "当前运行方向无效",
                f"系统方向值为 {direction}",
                "请先恢复有效的区间运行方向后再建立进路。",
            )
        if (station, route_type) in cls.ALLOWED_ROUTES[direction]:
            return

        route_name = cls.ROUTE_NAMES.get(route_type, route_type)
        direction_name = cls.DIRECTION_LABELS[direction]
        departure_station = "A" if direction == "A_TO_B" else "B"
        receive_station = "B" if direction == "A_TO_B" else "A"
        raise OperationRuleError(
            f"{station}站不能建立{route_name}",
            f"当前方向为{direction_name}，只允许{departure_station}站发车、"
            f"{receive_station}站接车。",
            f"请建立{departure_station}站发车进路或{receive_station}站接车进路。",
        )

    @classmethod
    def validate_waiting_train_routes(
        cls, direction: str, trains: list, route_service
    ) -> None:
        if direction not in cls.ALLOWED_ROUTES:
            cls.validate_route_request(direction, "A", RouteType.MAIN_DEPART)

        departure_station = "A" if direction == "A_TO_B" else "B"
        receive_station = "B" if direction == "A_TO_B" else "A"

        for train in trains:
            departure_track = cls._mode_to_track(train.departure_mode)
            arrival_track = cls._mode_to_track(train.arrival_mode)
            departure_route = route_service.departure_route_for(
                departure_station, departure_track
            )
            if departure_route is None:
                departure_name = cls._mode_route_name(
                    train.departure_mode, "发车"
                )
                raise OperationRuleError(
                    f"列车{train.train_id}缺少匹配的出发进路",
                    f"列车选择{departure_station}站{departure_name}，"
                    "但该进路尚未建立。",
                    f"请先建立{departure_station}站{departure_name}，"
                    "或修改列车的发车方式。",
                )

            receive_route = route_service.receive_route_for(
                receive_station, arrival_track
            )
            if receive_route is None:
                receive_name = cls._mode_route_name(
                    train.arrival_mode, "接车"
                )
                raise OperationRuleError(
                    f"列车{train.train_id}缺少匹配的到达进路",
                    f"列车选择{receive_station}站{receive_name}，"
                    "但该进路尚未建立。",
                    f"请先建立{receive_station}站{receive_name}，"
                    "或修改列车的接车方式。",
                )

    @staticmethod
    def _mode_to_track(mode: str) -> str:
        return "1G" if mode == "MAIN" else "3G"

    @staticmethod
    def _mode_route_name(mode: str, movement_name: str) -> str:
        line_name = "正线" if mode == "MAIN" else "侧线"
        return f"{line_name}{movement_name}"
