from models.route import Route, RouteState, RouteType


class RouteService:
    ROUTE_SPECS = {
        RouteType.MAIN_RECEIVE: ("正线接车", "1G", "RECEIVE"),
        RouteType.SIDE_RECEIVE: ("侧线接车", "3G", "RECEIVE"),
        RouteType.MAIN_DEPART: ("正线发车", "1G", "DEPART"),
        RouteType.SIDE_DEPART: ("侧线发车", "3G", "DEPART"),
    }

    def __init__(self):
        self._routes = {}
        self._next_order = 1

    def establish_route(self, station: str, route_type: str) -> Route:
        if station not in ("A", "B"):
            raise ValueError("非法车站")
        if route_type not in self.ROUTE_SPECS:
            raise ValueError("非法进路类型")

        display_name, track, movement = self.ROUTE_SPECS[route_type]
        if self.active_routes(station):
            raise ValueError("本站存在冲突进路")
        if movement == "DEPART":
            remote_station = "B" if station == "A" else "A"
            if self.has_departure_route(remote_station):
                raise ValueError("对端已有发车进路")

        route = Route(
            route_id=f"{station}-{route_type.replace('_', '-')}-{self._next_order:03d}",
            station=station,
            route_type=route_type,
            display_name=display_name,
            track=track,
            movement=movement,
            state=RouteState.ESTABLISHED,
            created_order=self._next_order,
        )
        self._routes[route.route_id] = route
        self._next_order += 1
        return route

    def active_routes(self, station: str | None = None) -> list[Route]:
        routes = list(self._routes.values())
        if station is None:
            return routes
        return [route for route in routes if route.station == station]

    def cancel_route(self, route_id: str) -> bool:
        route = self._routes.get(route_id)
        if route is None:
            return False
        if route.state == RouteState.LOCKED:
            raise ValueError("列车已进入进路，不能人工取消")
        del self._routes[route_id]
        return True

    def lock_route(self, route_id: str, train_id: str) -> Route:
        route = self._routes.get(route_id)
        if route is None:
            raise ValueError("进路不存在")
        if route.state == RouteState.LOCKED and route.train_id != train_id:
            raise ValueError("进路已被其他列车锁闭")
        route.state = RouteState.LOCKED
        route.train_id = train_id
        return route

    def release_route(self, route_id: str) -> bool:
        if route_id not in self._routes:
            return False
        del self._routes[route_id]
        return True

    def clear_all(self) -> None:
        self._routes.clear()
        self._next_order = 1

    def departure_route_for(self, station: str, track: str) -> Route | None:
        return self._route_for(station, track, "DEPART")

    def receive_route_for(self, station: str, track: str) -> Route | None:
        return self._route_for(station, track, "RECEIVE")

    def has_departure_route(self, station: str) -> bool:
        return any(
            route.movement == "DEPART"
            for route in self.active_routes(station)
        )

    def _route_for(self, station: str, track: str, movement: str) -> Route | None:
        for route in self.active_routes(station):
            if route.track == track and route.movement == movement:
                return route
        return None
