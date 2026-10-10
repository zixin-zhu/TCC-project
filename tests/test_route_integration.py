import unittest
from unittest.mock import patch

from PyQt5.QtWidgets import QApplication

from models.route import RouteState, RouteType
from services.route_service import RouteService
from services.simulation_service import SimulationService
from services.train_service import TrainService
from services.direction_manager import DirectionManager
from network.message_protocol import MessageProtocol
from ui.main_window import MainWindow


class RouteTrainIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.simulation = SimulationService("A")
        self.routes = RouteService()
        self.trains = TrainService(self.simulation, self.routes)

    def test_train_does_not_dispatch_without_departure_route(self):
        train = self.trains.add_waiting_train("MAIN")

        self.assertFalse(self.trains.dispatch_train(train))
        self.assertEqual(train.status, "WAITING")
        self.assertIsNone(train.current_track)

    def test_stopped_train_still_occupies_section_for_following_train(self):
        leading = self.trains.create_train()
        leading.enter_track("G02")
        leading.status = "STOPPED"
        following = self.trains.create_train()
        following.enter_track("G01")
        following.position = self.trains.default_track_length + 1

        self.trains.handle_track_transition(following)

        self.assertEqual(following.current_track, "G01")
        self.assertEqual(following.status, "STOPPED")

    def test_main_train_does_not_use_side_departure_route(self):
        self.routes.establish_route("A", RouteType.SIDE_DEPART)
        train = self.trains.add_waiting_train("MAIN")

        self.assertFalse(self.trains.dispatch_train(train))
        self.assertEqual(train.status, "WAITING")

    def test_matching_departure_route_dispatches_and_locks(self):
        route = self.routes.establish_route("A", RouteType.MAIN_DEPART)
        train = self.trains.add_waiting_train("MAIN")

        self.assertTrue(self.trains.dispatch_train(train))
        self.assertEqual(train.current_track, "G01")
        self.assertEqual(train.station_track, "1G")
        self.assertEqual(train.route_id, route.route_id)
        self.assertEqual(route.state, RouteState.LOCKED)
        self.assertEqual(route.train_id, train.train_id)

    def test_departure_route_remains_established_after_train_enters_second_section(self):
        route = self.routes.establish_route("A", RouteType.SIDE_DEPART)
        train = self.trains.add_waiting_train("SIDE")
        self.assertTrue(self.trains.dispatch_train(train))

        train.position = self.trains.default_track_length + 5
        self.trains.handle_track_transition(train)

        self.assertEqual(train.current_track, "G02")
        self.assertIsNone(train.route_id)
        self.assertIn(route, self.routes.active_routes())
        self.assertEqual(route.state, RouteState.ESTABLISHED)
        self.assertIsNone(route.train_id)

    def test_receive_route_locks_at_terminal_section_and_remains_after_arrival(self):
        self.simulation.set_direction("B_TO_A")
        departure = self.routes.establish_route("B", RouteType.SIDE_DEPART)
        receive = self.routes.establish_route("A", RouteType.SIDE_RECEIVE)
        train = self.trains.add_waiting_train("SIDE", "SIDE")
        self.assertTrue(self.trains.dispatch_train(train))

        train.position = self.trains.default_track_length + 1
        self.trains.handle_track_transition(train)
        self.assertIn(departure, self.routes.active_routes())
        self.assertEqual(departure.state, RouteState.ESTABLISHED)

        train.current_track = "G02"
        train.position = self.trains.default_track_length + 1
        self.trains.handle_track_transition(train)

        self.assertEqual(train.current_track, "G01")
        self.assertEqual(train.route_id, receive.route_id)
        self.assertEqual(receive.state, RouteState.LOCKED)

        train.position = self.trains.default_track_length + 1
        self.trains.handle_track_transition(train)

        self.assertEqual(train.status, "ARRIVED")
        self.assertIsNone(train.route_id)
        self.assertIn(receive, self.routes.active_routes())
        self.assertEqual(receive.state, RouteState.ESTABLISHED)
        self.assertIsNone(receive.train_id)


class RouteSignalIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_simulation(self, station="A"):
        routes = RouteService()
        return routes, SimulationService(station, routes)

    def test_departure_signal_requires_route_direction_and_clear_entry(self):
        cases = (
            (None, "A_TO_B", False, "红灯"),
            (RouteType.MAIN_DEPART, "B_TO_A", False, "红灯"),
            (RouteType.MAIN_DEPART, "A_TO_B", True, "红灯"),
            (RouteType.MAIN_DEPART, "A_TO_B", False, "绿灯"),
            (RouteType.SIDE_DEPART, "A_TO_B", False, "L灯"),
        )

        for route_type, direction, occupied, expected in cases:
            with self.subTest(
                route_type=route_type,
                direction=direction,
                occupied=occupied,
            ):
                routes, simulation = self.make_simulation("A")
                if route_type is not None:
                    routes.establish_route("A", route_type)
                simulation.set_direction(direction)
                if occupied:
                    simulation.track_circuits["G01"].occupy()

                aspects = simulation.update_signal_status()

                self.assertEqual(aspects["S01"], expected)

    def test_receive_route_extends_boundary_code_target(self):
        routes, simulation = self.make_simulation("B")
        simulation.set_direction("A_TO_B")
        simulation.update_all_track_codes()
        without_route = simulation.track_circuits["G38"].signal_code

        routes.establish_route("B", RouteType.MAIN_RECEIVE)
        simulation.update_all_track_codes()
        with_route = simulation.track_circuits["G38"].signal_code

        self.assertEqual(without_route, "HU")
        self.assertEqual(with_route, "U")

    def test_station_track_codes_follow_route_type(self):
        cases = (
            (RouteType.MAIN_DEPART, "1G", "L5"),
            (RouteType.SIDE_DEPART, "3G", "UUS"),
            (RouteType.MAIN_RECEIVE, "1G", "HU"),
            (RouteType.SIDE_RECEIVE, "3G", "UUS"),
        )

        for route_type, track, expected_code in cases:
            with self.subTest(route_type=route_type):
                routes, simulation = self.make_simulation("A")
                routes.establish_route("A", route_type)
                simulation.update_all_track_codes()

                codes = simulation.get_station_track_codes()

                self.assertEqual(codes[track], expected_code)
                self.assertIn(codes["THROAT"], ("HU", "UUS", "L5", "L3", "L2", "L", "LU", "U"))

    def test_station_codes_default_to_restrictive_code(self):
        _, simulation = self.make_simulation("B")

        self.assertEqual(
            simulation.get_station_track_codes(),
            {"1G": "HU", "3G": "HU", "THROAT": "HU"},
        )

    def test_word_code_sequence_includes_l4(self):
        _, simulation = self.make_simulation("A")

        self.assertEqual(simulation.calculate_track_code(6), "L4")
        self.assertEqual(simulation.get_aspect_by_code("L4"), "绿灯")

    def test_balise_packets_follow_route_type(self):
        window = MainWindow()
        with patch.object(window, "is_connected", return_value=True):
            default_info = window.get_balise_information("B站X口_JZ")
            self.assertIn("ETCS-132", default_info["packets"])
            self.assertNotIn("ETCS-68", default_info["packets"])

            window.route_service.establish_route("B", RouteType.SIDE_RECEIVE)
            side_info = window.get_balise_information("B站X口_JZ")
            self.assertIn("ETCS-68", side_info["packets"])
            self.assertTrue(
                any("CTCS-1" in packet for packet in side_info["packets"])
            )
            self.assertFalse(
                any("CTCS-2" in packet for packet in side_info["packets"])
            )

            window.temporary_speed_service.set_restriction("G05", "G08", 80)
            restricted_info = window.get_balise_information("B站X口_JZ")
            self.assertIn("ETCS-44(CTCS-2)", restricted_info["packets"])
        window.close()


class RouteDirectionIntegrationTest(unittest.TestCase):
    def make_manager(self, station, routes):
        simulation = SimulationService(station, routes)
        manager = DirectionManager(
            simulation,
            f"TCC_{station}",
            station,
            routes,
        )
        return simulation, manager

    def test_direction_request_requires_local_departure_route(self):
        routes = RouteService()
        simulation, manager = self.make_manager("B", routes)

        message, reason = manager.create_request()

        self.assertIsNone(message)
        self.assertEqual(reason, "本站未建立发车进路")
        self.assertEqual(simulation.get_direction(), "A_TO_B")

    def test_invalid_target_direction_is_denied(self):
        routes = RouteService()
        simulation, manager = self.make_manager("A", routes)

        approved, reason = manager.evaluate_request("INVALID")

        self.assertFalse(approved)
        self.assertEqual(reason, "非法目标方向")
        self.assertEqual(simulation.get_direction(), "A_TO_B")

    def test_direction_request_is_denied_when_remote_departure_route_exists(self):
        routes = RouteService()
        routes.establish_route("A", RouteType.MAIN_DEPART)
        simulation, manager = self.make_manager("A", routes)

        approved, reason = manager.evaluate_request("B_TO_A")

        self.assertFalse(approved)
        self.assertEqual(reason, "被申请站存在发车进路")
        self.assertEqual(simulation.get_direction(), "A_TO_B")

    def test_failed_direction_change_preserves_established_route(self):
        routes = RouteService()
        route = routes.establish_route("B", RouteType.SIDE_DEPART)
        simulation, manager = self.make_manager("B", routes)
        simulation.track_circuits["G20"].occupy()

        message, reason = manager.create_request()

        self.assertIsNone(message)
        self.assertEqual(reason, "区间未清空")
        self.assertIn(route, routes.active_routes())
        self.assertEqual(simulation.get_direction(), "A_TO_B")

    def test_valid_route_and_empty_interval_allow_direction_change(self):
        routes = RouteService()
        route = routes.establish_route("B", RouteType.MAIN_DEPART)
        simulation_a, manager_a = self.make_manager("A", routes)
        simulation_b, manager_b = self.make_manager("B", routes)

        request, reason = manager_b.create_request()
        self.assertIsNotNone(request)
        self.assertIsNone(reason)

        approved, reason = manager_a.evaluate_request("B_TO_A")
        self.assertTrue(approved)
        self.assertIsNone(reason)

        text, success = manager_b.apply_reply(
            MessageProtocol.DIRECTION_APPROVE,
            {"target_direction": "B_TO_A"},
        )

        self.assertTrue(success)
        self.assertEqual(text, DirectionManager.APPROVED)
        self.assertEqual(simulation_a.get_direction(), "B_TO_A")
        self.assertEqual(simulation_b.get_direction(), "B_TO_A")
        self.assertIn(route, routes.active_routes())


if __name__ == "__main__":
    unittest.main()
