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

        with self.assertRaises(ValueError) as raised:
            service.establish_route("A", RouteType.SIDE_DEPART)

        message = str(raised.exception)
        self.assertIn("A站", message)
        self.assertIn("正线接车", message)
        self.assertIn("侧线发车", message)
        self.assertEqual(service.active_routes(), [first])

    def test_exact_duplicate_route_has_specific_recovery_message(self):
        service = RouteService()
        first = service.establish_route("A", RouteType.MAIN_DEPART)

        with self.assertRaises(ValueError) as raised:
            service.establish_route("A", RouteType.MAIN_DEPART)

        message = str(raised.exception)
        self.assertIn("A站", message)
        self.assertIn("正线发车", message)
        self.assertIn("请勿重复操作", message)
        self.assertEqual(service.active_routes(), [first])

    def test_opposing_departure_routes_conflict(self):
        service = RouteService()
        first = service.establish_route("A", RouteType.MAIN_DEPART)

        with self.assertRaises(ValueError) as raised:
            service.establish_route("B", RouteType.SIDE_DEPART)

        message = str(raised.exception)
        self.assertIn("A站", message)
        self.assertIn("正线发车", message)
        self.assertIn("B站", message)
        self.assertIn("侧线发车", message)
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
        with self.assertRaises(ValueError) as raised:
            service.cancel_route(route.route_id)
        self.assertIn("T001", str(raised.exception))
        self.assertIn("不能人工取消", str(raised.exception))
        self.assertEqual(service.active_routes(), [locked])
        self.assertTrue(service.release_route(route.route_id))
        self.assertEqual(service.active_routes(), [])

    def test_locked_route_cannot_be_rebound_to_another_train(self):
        service = RouteService()
        route = service.establish_route("A", RouteType.MAIN_DEPART)
        service.lock_route(route.route_id, "T001")

        with self.assertRaisesRegex(ValueError, "进路已被其他列车锁闭"):
            service.lock_route(route.route_id, "T002")

        self.assertEqual(route.train_id, "T001")

    def test_clear_all_removes_routes_and_resets_sequence(self):
        service = RouteService()
        service.establish_route("A", RouteType.MAIN_DEPART)
        service.establish_route("B", RouteType.MAIN_RECEIVE)

        service.clear_all()
        route = service.establish_route("B", RouteType.SIDE_RECEIVE)

        self.assertEqual(service.active_routes(), [route])
        self.assertEqual(route.route_id, "B-SIDE-RECEIVE-001")

    def test_reset_locks_preserves_routes_and_clears_train_bindings(self):
        service = RouteService()
        departure = service.establish_route("A", RouteType.MAIN_DEPART)
        receive = service.establish_route("B", RouteType.SIDE_RECEIVE)
        original_ids = [departure.route_id, receive.route_id]
        original_orders = [departure.created_order, receive.created_order]
        service.lock_route(departure.route_id, "T001")
        service.lock_route(receive.route_id, "T001")

        service.reset_locks()

        routes = service.active_routes()
        self.assertEqual([route.route_id for route in routes], original_ids)
        self.assertEqual(
            [route.created_order for route in routes], original_orders
        )
        self.assertTrue(
            all(route.state == RouteState.ESTABLISHED for route in routes)
        )
        self.assertTrue(all(route.train_id is None for route in routes))


if __name__ == "__main__":
    unittest.main()
