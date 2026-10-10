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
        station_routes = self.active_routes(station)
        duplicate = next(
            (
                route
                for route in station_routes
                if route.route_type == route_type
            ),
            None,
        )
        if duplicate is not None:
            raise ValueError(
                f"{station}站{display_name}已建立，请勿重复操作。"
            )
        if station_routes:
            existing = station_routes[0]
            raise ValueError(
                f"{station}站已建立{existing.display_name}，"
                f"不能同时建立{display_name}；请先取消现有进路。"
            )
        if movement == "DEPART":
            remote_station = "B" if station == "A" else "A"
            remote_departure = next(
                (
                    route
                    for route in self.active_routes(remote_station)
                    if route.movement == "DEPART"
                ),
                None,
            )
            if remote_departure is not None:
                raise ValueError(
                    f"{remote_station}站已建立{remote_departure.display_name}，"
                    f"不能再建立{station}站{display_name}；"
                    "请先取消对端发车进路。"
                )

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
            raise ValueError(
                f"{route.station}站{route.display_name}已被列车"
                f"{route.train_id}锁闭，列车已进入进路，不能人工取消。"
            )
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

    def unlock_route(self, route_id: str) -> bool:
        route = self._routes.get(route_id)
        if route is None:
            return False
        route.state = RouteState.ESTABLISHED
        route.train_id = None
        return True

    def unlock_routes_for_train(self, train_id: str) -> None:
        for route in self._routes.values():
            if route.train_id == train_id:
                route.state = RouteState.ESTABLISHED
                route.train_id = None

    def clear_all(self) -> None:
        self._routes.clear()
        self._next_order = 1

    def reset_locks(self) -> None:
        for route in self._routes.values():
            route.state = RouteState.ESTABLISHED
            route.train_id = None

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
