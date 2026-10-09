import unittest

from models.route import RouteState, RouteType
from services.route_service import RouteService


class RouteServiceTest(unittest.TestCase):
    def test_all_four_route_types_can_be_established_for_each_station(self):
        cases = (
            (RouteType.MAIN_RECEIVE, "正线接车", "1G", "RECEIVE"),
            (RouteType.SIDE_RECEIVE, "侧线接车", "3G", "RECEIVE"),
            (RouteType.MAIN_DEPART, "正线发车", "1G", "DEPART"),
            (RouteType.SIDE_DEPART, "侧线发车", "3G", "DEPART"),
        )

        for station in ("A", "B"):
            for route_type, display_name, track, movement in cases:
                with self.subTest(station=station, route_type=route_type):
                    service = RouteService()
                    route = service.establish_route(station, route_type)

                    self.assertEqual(route.station, station)
                    self.assertEqual(route.route_type, route_type)
                    self.assertEqual(route.display_name, display_name)
                    self.assertEqual(route.track, track)
                    self.assertEqual(route.movement, movement)
                    self.assertEqual(route.state, RouteState.ESTABLISHED)
                    self.assertIsNone(route.train_id)
                    self.assertEqual(service.active_routes(), [route])

    def test_invalid_station_or_route_type_does_not_change_state(self):
        service = RouteService()

        for station, route_type in (
            ("C", RouteType.MAIN_DEPART),
            ("A", "UNKNOWN"),
        ):
            with self.subTest(station=station, route_type=route_type):
                with self.assertRaises(ValueError):
                    service.establish_route(station, route_type)
                self.assertEqual(service.active_routes(), [])

    def test_same_station_routes_conflict(self):
        service = RouteService()
        first = service.establish_route("A", RouteType.MAIN_RECEIVE)

        with self.assertRaisesRegex(ValueError, "本站存在冲突进路"):
            service.establish_route("A", RouteType.SIDE_DEPART)

        self.assertEqual(service.active_routes(), [first])

    def test_opposing_departure_routes_conflict(self):
        service = RouteService()
        first = service.establish_route("A", RouteType.MAIN_DEPART)

        with self.assertRaisesRegex(ValueError, "对端已有发车进路"):
            service.establish_route("B", RouteType.SIDE_DEPART)

        self.assertEqual(service.active_routes(), [first])

    def test_matching_departure_and_remote_receive_can_coexist(self):
        service = RouteService()
        departure = service.establish_route("A", RouteType.MAIN_DEPART)
        receive = service.establish_route("B", RouteType.MAIN_RECEIVE)

        self.assertEqual(service.active_routes(), [departure, receive])
        self.assertIs(
            service.departure_route_for("A", "1G"),
            departure,
        )
        self.assertIs(
            service.receive_route_for("B", "1G"),
            receive,
        )
        self.assertTrue(service.has_departure_route("A"))
        self.assertFalse(service.has_departure_route("B"))

    def test_established_route_can_be_cancelled(self):
        service = RouteService()
        route = service.establish_route("A", RouteType.MAIN_DEPART)

        self.assertTrue(service.cancel_route(route.route_id))
        self.assertEqual(service.active_routes(), [])
        self.assertFalse(service.cancel_route(route.route_id))

    def test_locked_route_cannot_be_cancelled(self):
        service = RouteService()
        route = service.establish_route("A", RouteType.MAIN_DEPART)
        locked = service.lock_route(route.route_id, "T001")

        self.assertEqual(locked.state, RouteState.LOCKED)
        self.assertEqual(locked.train_id, "T001")
        with self.assertRaisesRegex(ValueError, "列车已进入进路，不能人工取消"):
            service.cancel_route(route.route_id)
        self.assertEqual(service.active_routes(), [locked])
        self.assertTrue(service.release_route(route.route_id))
        self.assertEqual(service.active_routes(), [])

    def test_clear_all_removes_routes_and_resets_sequence(self):
        service = RouteService()
        service.establish_route("A", RouteType.MAIN_DEPART)
        service.establish_route("B", RouteType.MAIN_RECEIVE)

        service.clear_all()
        route = service.establish_route("B", RouteType.SIDE_RECEIVE)

        self.assertEqual(service.active_routes(), [route])
        self.assertEqual(route.route_id, "B-SIDE-RECEIVE-001")


if __name__ == "__main__":
    unittest.main()
