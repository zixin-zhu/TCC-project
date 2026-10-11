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


class MultiTrainLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.routes = RouteService()
        self.simulation = SimulationService("A", route_service=self.routes)
        self.service = TrainService(self.simulation, route_service=self.routes)

    def establish_main_routes(self):
        departure = self.routes.establish_route("A", RouteType.MAIN_DEPART)
        receive = self.routes.establish_route("B", RouteType.MAIN_RECEIVE)
        return departure, receive

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
        self.assertEqual(selected.current_track, "G01")
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
        front.current_track = "G02"
        front.position = 100.0
        self.routes.unlock_route(departure.route_id)
        front.route_id = None
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
        departure, _ = self.establish_main_routes()
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
        for train, max_speed, modes in (
            (running, 200.0, ("MAIN", "MAIN")),
            (stopped, 160.0, ("SIDE", "MAIN")),
            (arrived, 250.0, ("MAIN", "SIDE")),
        ):
            self.assertEqual(train.status, "WAITING")
            self.assertIsNone(train.current_track)
            self.assertEqual(train.max_speed, max_speed)
            self.assertEqual((train.departure_mode, train.arrival_mode), modes)
            self.assertIn(train.train_id, self.service.waiting_queue)
        self.assertEqual(departure.state, RouteState.ESTABLISHED)
        self.assertIsNone(departure.train_id)
        self.assertEqual(self.service.waiting_queue[0], waiting.train_id)

    def test_simulation_engine_tracks_user_pause_state(self):
        engine = SimulationEngine(self.service)

        engine.start()
        self.assertFalse(engine.is_paused)
        engine.pause()
        self.assertTrue(engine.is_paused)


if __name__ == "__main__":
    unittest.main()
