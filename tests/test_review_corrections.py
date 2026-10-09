import unittest

from services.simulation_service import SimulationService
from services.temporary_speed_service import TemporarySpeedService
from services.train_service import TrainService


class IntervalModelCorrectionTest(unittest.TestCase):
    def test_interval_has_38_track_sections_in_19_blocks(self):
        simulation = SimulationService("A")
        train_service = TrainService(simulation)

        self.assertEqual(len(simulation.track_circuits), 38)
        self.assertEqual(train_service.get_track_order("A_TO_B")[0], "G01")
        self.assertEqual(train_service.get_track_order("A_TO_B")[-1], "G38")
        self.assertEqual(len(train_service.get_track_order("A_TO_B")), 38)

        block_pairs = simulation.get_block_section_pairs()
        self.assertEqual(len(block_pairs), 19)
        self.assertEqual(block_pairs["BS01"], ("G01", "G02"))
        self.assertEqual(block_pairs["BS19"], ("G37", "G38"))

    def test_clear_all_trains_preserves_clock_independent_state(self):
        simulation = SimulationService("A")
        train_service = TrainService(simulation)
        train = train_service.create_train()
        train.enter_track("G01")
        train_service.waiting_queue.append(train)
        simulation.track_circuits["G01"].occupy()

        train_service.clear_all_trains()

        self.assertEqual(train_service.trains, {})
        self.assertEqual(train_service.waiting_queue, [])
        self.assertTrue(all(not track.occupied for track in simulation.track_circuits.values()))


class TemporarySpeedServiceTest(unittest.TestCase):
    def setUp(self):
        self.sections = [f"G{i:02d}" for i in range(1, 39)]
        self.service = TemporarySpeedService(self.sections)

    def test_set_range_and_query_speed(self):
        restriction = self.service.set_restriction("G05", "G08", 80)

        self.assertEqual(self.service.speed_for("G04"), None)
        self.assertEqual(self.service.speed_for("G05"), 80)
        self.assertEqual(self.service.speed_for("G08"), 80)
        self.assertEqual(restriction["start_section"], "G05")

    def test_overlapping_restrictions_take_lower_speed_and_can_cancel(self):
        first = self.service.set_restriction("G05", "G10", 120)
        second = self.service.set_restriction("G08", "G12", 80)

        self.assertEqual(self.service.speed_for("G09"), 80)
        self.assertTrue(self.service.cancel_restriction(second["id"]))
        self.assertEqual(self.service.speed_for("G09"), 120)
        self.assertEqual(len(self.service.active_restrictions()), 1)
        self.assertEqual(self.service.active_restrictions()[0]["id"], first["id"])

    def test_reversed_or_unknown_range_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.set_restriction("G10", "G05", 80)
        with self.assertRaises(ValueError):
            self.service.set_restriction("G00", "G05", 80)


if __name__ == "__main__":
    unittest.main()
