import unittest

from models.train import Train


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


if __name__ == "__main__":
    unittest.main()
