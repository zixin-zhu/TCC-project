import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from models.route import RouteState, RouteType
from models.train import Train
from services.operation_policy import OperationRuleError
from services.route_service import RouteService
from services.simulation_engine import SimulationEngine
from services.simulation_service import SimulationService
from services.train_service import TrainService
from ui.tcc_overview import TccOverviewWidget


APP = QApplication.instance() or QApplication(sys.argv[:1])


class MultiTrainModelTest(unittest.TestCase):
    def test_train_max_speed_options_and_status_snapshot(self):
        train = Train("T001")

        self.assertEqual(
            train.ALLOWED_MAX_SPEEDS,
            (80, 120, 160, 200, 250, 300, 350),
        )
        train.set_max_speed(250)

        self.assertEqual(train.max_speed, 250.0)
        self.assertEqual(train.get_status()["max_speed"], 250.0)

    def test_invalid_max_speed_is_rejected_with_allowed_values(self):
        train = Train("T001")

        with self.assertRaises(ValueError) as raised:
            train.set_max_speed(100)

        message = str(raised.exception)
        self.assertIn("100", message)
        self.assertIn("80、120、160、200、250、300、350", message)
        self.assertEqual(train.max_speed, 120.0)

    def test_lowering_max_speed_changes_target_not_current_speed(self):
        train = Train("T001")
        train.speed = 160.0
        train.block_speed = 350.0
        train.line_speed = 350.0
        train.active_balise_speed = 350.0
        train.temporary_speed = 350.0

        train.set_max_speed(80)
        train.calculate_target_speed()

        self.assertEqual(train.target_speed, 80.0)
        self.assertEqual(train.speed, 160.0)

    def test_reset_preserves_configuration_and_max_speed(self):
        train = Train("T001", "A_TO_B", "SIDE", "MAIN")
        train.set_max_speed(200)
        train.enter_track("G01")
        train.speed = 45.0

        train.reset_to_departure()

        self.assertEqual(
            (train.departure_mode, train.arrival_mode),
            ("SIDE", "MAIN"),
        )
        self.assertEqual((train.station_track, train.arrival_track), ("3G", "1G"))
        self.assertEqual(train.max_speed, 200.0)
        self.assertEqual(train.status, "WAITING")
        self.assertIsNone(train.current_track)
        self.assertEqual(train.position, 0.0)
        self.assertEqual(train.speed, 0.0)

    def test_full_reset_clears_route_configuration_but_preserves_max_speed(self):
        train = Train("T001", "A_TO_B", "SIDE", "MAIN")
        train.set_max_speed(250)
        train.configure_departure_route("A-SIDE-DEPART-001", "3G")
        train.configure_receive_route("B-MAIN-RECEIVE-002", "1G")
        train.enter_track("G10")

        train.reset_to_departure(preserve_configuration=False)

        self.assertEqual(train.max_speed, 250.0)
        self.assertIsNone(train.departure_mode)
        self.assertIsNone(train.arrival_mode)
        self.assertIsNone(train.station_track)
        self.assertIsNone(train.arrival_track)
        self.assertIsNone(train.route_id)
        self.assertIsNone(train.departure_route_id)
        self.assertIsNone(train.receive_route_id)


class MultiTrainLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.routes = RouteService()
        self.simulation = SimulationService("A", route_service=self.routes)
        self.service = TrainService(self.simulation, route_service=self.routes)

    def establish_main_routes(self):
        departure = self.routes.establish_route("A", RouteType.MAIN_DEPART)
        receive = self.routes.establish_route("B", RouteType.MAIN_RECEIVE)
        return departure, receive

    def test_dispatch_starts_at_station_before_entrance_section(self):
        departure = self.routes.establish_route("A", RouteType.MAIN_DEPART)
        selected = self.service.add_waiting_train()

        self.service.dispatch_selected_train(selected.train_id, 120)

        self.assertEqual(selected.status, "RUNNING")
        self.assertEqual(selected.movement_phase, "DEPARTING")
        self.assertIsNone(selected.current_track)
        self.assertEqual(selected.station_position, 0.0)
        self.assertEqual(departure.state, RouteState.LOCKED)
        self.assertEqual(departure.train_id, selected.train_id)

    def test_departing_enters_g01_or_g38_only_after_station_boundary(self):
        cases = (
            ("A_TO_B", "A", "G01", "B01"),
            ("B_TO_A", "B", "G38", "B38"),
        )
        for direction, station, entrance, balise in cases:
            with self.subTest(direction=direction):
                routes = RouteService()
                simulation = SimulationService("A", route_service=routes)
                simulation.set_direction(direction)
                service = TrainService(simulation, route_service=routes)
                departure = routes.establish_route(
                    station,
                    RouteType.MAIN_DEPART,
                )
                train = service.add_waiting_train()
                service.dispatch_selected_train(train.train_id, 120)
                train.station_position = 2980.0
                train.position = 2980.0
                train.speed = 36.0
                train.target_speed = 36.0

                service.update_train(train, 1.0)
                service.sync_track_circuits()

                self.assertEqual(train.movement_phase, "DEPARTING")
                self.assertIsNone(train.current_track)
                self.assertFalse(simulation.track_circuits[entrance].occupied)
                self.assertIn(departure, routes.active_routes())

                service.update_train(train, 2.0)
                service.sync_track_circuits()

                self.assertEqual(train.movement_phase, "INTERVAL_RUNNING")
                self.assertEqual(train.current_track, entrance)
                self.assertAlmostEqual(train.position, 10.0)
                self.assertEqual(train.last_balise, balise)
                self.assertTrue(simulation.track_circuits[entrance].occupied)
                self.assertNotIn(departure, routes.active_routes())
                self.assertIsNone(train.departure_route_id)

    def test_dispatch_requires_only_departure_route_and_derives_side_mode(self):
        departure = self.routes.establish_route("A", RouteType.SIDE_DEPART)
        selected = self.service.add_waiting_train()

        dispatched = self.service.dispatch_selected_train(
            selected.train_id,
            160,
        )

        self.assertIs(dispatched, selected)
        self.assertEqual(selected.status, "RUNNING")
        self.assertIsNone(selected.current_track)
        self.assertEqual(selected.departure_mode, "SIDE")
        self.assertEqual(selected.station_track, "3G")
        self.assertIsNone(selected.arrival_mode)
        self.assertEqual(selected.movement_phase, "DEPARTING")
        self.assertEqual(selected.departure_route_id, departure.route_id)
        self.assertIn(departure, self.routes.active_routes())

    def test_reverse_dispatch_uses_b_station_departure_route(self):
        self.simulation.set_direction("B_TO_A")
        departure = self.routes.establish_route("B", RouteType.MAIN_DEPART)
        selected = self.service.add_waiting_train()

        self.service.dispatch_selected_train(selected.train_id, 120)

        self.assertEqual(selected.direction, "B_TO_A")
        self.assertIsNone(selected.current_track)
        self.assertEqual(selected.movement_phase, "DEPARTING")
        self.assertEqual(selected.departure_mode, "MAIN")
        self.assertIn(departure, self.routes.active_routes())

    def test_next_train_requires_a_rebuilt_departure_route(self):
        self.routes.establish_route("A", RouteType.MAIN_DEPART)
        first = self.service.add_waiting_train()
        second = self.service.add_waiting_train()
        self.service.dispatch_selected_train(first.train_id, 120)
        first.station_position = self.service.STATION_EXIT_POSITION
        self.service.handle_departure_transition(first)
        first.current_track = "G03"
        self.service.sync_track_circuits()

        with self.assertRaises(OperationRuleError) as raised:
            self.service.dispatch_selected_train(second.train_id, 120)

        self.assertIn("发车进路尚未建立", raised.exception.format_message())
        self.assertEqual(second.status, "WAITING")

    def test_receive_route_wakes_only_frontmost_train_without_early_lock(self):
        rear = self.service.create_train()
        rear.enter_track("G20")
        front = self.service.create_train()
        front.enter_track("G30")
        receive = self.routes.establish_route("B", RouteType.SIDE_RECEIVE)

        assigned = self.service.assign_receive_route(receive)

        self.assertIs(assigned, front)
        self.assertEqual(receive.state, RouteState.ESTABLISHED)
        self.assertEqual(receive.train_id, front.train_id)
        self.assertIsNone(front.receive_route_id)
        self.assertEqual(self.service.receive_mode_for_train(front), "SIDE")
        self.assertIsNone(rear.receive_route_id)
        self.assertEqual(self.service.receive_mode_for_train(rear), "SIDE")

    def test_receive_route_without_an_active_candidate_remains_established(self):
        self.service.add_waiting_train()
        receive = self.routes.establish_route("B", RouteType.MAIN_RECEIVE)

        assigned = self.service.assign_receive_route(receive)

        self.assertIsNone(assigned)
        self.assertEqual(receive.state, RouteState.ESTABLISHED)
        self.assertIsNone(receive.train_id)

    def test_dispatch_selected_train_leaves_other_waiting_train_untouched(self):
        departure, _ = self.establish_main_routes()
        first = self.service.add_waiting_train()
        selected = self.service.add_waiting_train()

        dispatched = self.service.dispatch_selected_train(
            selected.train_id,
            "MAIN",
            "MAIN",
            200,
        )

        self.assertIs(dispatched, selected)
        self.assertEqual(selected.status, "RUNNING")
        self.assertIsNone(selected.current_track)
        self.assertEqual(selected.movement_phase, "DEPARTING")
        self.assertEqual(selected.max_speed, 200.0)
        self.assertEqual(first.status, "WAITING")
        self.assertIn(first.train_id, self.service.waiting_queue)
        self.assertNotIn(selected.train_id, self.service.waiting_queue)
        self.assertEqual(departure.state, RouteState.LOCKED)
        self.assertEqual(departure.train_id, selected.train_id)

    def test_failed_dispatch_without_routes_is_atomic(self):
        selected = self.service.add_waiting_train()
        original_queue = list(self.service.waiting_queue)

        with self.assertRaises(OperationRuleError) as raised:
            self.service.dispatch_selected_train(
                selected.train_id,
                "MAIN",
                "MAIN",
                160,
            )

        message = raised.exception.format_message()
        self.assertIn("操作失败", message)
        self.assertIn("当前状态", message)
        self.assertIn("处理建议", message)
        self.assertIn(selected.train_id, message)
        self.assertEqual(selected.status, "WAITING")
        self.assertIsNone(selected.departure_mode)
        self.assertEqual(selected.max_speed, 120.0)
        self.assertEqual(self.service.waiting_queue, original_queue)
        self.assertTrue(
            all(not track.occupied for track in self.simulation.track_circuits.values())
        )

    def test_dispatch_spacing_error_names_front_train_and_section(self):
        departure, _ = self.establish_main_routes()
        front = self.service.add_waiting_train()
        following = self.service.add_waiting_train()
        self.service.dispatch_selected_train(front.train_id, "MAIN", "MAIN", 120)
        front.station_position = self.service.STATION_EXIT_POSITION
        self.service.handle_departure_transition(front)
        front.current_track = "G02"
        front.position = 100.0
        departure = self.routes.establish_route("A", RouteType.MAIN_DEPART)
        self.service.sync_track_circuits()

        with self.assertRaises(OperationRuleError) as raised:
            self.service.dispatch_selected_train(
                following.train_id,
                "MAIN",
                "MAIN",
                120,
            )

        message = raised.exception.format_message()
        self.assertIn(front.train_id, message)
        self.assertIn("G02", message)
        self.assertIn("两个完整轨道区段", message)
        self.assertEqual(following.status, "WAITING")
        self.assertEqual(departure.state, RouteState.ESTABLISHED)
        self.assertEqual(self.service.waiting_queue, [following.train_id])

    def test_pause_resume_and_reset_apply_to_all_dispatched_trains(self):
        departure, receive = self.establish_main_routes()
        waiting = self.service.add_waiting_train()
        running = self.service.create_train("MAIN", "MAIN")
        running.set_max_speed(200)
        running.enter_track("G05")
        stopped = self.service.create_train("SIDE", "MAIN")
        stopped.set_max_speed(160)
        stopped.enter_track("G08")
        stopped.status = "STOPPED"
        arrived = self.service.create_train("MAIN", "SIDE")
        arrived.set_max_speed(250)
        arrived.status = "ARRIVED"
        self.routes.lock_route(departure.route_id, running.train_id)
        running.route_id = departure.route_id
        running.departure_route_id = departure.route_id
        self.routes.lock_route(receive.route_id, stopped.train_id)
        stopped.route_id = receive.route_id
        stopped.receive_route_id = receive.route_id

        paused = self.service.pause_all()
        self.assertEqual([train.train_id for train in paused], [running.train_id])
        self.assertEqual(running.status, "STOPPED")
        self.assertEqual(stopped.status, "STOPPED")

        resumed = self.service.resume_all()
        self.assertEqual(
            {train.train_id for train in resumed},
            {running.train_id, stopped.train_id},
        )
        self.assertEqual(running.status, "RUNNING")
        self.assertEqual(stopped.status, "RUNNING")

        reset = self.service.reset_dispatched_trains()

        self.assertEqual(
            {train.train_id for train in reset},
            {running.train_id, stopped.train_id, arrived.train_id},
        )
        self.assertEqual(waiting.status, "WAITING")
        self.assertEqual(waiting.departure_mode, None)
        for train, max_speed in (
            (running, 200.0),
            (stopped, 160.0),
            (arrived, 250.0),
        ):
            self.assertEqual(train.status, "WAITING")
            self.assertIsNone(train.current_track)
            self.assertEqual(train.max_speed, max_speed)
            self.assertIsNone(train.departure_mode)
            self.assertIsNone(train.arrival_mode)
            self.assertIsNone(train.station_track)
            self.assertIsNone(train.arrival_track)
            self.assertIsNone(train.route_id)
            self.assertIsNone(train.departure_route_id)
            self.assertIsNone(train.receive_route_id)
            self.assertIn(train.train_id, self.service.waiting_queue)
        self.assertEqual(self.routes.active_routes(), [])
        self.assertEqual(self.service.waiting_queue[0], waiting.train_id)

    def test_simulation_engine_tracks_user_pause_state(self):
        engine = SimulationEngine(self.service)

        engine.start()
        self.assertFalse(engine.is_paused)
        engine.pause()
        self.assertTrue(engine.is_paused)


class MultiTrainMovementTest(unittest.TestCase):
    def setUp(self):
        self.routes = RouteService()
        self.simulation = SimulationService("A", route_service=self.routes)
        self.service = TrainService(self.simulation, route_service=self.routes)

    def add_running_train(self, track, position, speed=36.0, direction="A_TO_B"):
        train = self.service.create_train("MAIN", "MAIN")
        train.direction = direction
        train.enter_track(track)
        train.position = position
        train.speed = speed
        train.target_speed = speed
        return train

    def test_movement_snapshot_uses_all_active_trains_and_38_section_order(self):
        forward = self.add_running_train("G03", 250.0)
        reverse = self.add_running_train("G36", 400.0, direction="B_TO_A")

        snapshot = self.service.build_movement_snapshot()

        self.assertEqual(snapshot[forward.train_id]["absolute_position"], 2250.0)
        self.assertEqual(snapshot[reverse.train_id]["absolute_position"], 2400.0)
        self.assertEqual(snapshot[reverse.train_id]["track"], "G36")

    def test_two_running_trains_advance_in_the_same_tick(self):
        rear = self.add_running_train("G01", 100.0)
        front = self.add_running_train("G05", 200.0)

        self.service.update_all(1.0)

        self.assertGreater(rear.position, 100.0)
        self.assertGreater(front.position, 200.0)
        self.assertEqual(rear.status, "RUNNING")
        self.assertEqual(front.status, "RUNNING")

    def test_each_running_train_advances_once_per_update_all_tick(self):
        rear = self.add_running_train("G01", 100.0)
        front = self.add_running_train("G05", 200.0)

        self.service.update_all(1.0)

        self.assertAlmostEqual(rear.position, 110.5)
        self.assertAlmostEqual(front.position, 210.5)

    def test_adjacent_boundary_crossing_never_overlaps_or_overtakes(self):
        rear = self.add_running_train("G01", 999.0, speed=120.0)
        front = self.add_running_train("G02", 999.0, speed=120.0)

        self.service.update_all(1.0)

        occupied = [
            train.current_track
            for train in (rear, front)
            if train.current_track is not None
        ]
        self.assertEqual(len(occupied), len(set(occupied)))
        self.assertLess(
            self.service.get_absolute_position(rear),
            self.service.get_absolute_position(front),
        )

    def test_live_max_speed_reduces_target_without_instant_speed_jump(self):
        train = self.add_running_train("G10", 100.0, speed=160.0)
        train.set_max_speed(250)
        self.service.update_train_speed_limit(train)
        speed_before_change = train.speed

        train.set_max_speed(80)
        self.service.update_train_speed_limit(train)

        self.assertLessEqual(train.target_speed, 80.0)
        self.assertEqual(train.speed, speed_before_change)
        self.service.update_all(1.0)
        self.assertLess(train.speed, speed_before_change)
        self.assertGreater(train.speed, 80.0)

    def test_globally_paused_trains_do_not_move_if_update_is_called(self):
        first = self.add_running_train("G03", 200.0)
        second = self.add_running_train("G08", 300.0)
        self.service.pause_all()
        original = {
            first.train_id: first.position,
            second.train_id: second.position,
        }

        self.service.update_all(5.0)

        self.assertEqual(first.position, original[first.train_id])
        self.assertEqual(second.position, original[second.train_id])
        self.assertEqual(first.status, "STOPPED")
        self.assertEqual(second.status, "STOPPED")

    def test_multiple_occupancies_generate_independent_protection_codes(self):
        self.routes.establish_route("A", RouteType.MAIN_DEPART)
        self.add_running_train("G03", 100.0)
        self.add_running_train("G08", 100.0)

        self.service.sync_track_circuits()

        self.assertEqual(self.simulation.track_circuits["G03"].signal_code, "U")
        self.assertEqual(self.simulation.track_circuits["G04"].signal_code, "U")
        self.assertEqual(self.simulation.track_circuits["G07"].signal_code, "L5")
        self.assertEqual(self.simulation.track_circuits["G08"].signal_code, "L5")
        self.assertEqual(self.simulation.track_circuits["G02"].signal_code, "HU")
        self.assertEqual(self.simulation.track_circuits["G01"].signal_code, "HU")
        self.assertEqual(self.simulation.track_circuits["G06"].signal_code, "HU")
        self.assertEqual(self.simulation.signal_states["S01"], "红灯")

    def test_train_cannot_cross_red_block_exit_signal(self):
        cases = (
            ("G34", "G36", "S17"),
            ("G36", "G38", "S18"),
        )
        for current_track, occupied_track, signal_id in cases:
            with self.subTest(signal_id=signal_id):
                routes = RouteService()
                simulation = SimulationService("A", route_service=routes)
                service = TrainService(simulation, route_service=routes)
                train = service.create_train("MAIN", "MAIN")
                train.enter_track(current_track)
                train.position = service.default_track_length + 25.0
                train.speed = 45.0
                train.target_speed = 45.0
                blocker = service.create_train("MAIN", "MAIN")
                blocker.enter_track(occupied_track)
                blocker.position = 100.0
                blocker.speed = 0.0
                blocker.target_speed = 0.0
                blocker.status = "STOPPED"
                service.sync_track_circuits()

                self.assertEqual(
                    simulation.get_interval_signal_aspects()[signal_id],
                    "红灯",
                )
                service.handle_track_transition(train)

                self.assertEqual(train.current_track, current_track)
                self.assertLess(train.position, service.default_track_length)
                self.assertEqual(train.status, "STOPPED")
                self.assertEqual(train.movement_phase, "WAITING_SIGNAL")
                self.assertEqual(train.stop_signal_id, signal_id)

    def test_zero_speed_before_red_signal_uses_signal_waiting_state(self):
        train = self.add_running_train("G36", 900.0, speed=0.0)
        train.block_code = "HU"
        blocker = self.add_running_train("G38", 100.0, speed=0.0)
        blocker.status = "STOPPED"
        self.service.sync_track_circuits()

        self.service.update_train(train, 0.0)

        self.assertEqual(train.status, "STOPPED")
        self.assertEqual(train.movement_phase, "WAITING_SIGNAL")
        self.assertEqual(train.stop_signal_id, "S18")

    def test_receive_route_reserved_for_front_train_keeps_rear_at_x(self):
        front = self.add_running_train("G38", 100.0, speed=0.0)
        rear = self.add_running_train("G37", 900.0, speed=0.0)
        rear.block_code = "HU"
        receive = self.routes.establish_route("B", RouteType.MAIN_RECEIVE)
        receive.train_id = front.train_id
        self.service.sync_track_circuits()

        self.service.update_train(rear, 0.0)

        self.assertEqual(rear.status, "STOPPED")
        self.assertEqual(rear.movement_phase, "WAITING_SIGNAL")
        self.assertEqual(rear.stop_signal_id, "X")

    def test_signal_waiting_train_resumes_only_after_signal_clears(self):
        train = self.add_running_train("G36", 999.9, speed=0.0)
        blocker = self.add_running_train("G38", 100.0, speed=0.0)
        blocker.status = "STOPPED"
        train.wait_at_signal("S18")
        self.service.sync_track_circuits()

        self.service.try_resume_stopped_trains()
        self.assertEqual(train.status, "STOPPED")

        blocker.leave_section()
        self.service.sync_track_circuits()
        self.service.try_resume_stopped_trains()

        self.assertEqual(train.status, "RUNNING")
        self.assertEqual(train.movement_phase, "INTERVAL_RUNNING")
        self.assertIsNone(train.stop_signal_id)

    def test_global_resume_does_not_override_a_red_signal_stop(self):
        train = self.add_running_train("G36", 999.9, speed=0.0)
        train.wait_at_signal("S18")

        resumed = self.service.resume_all()

        self.assertNotIn(train, resumed)
        self.assertEqual(train.status, "STOPPED")
        self.assertEqual(train.movement_phase, "WAITING_SIGNAL")


class MultiTrainStationMovementTest(unittest.TestCase):
    def setUp(self):
        self.routes = RouteService()
        self.simulation = SimulationService("A", route_service=self.routes)
        self.service = TrainService(self.simulation, route_service=self.routes)

    def make_terminal_train(self, direction="A_TO_B"):
        train = self.service.create_train()
        train.direction = direction
        terminal = "G38" if direction == "A_TO_B" else "G01"
        train.enter_track(terminal)
        train.position = self.service.default_track_length + 5.0
        train.speed = 45.0
        train.target_speed = 45.0
        return train

    def test_train_waits_at_destination_signal_without_receive_route(self):
        for direction, terminal in (("A_TO_B", "G38"), ("B_TO_A", "G01")):
            with self.subTest(direction=direction):
                train = self.make_terminal_train(direction)

                self.service.handle_track_transition(train)
                stopped_position = train.position
                self.service.update_all(10.0)

                self.assertEqual(train.status, "STOPPED")
                self.assertEqual(train.movement_phase, "WAITING_RECEIVE_ROUTE")
                self.assertEqual(train.current_track, terminal)
                self.assertEqual(train.position, stopped_position)
                self.assertIn("接车进路尚未建立", train.receive_waiting_reason)

    def test_new_receive_route_resumes_only_the_frontmost_waiting_train(self):
        rear = self.service.create_train()
        rear.enter_track("G36")
        rear.status = "STOPPED"
        front = self.make_terminal_train()
        self.service.handle_track_transition(front)
        receive = self.routes.establish_route("B", RouteType.MAIN_RECEIVE)

        assigned = self.service.assign_receive_route(receive)

        self.assertIs(assigned, front)
        self.assertEqual(front.status, "RUNNING")
        self.assertIsNone(front.arrival_mode)
        self.assertEqual(self.service.receive_mode_for_train(front), "MAIN")
        self.assertIsNone(rear.receive_route_id)
        self.assertEqual(rear.status, "STOPPED")

    def test_receive_route_releases_at_inner_signal_then_train_exits_station(self):
        cases = (
            ("A_TO_B", "B", RouteType.MAIN_RECEIVE, "MAIN"),
            ("A_TO_B", "B", RouteType.SIDE_RECEIVE, "SIDE"),
            ("B_TO_A", "A", RouteType.MAIN_RECEIVE, "MAIN"),
            ("B_TO_A", "A", RouteType.SIDE_RECEIVE, "SIDE"),
        )
        for direction, station, route_type, arrival_mode in cases:
            with self.subTest(direction=direction, route_type=route_type):
                routes = RouteService()
                simulation = SimulationService("A", route_service=routes)
                service = TrainService(simulation, route_service=routes)
                train = service.create_train()
                train.direction = direction
                terminal = "G38" if direction == "A_TO_B" else "G01"
                train.enter_track(terminal)
                route = routes.establish_route(station, route_type)
                service.assign_receive_route(route)
                train.position = service.default_track_length + 10.0

                service.handle_track_transition(train)
                self.assertEqual(train.movement_phase, "RECEIVING")
                self.assertEqual(train.arrival_mode, arrival_mode)
                self.assertIn(route, routes.active_routes())

                train.station_position = service.RECEIVE_RELEASE_POSITION - 0.1
                service.handle_station_transition(train)
                self.assertIn(route, routes.active_routes())

                train.station_position = service.RECEIVE_RELEASE_POSITION + 0.1
                service.handle_station_transition(train)
                self.assertNotIn(route, routes.active_routes())
                self.assertIsNone(train.receive_route_id)
                self.assertEqual(train.movement_phase, "STATION_RUNNING")
                self.assertEqual(train.status, "RUNNING")

                train.station_position = service.STATION_EXIT_POSITION + 0.1
                service.handle_station_transition(train)
                self.assertEqual(train.status, "ARRIVED")
                self.assertEqual(train.movement_phase, "ARRIVED")


class RouteLifecycleEndToEndTest(unittest.TestCase):
    def make_system(self, direction):
        routes = RouteService()
        simulation = SimulationService("A", route_service=routes)
        simulation.set_direction(direction)
        service = TrainService(simulation, route_service=routes)
        return routes, service

    def move_train_to_terminal(self, service, train):
        terminal = "G38" if train.direction == "A_TO_B" else "G01"
        train.current_track = terminal
        train.position = service.default_track_length + 1.0
        train.speed = 45.0
        train.target_speed = 45.0
        service.sync_track_circuits()
        service.handle_track_transition(train)

    def test_two_trains_rebuild_routes_and_leave_station_in_both_directions(self):
        cases = (
            (
                "A_TO_B",
                "A",
                "B",
                RouteType.MAIN_DEPART,
                RouteType.SIDE_DEPART,
                RouteType.MAIN_RECEIVE,
                RouteType.SIDE_RECEIVE,
            ),
            (
                "B_TO_A",
                "B",
                "A",
                RouteType.MAIN_DEPART,
                RouteType.SIDE_DEPART,
                RouteType.MAIN_RECEIVE,
                RouteType.SIDE_RECEIVE,
            ),
        )
        for (
            direction,
            departure_station,
            arrival_station,
            first_departure_type,
            second_departure_type,
            first_receive_type,
            second_receive_type,
        ) in cases:
            with self.subTest(direction=direction):
                routes, service = self.make_system(direction)
                first = service.add_waiting_train()
                second = service.add_waiting_train()

                routes.establish_route(departure_station, first_departure_type)
                service.dispatch_selected_train(first.train_id, 160)
                first.station_position = service.STATION_EXIT_POSITION
                service.handle_departure_transition(first)
                first.current_track = "G03" if direction == "A_TO_B" else "G36"
                first.position = 100.0
                service.sync_track_circuits()

                routes.establish_route(departure_station, second_departure_type)
                service.dispatch_selected_train(second.train_id, 120)
                second.station_position = service.STATION_EXIT_POSITION
                service.handle_departure_transition(second)
                self.assertIsNone(routes.departure_route(departure_station))

                self.move_train_to_terminal(service, first)
                self.assertEqual(first.movement_phase, "WAITING_RECEIVE_ROUTE")
                first_receive = routes.establish_route(
                    arrival_station,
                    first_receive_type,
                )
                self.assertIs(service.assign_receive_route(first_receive), first)
                self.assertIsNone(first.arrival_mode)
                self.assertEqual(service.receive_mode_for_train(first), "MAIN")

                terminal = "G38" if direction == "A_TO_B" else "G01"
                second.current_track = terminal
                second.position = service.default_track_length + 1.0
                second.speed = 45.0
                second.target_speed = 45.0
                service.handle_track_transition(second)
                self.assertEqual(second.movement_phase, "WAITING_RECEIVE_ROUTE")
                self.assertIsNone(second.receive_route_id)

                first.position = service.default_track_length + 1.0
                service.handle_track_transition(first)
                self.assertEqual(first.arrival_mode, "MAIN")
                first.station_position = service.STATION_EXIT_POSITION + 0.1
                service.handle_station_transition(first)
                self.assertEqual(first.status, "ARRIVED")
                self.assertIsNone(routes.receive_route(arrival_station))

                second_receive = routes.establish_route(
                    arrival_station,
                    second_receive_type,
                )
                self.assertIs(service.assign_receive_route(second_receive), second)
                self.assertIsNone(second.arrival_mode)
                self.assertEqual(service.receive_mode_for_train(second), "SIDE")
                self.assertEqual(second.status, "RUNNING")

                second.position = service.default_track_length + 1.0
                service.handle_track_transition(second)
                self.assertEqual(second.arrival_mode, "SIDE")
                second.station_position = service.STATION_EXIT_POSITION + 0.1
                service.handle_station_transition(second)
                self.assertEqual(second.status, "ARRIVED")
                self.assertIsNone(routes.receive_route(arrival_station))

    def test_all_direction_and_track_combinations_depart_from_station_path_and_arrive(self):
        cases = (
            ("A_TO_B", "A", "B", RouteType.MAIN_DEPART, RouteType.MAIN_RECEIVE, "MAIN"),
            ("A_TO_B", "A", "B", RouteType.SIDE_DEPART, RouteType.SIDE_RECEIVE, "SIDE"),
            ("B_TO_A", "B", "A", RouteType.MAIN_DEPART, RouteType.MAIN_RECEIVE, "MAIN"),
            ("B_TO_A", "B", "A", RouteType.SIDE_DEPART, RouteType.SIDE_RECEIVE, "SIDE"),
        )
        for direction, departure_station, arrival_station, departure_type, receive_type, mode in cases:
            with self.subTest(direction=direction, mode=mode):
                routes, service = self.make_system(direction)
                train = service.add_waiting_train()
                waiting = TccOverviewWidget.waiting_marker_contracts(
                    service.get_all_train_status()
                )
                self.assertEqual(len(waiting), 1)
                self.assertEqual(waiting[0]["label"], "x1")

                routes.establish_route(departure_station, departure_type)
                service.dispatch_selected_train(train.train_id, 160)
                self.assertEqual(train.movement_phase, "DEPARTING")
                self.assertIsNone(train.current_track)
                self.assertTrue(
                    all(not track.occupied for track in service.simulation.track_circuits.values())
                )

                train.station_position = service.STATION_EXIT_POSITION
                service.handle_departure_transition(train)
                entrance = "G01" if direction == "A_TO_B" else "G38"
                terminal = "G38" if direction == "A_TO_B" else "G01"
                self.assertEqual(train.current_track, entrance)

                train.current_track = terminal
                train.position = service.default_track_length + 1.0
                service.sync_track_circuits()
                service.handle_track_transition(train)
                self.assertEqual(train.movement_phase, "WAITING_RECEIVE_ROUTE")

                receive = routes.establish_route(arrival_station, receive_type)
                self.assertIs(service.assign_receive_route(receive), train)
                train.position = service.default_track_length + 1.0
                service.handle_track_transition(train)
                self.assertEqual(train.movement_phase, "RECEIVING")
                self.assertEqual(train.arrival_mode, mode)
                marker = TccOverviewWidget.train_marker_contract(train.get_status())
                self.assertEqual(marker["region"], "STATION")
                self.assertEqual(marker["track"], "1G" if mode == "MAIN" else "3G")

                train.station_position = service.RECEIVE_RELEASE_POSITION + 0.1
                service.handle_station_transition(train)
                self.assertNotIn(receive, routes.active_routes())
                train.station_position = service.STATION_EXIT_POSITION + 0.1
                service.handle_station_transition(train)
                self.assertEqual(train.status, "ARRIVED")

    def test_multiple_trains_update_codes_signals_and_waiting_count_together(self):
        routes, service = self.make_system("A_TO_B")
        first = service.create_train()
        first.enter_track("G05")
        first.position = 100.0
        first.speed = first.target_speed = 36.0
        second = service.create_train()
        second.enter_track("G20")
        second.position = 200.0
        second.speed = second.target_speed = 36.0
        service.add_waiting_train()
        service.add_waiting_train()
        service.sync_track_circuits()

        waiting = TccOverviewWidget.waiting_marker_contracts(
            service.get_all_train_status()
        )
        before = {first.train_id: first.position, second.train_id: second.position}
        occupied_aspects = service.simulation.get_interval_signal_aspects()
        service.update_all(1.0)

        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["label"], "x2")
        self.assertAlmostEqual(first.position - before[first.train_id], 10.5)
        self.assertAlmostEqual(second.position - before[second.train_id], 10.5)
        self.assertEqual(occupied_aspects["S02"], "红灯")

        first.current_track = "G10"
        first.position = 100.0
        service.sync_track_circuits()
        cleared_aspects = service.simulation.get_interval_signal_aspects()
        self.assertNotEqual(cleared_aspects["S02"], "红灯")

        service.reset_dispatched_trains()
        reset_waiting = TccOverviewWidget.waiting_marker_contracts(
            service.get_all_train_status()
        )
        station_aspects = service.simulation.get_station_signal_aspects()
        self.assertEqual(len(reset_waiting), 1)
        self.assertEqual(reset_waiting[0]["label"], "x4")
        self.assertTrue(all(aspect == "红灯" for aspect in station_aspects.values()))


if __name__ == "__main__":
    unittest.main()
