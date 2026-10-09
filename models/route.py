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

    def to_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "station": self.station,
            "route_type": self.route_type,
            "display_name": self.display_name,
            "track": self.track,
            "movement": self.movement,
            "state": self.state,
            "train_id": self.train_id,
            "created_order": self.created_order,
        }
