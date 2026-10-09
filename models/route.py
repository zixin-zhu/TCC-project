from dataclasses import dataclass


class RouteType:
    MAIN_RECEIVE = "MAIN_RECEIVE"
    SIDE_RECEIVE = "SIDE_RECEIVE"
    MAIN_DEPART = "MAIN_DEPART"
    SIDE_DEPART = "SIDE_DEPART"


class RouteState:
    ESTABLISHED = "ESTABLISHED"
    LOCKED = "LOCKED"


@dataclass
class Route:
    route_id: str
    station: str
    route_type: str
    display_name: str
    track: str
    movement: str
    state: str = RouteState.ESTABLISHED
    train_id: str | None = None
    created_order: int = 0
