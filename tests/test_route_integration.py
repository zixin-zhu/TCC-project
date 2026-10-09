import unittest

from models.route import RouteState, RouteType
from services.route_service import RouteService
from services.simulation_service import SimulationService
from services.train_service import TrainService


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

    def test_departure_route_releases_after_train_enters_second_section(self):
        route = self.routes.establish_route("A", RouteType.SIDE_DEPART)
        train = self.trains.add_waiting_train("SIDE")
        self.assertTrue(self.trains.dispatch_train(train))

        train.position = self.trains.default_track_length + 5
        self.trains.handle_track_transition(train)

        self.assertEqual(train.current_track, "G02")
        self.assertIsNone(train.route_id)
        self.assertNotIn(route, self.routes.active_routes())

    def test_receive_route_locks_at_terminal_section_and_releases_on_arrival(self):
        self.simulation.set_direction("B_TO_A")
        departure = self.routes.establish_route("B", RouteType.SIDE_DEPART)
        receive = self.routes.establish_route("A", RouteType.SIDE_RECEIVE)
        train = self.trains.add_waiting_train("SIDE", "SIDE")
        self.assertTrue(self.trains.dispatch_train(train))

        train.position = self.trains.default_track_length + 1
        self.trains.handle_track_transition(train)
        self.assertNotIn(departure, self.routes.active_routes())

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
        self.assertNotIn(receive, self.routes.active_routes())


if __name__ == "__main__":
    unittest.main()
