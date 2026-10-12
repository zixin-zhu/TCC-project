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

    def test_matching_departure_route_dispatches_and_is_consumed(self):
        route = self.routes.establish_route("A", RouteType.MAIN_DEPART)
        train = self.trains.add_waiting_train("MAIN")

        self.assertTrue(self.trains.dispatch_train(train))
        self.assertIsNone(train.current_track)
        self.assertEqual(train.movement_phase, "DEPARTING")
        self.assertEqual(train.route_id, route.route_id)
        self.assertEqual(train.departure_route_id, route.route_id)
        self.assertEqual(route.state, RouteState.LOCKED)
        self.assertEqual(route.train_id, train.train_id)
        self.assertIn(route, self.routes.active_routes())

        train.station_position = self.trains.STATION_EXIT_POSITION
        self.trains.handle_departure_transition(train)

        self.assertEqual(train.current_track, "G01")
        self.assertEqual(train.station_track, "1G")
        self.assertIsNone(train.route_id)
        self.assertIsNone(train.departure_route_id)
        self.assertNotIn(route, self.routes.active_routes())

    def test_departure_route_is_not_restored_after_train_enters_second_section(self):
        route = self.routes.establish_route("A", RouteType.SIDE_DEPART)
        train = self.trains.add_waiting_train("SIDE")
        self.assertTrue(self.trains.dispatch_train(train))

        train.station_position = self.trains.STATION_EXIT_POSITION
        self.trains.handle_departure_transition(train)
        train.position = self.trains.default_track_length + 5
        self.trains.handle_track_transition(train)

        self.assertEqual(train.current_track, "G02")
        self.assertIsNone(train.route_id)
        self.assertNotIn(route, self.routes.active_routes())

    def test_receive_route_is_locked_only_when_train_enters_station(self):
        self.simulation.set_direction("B_TO_A")
        departure = self.routes.establish_route("B", RouteType.SIDE_DEPART)
        receive = self.routes.establish_route("A", RouteType.SIDE_RECEIVE)
        train = self.trains.add_waiting_train("SIDE")
        self.assertTrue(self.trains.dispatch_train(train))

        train.station_position = self.trains.STATION_EXIT_POSITION
        self.trains.handle_departure_transition(train)
        self.assertNotIn(departure, self.routes.active_routes())
        self.assertEqual(receive.state, RouteState.ESTABLISHED)
        self.assertIsNone(train.receive_route_id)

        train.current_track = "G01"
        train.position = self.trains.default_track_length + 1
        self.trains.handle_track_transition(train)

        self.assertEqual(train.route_id, receive.route_id)
        self.assertEqual(train.receive_route_id, receive.route_id)
        self.assertEqual(receive.state, RouteState.LOCKED)

    def test_receive_throat_clearance_uses_derived_station_section_boundary(self):
        receive = self.routes.establish_route("B", RouteType.MAIN_RECEIVE)
        train = self.trains.create_train()
        train.configure_receive_route(receive.route_id, "1G")
        train.enter_station()
        self.trains.STATION_EXIT_POSITION = 3600.0

        train.station_position = 1199.9
        self.trains.handle_station_transition(train)
        self.assertFalse(train.receive_throat_cleared)

        train.station_position = 1200.1
        self.trains.handle_station_transition(train)
        self.assertTrue(train.receive_throat_cleared)

    def test_cancelled_receive_route_stops_train_at_destination_signal(self):
        train = self.trains.create_train()
        train.enter_track("G20")
        receive = self.routes.establish_route("B", RouteType.MAIN_RECEIVE)
        self.assertIs(self.trains.assign_receive_route(receive), train)
        self.assertEqual(receive.train_id, train.train_id)

        self.trains.cancel_route(receive.route_id)
        train.current_track = "G38"
        train.position = self.trains.default_track_length + 1
        self.trains.handle_track_transition(train)

        self.assertEqual(train.movement_phase, "WAITING_RECEIVE_ROUTE")
        self.assertEqual(train.current_track, "G38")
        self.assertIsNone(train.receive_route_id)
        self.assertIsNone(train.arrival_mode)

    def test_departure_route_in_use_cannot_be_cancelled_before_station_boundary(self):
        route = self.routes.establish_route("A", RouteType.MAIN_DEPART)
        train = self.trains.add_waiting_train("MAIN")
        self.assertTrue(self.trains.dispatch_train(train))

        with self.assertRaisesRegex(ValueError, "驶出站界前不能人工取消"):
            self.trains.cancel_route(route.route_id)

        self.assertIn(route, self.routes.active_routes())


class RouteSignalIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_simulation(self, station="A"):
        routes = RouteService()
        return routes, SimulationService(station, routes)

    def test_aspect_for_code_covers_all_codes_and_fails_safe(self):
        _, simulation = self.make_simulation()
        expected = {
            "L5": "绿灯",
            "L4": "绿灯",
            "L3": "绿灯",
            "L2": "绿灯",
            "L": "绿灯",
            "LU": "黄绿灯",
            "U": "黄灯",
            "U2S": "黄灯",
            "HU": "红灯",
            "UUS": "双黄灯",
            None: "红灯",
            "INVALID": "红灯",
        }

        self.assertEqual(
            {code: simulation.aspect_for_code(code) for code in expected},
            expected,
        )

    def test_interval_codes_are_shared_by_each_two_section_block(self):
        _, simulation = self.make_simulation()
        simulation.set_direction("A_TO_B")
        simulation.update_all_track_codes()

        expected_tail = ("L5", "L4", "L3", "L2", "L", "LU", "U", "HU")
        actual_tail = []
        for block_no in range(12, 20):
            first = simulation.track_circuits[f"G{block_no * 2 - 1:02d}"].signal_code
            second = simulation.track_circuits[f"G{block_no * 2:02d}"].signal_code
            self.assertEqual(first, second)
            actual_tail.append(first)

        self.assertEqual(tuple(actual_tail), expected_tail)

    def test_occupied_block_keeps_code_derived_from_clear_blocks_ahead(self):
        _, simulation = self.make_simulation()
        simulation.track_circuits["G25"].occupy()

        simulation.update_all_track_codes()

        self.assertEqual(simulation.track_circuits["G25"].signal_code, "L4")
        self.assertEqual(simulation.track_circuits["G26"].signal_code, "L4")
        self.assertEqual(simulation.track_circuits["G23"].signal_code, "HU")
        self.assertEqual(simulation.track_circuits["G24"].signal_code, "HU")

    def test_main_receive_route_extends_code_and_station_turns_b_after_entry(self):
        routes, simulation = self.make_simulation("B")
        route = routes.establish_route("B", RouteType.MAIN_RECEIVE)

        simulation.update_all_track_codes()
        self.assertEqual(simulation.track_circuits["G38"].signal_code, "L")
        self.assertEqual(
            simulation.get_station_track_codes(),
            {"1G": "HU", "3G": "HU", "THROAT": "HU"},
        )

        routes.lock_route(route.route_id, "T001")
        simulation.set_train_states([
            {
                "train_id": "T001",
                "direction": "A_TO_B",
                "movement_phase": "RECEIVING",
                "arrival_track": "1G",
            }
        ])
        simulation.update_all_track_codes()

        self.assertEqual(simulation.track_circuits["G38"].signal_code, "HU")
        self.assertEqual(simulation.get_station_track_codes()["1G"], "HU")
        self.assertEqual(simulation.get_station_track_codes()["THROAT"], "HU")

        simulation.set_train_states([
            {
                "train_id": "T001",
                "direction": "A_TO_B",
                "movement_phase": "RECEIVING",
                "arrival_track": "1G",
                "receive_throat_cleared": True,
            }
        ])
        self.assertEqual(simulation.get_station_track_codes()["THROAT"], "B")

    def test_side_receive_route_uses_u2s_uus_then_b_after_entry(self):
        routes, simulation = self.make_simulation("B")
        route = routes.establish_route("B", RouteType.SIDE_RECEIVE)

        simulation.update_all_track_codes()
        self.assertEqual(simulation.track_circuits["G35"].signal_code, "U2S")
        self.assertEqual(simulation.track_circuits["G36"].signal_code, "U2S")
        self.assertEqual(simulation.track_circuits["G37"].signal_code, "UUS")
        self.assertEqual(simulation.track_circuits["G38"].signal_code, "UUS")
        self.assertEqual(
            simulation.get_station_track_codes(),
            {"1G": "HU", "3G": "HU", "THROAT": "HU"},
        )

        routes.lock_route(route.route_id, "T001")
        simulation.set_train_states([
            {
                "train_id": "T001",
                "direction": "A_TO_B",
                "movement_phase": "RECEIVING",
                "arrival_track": "3G",
            }
        ])
        simulation.update_all_track_codes()

        self.assertEqual(simulation.get_station_track_codes()["3G"], "HU")
        self.assertEqual(simulation.get_station_track_codes()["THROAT"], "HU")

        simulation.set_train_states([
            {
                "train_id": "T001",
                "direction": "A_TO_B",
                "movement_phase": "RECEIVING",
                "arrival_track": "3G",
                "receive_throat_cleared": True,
            }
        ])
        self.assertEqual(simulation.get_station_track_codes()["THROAT"], "B")

    def test_side_receive_opens_boundary_double_yellow_and_keeps_inner_red(self):
        cases = (
            ("B", "A_TO_B", "X", "X3"),
            ("A", "B_TO_A", "SN", "S3"),
        )
        for station, direction, boundary, inner in cases:
            with self.subTest(station=station):
                routes, simulation = self.make_simulation(station)
                simulation.set_direction(direction)
                routes.establish_route(station, RouteType.SIDE_RECEIVE)

                aspects = simulation.get_station_signal_aspects()

                self.assertEqual(aspects[boundary], "双黄灯")
                self.assertEqual(aspects[inner], "红灯")

    def test_departure_station_codes_follow_no_route_main_and_side_rules(self):
        routes, simulation = self.make_simulation("A")
        simulation.track_circuits["G01"].set_track_code("L4")

        self.assertEqual(
            simulation.get_station_track_codes(),
            {"1G": "HU", "3G": "HU", "THROAT": "B"},
        )

        main = routes.establish_route("A", RouteType.MAIN_DEPART)
        self.assertEqual(
            simulation.get_station_track_codes(),
            {"1G": "L5", "3G": "HU", "THROAT": "L4"},
        )
        routes.release_route(main.route_id)

        routes.establish_route("A", RouteType.SIDE_DEPART)
        self.assertEqual(
            simulation.get_station_track_codes(),
            {"1G": "HU", "3G": "UUS", "THROAT": "L4"},
        )
        aspects = simulation.get_station_signal_aspects()
        self.assertEqual(aspects["X3"], "L灯")
        self.assertEqual(aspects["SN"], "绿灯")

    def test_main_departure_track_code_is_one_step_above_throat_code(self):
        upgrades = {
            "HU": "U",
            "U": "LU",
            "LU": "L",
            "L": "L2",
            "L2": "L3",
            "L3": "L4",
            "L4": "L5",
            "L5": "L5",
        }
        for throat_code, track_code in upgrades.items():
            with self.subTest(throat_code=throat_code):
                routes, simulation = self.make_simulation("A")
                simulation.track_circuits["G01"].set_track_code(throat_code)
                routes.establish_route("A", RouteType.MAIN_DEPART)

                codes = simulation.get_station_track_codes()

                self.assertEqual(codes["THROAT"], throat_code)
                self.assertEqual(codes["1G"], track_code)

    def test_station_signal_aspects_follow_active_route_and_track_codes(self):
        cases = (
            ("A", "A_TO_B", RouteType.MAIN_DEPART, {"X1": "绿灯", "SN": "黄灯"}),
            ("A", "A_TO_B", RouteType.SIDE_DEPART, {"X3": "L灯", "SN": "黄灯"}),
            ("A", "B_TO_A", RouteType.MAIN_RECEIVE, {"SN": "黄灯", "S1": "绿灯"}),
            ("A", "B_TO_A", RouteType.SIDE_RECEIVE, {"SN": "双黄灯"}),
            ("B", "A_TO_B", RouteType.MAIN_RECEIVE, {"X": "黄灯", "X1": "绿灯"}),
            ("B", "A_TO_B", RouteType.SIDE_RECEIVE, {"X": "双黄灯"}),
            ("B", "B_TO_A", RouteType.MAIN_DEPART, {"S1": "绿灯", "S": "黄灯"}),
            ("B", "B_TO_A", RouteType.SIDE_DEPART, {"S3": "L灯", "S": "黄灯"}),
        )
        station_codes = {"1G": "L5", "3G": "UUS", "THROAT": "U"}

        for station, direction, route_type, expected_open in cases:
            with self.subTest(station=station, route_type=route_type):
                routes, simulation = self.make_simulation(station)
                simulation.set_direction(direction)
                routes.establish_route(station, route_type)
                with patch.object(
                    simulation,
                    "get_station_track_codes",
                    return_value=station_codes,
                ):
                    aspects = simulation.get_station_signal_aspects()

                self.assertEqual(
                    {name: aspect for name, aspect in aspects.items() if aspect != "红灯"},
                    expected_open,
                )

    def test_station_signal_aspects_fail_safe_for_wrong_direction_and_occupied_exit(self):
        routes, simulation = self.make_simulation("A")
        routes.establish_route("A", RouteType.MAIN_DEPART)
        station_codes = {"1G": "L5", "3G": "UUS", "THROAT": "L5"}

        simulation.set_direction("B_TO_A")
        with patch.object(simulation, "get_station_track_codes", return_value=station_codes):
            wrong_direction = simulation.get_station_signal_aspects()

        simulation.set_direction("A_TO_B")
        simulation.track_circuits["G01"].occupy()
        with patch.object(simulation, "get_station_track_codes", return_value=station_codes):
            occupied_exit = simulation.get_station_signal_aspects()

        self.assertTrue(all(aspect == "红灯" for aspect in wrong_direction.values()))
        self.assertTrue(all(aspect == "红灯" for aspect in occupied_exit.values()))

    def test_interval_signal_aspects_use_most_restrictive_protected_code(self):
        _, simulation = self.make_simulation("A")
        simulation.set_direction("A_TO_B")
        for code, track_code in (
            ("G01", "L5"),
            ("G02", "L3"),
            ("G03", "L5"),
            ("G04", "LU"),
            ("G05", "L5"),
            ("G06", "U"),
            ("G07", "L5"),
            ("G08", "HU"),
        ):
            simulation.track_circuits[code].set_track_code(track_code)

        aspects = simulation.get_interval_signal_aspects()

        self.assertEqual(aspects["S01"], "绿灯")
        self.assertEqual(aspects["S02"], "黄绿灯")
        self.assertEqual(aspects["S03"], "黄灯")
        self.assertEqual(aspects["S04"], "红灯")

    def test_interval_signal_at_right_endpoint_uses_current_left_block_code(self):
        _, simulation = self.make_simulation("A")
        simulation.set_direction("A_TO_B")
        for code in ("G01", "G02"):
            simulation.track_circuits[code].set_track_code("LU")
        for code in ("G03", "G04"):
            simulation.track_circuits[code].set_track_code("HU")

        aspects = simulation.get_interval_signal_aspects()

        self.assertEqual(aspects["S01"], "黄绿灯")

    def test_interval_signal_aspects_fail_safe_for_unknown_code_and_direction(self):
        _, simulation = self.make_simulation("A")
        simulation.set_direction("A_TO_B")
        simulation.track_circuits["G01"].set_track_code("INVALID")
        simulation.track_circuits["G03"].set_track_code("INVALID")

        aspects = simulation.get_interval_signal_aspects()

        self.assertEqual(aspects["S01"], "红灯")
        self.assertEqual(aspects["S02"], "红灯")

        simulation.set_direction("B_TO_A")
        reverse_aspects = simulation.get_interval_signal_aspects()
        self.assertEqual(set(reverse_aspects.values()), {"红灯"})

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
        self.assertEqual(with_route, "L")

    def test_station_track_codes_follow_route_type(self):
        cases = (
            (RouteType.MAIN_DEPART, "1G", "L5"),
            (RouteType.SIDE_DEPART, "3G", "UUS"),
            (RouteType.MAIN_RECEIVE, "1G", "HU"),
            (RouteType.SIDE_RECEIVE, "3G", "HU"),
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
            {"1G": "HU", "3G": "HU", "THROAT": "B"},
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
