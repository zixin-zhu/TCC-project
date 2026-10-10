import unittest

from models.route import RouteType
from models.train import Train
from services.operation_policy import OperationPolicy, OperationRuleError
from services.route_service import RouteService


class OperationPolicyTest(unittest.TestCase):
    def test_a_to_b_only_allows_a_departure_and_b_receive(self):
        allowed = (
            ("A", RouteType.MAIN_DEPART),
            ("A", RouteType.SIDE_DEPART),
            ("B", RouteType.MAIN_RECEIVE),
            ("B", RouteType.SIDE_RECEIVE),
        )
        rejected = (
            ("A", RouteType.MAIN_RECEIVE),
            ("A", RouteType.SIDE_RECEIVE),
            ("B", RouteType.MAIN_DEPART),
            ("B", RouteType.SIDE_DEPART),
        )

        for station, route_type in allowed:
            with self.subTest(allowed=(station, route_type)):
                OperationPolicy.validate_route_request(
                    "A_TO_B", station, route_type
                )

        for station, route_type in rejected:
            with self.subTest(rejected=(station, route_type)):
                with self.assertRaises(OperationRuleError) as raised:
                    OperationPolicy.validate_route_request(
                        "A_TO_B", station, route_type
                    )
                message = raised.exception.format_message()
                self.assertIn("操作失败", message)
                self.assertIn("当前状态", message)
                self.assertIn("处理建议", message)
                self.assertIn(f"{station}站", message)

    def test_b_to_a_only_allows_b_departure_and_a_receive(self):
        allowed = (
            ("B", RouteType.MAIN_DEPART),
            ("B", RouteType.SIDE_DEPART),
            ("A", RouteType.MAIN_RECEIVE),
            ("A", RouteType.SIDE_RECEIVE),
        )
        rejected = (
            ("B", RouteType.MAIN_RECEIVE),
            ("B", RouteType.SIDE_RECEIVE),
            ("A", RouteType.MAIN_DEPART),
            ("A", RouteType.SIDE_DEPART),
        )

        for station, route_type in allowed:
            with self.subTest(allowed=(station, route_type)):
                OperationPolicy.validate_route_request(
                    "B_TO_A", station, route_type
                )

        for station, route_type in rejected:
            with self.subTest(rejected=(station, route_type)):
                with self.assertRaises(OperationRuleError) as raised:
                    OperationPolicy.validate_route_request(
                        "B_TO_A", station, route_type
                    )
                message = raised.exception.format_message()
                self.assertIn("B站→A站", message)
                self.assertIn(f"{station}站", message)

    def test_waiting_train_requires_matching_departure_and_receive_routes(self):
        routes = RouteService()
        routes.establish_route("A", RouteType.SIDE_DEPART)
        routes.establish_route("B", RouteType.MAIN_RECEIVE)
        train = Train(
            "T001",
            direction="A_TO_B",
            departure_mode="SIDE",
            arrival_mode="MAIN",
        )

        OperationPolicy.validate_waiting_train_routes(
            "A_TO_B", [train], routes
        )

        train.arrival_mode = "SIDE"
        train.arrival_track = "3G"
        with self.assertRaises(OperationRuleError) as raised:
            OperationPolicy.validate_waiting_train_routes(
                "A_TO_B", [train], routes
            )

        message = raised.exception.format_message()
        self.assertIn("T001", message)
        self.assertIn("B站", message)
        self.assertIn("侧线接车", message)

    def test_second_invalid_waiting_train_rejects_whole_batch(self):
        routes = RouteService()
        routes.establish_route("A", RouteType.MAIN_DEPART)
        routes.establish_route("B", RouteType.MAIN_RECEIVE)
        trains = [
            Train("T001", "A_TO_B", "MAIN", "MAIN"),
            Train("T002", "A_TO_B", "SIDE", "MAIN"),
        ]

        with self.assertRaises(OperationRuleError) as raised:
            OperationPolicy.validate_waiting_train_routes(
                "A_TO_B", trains, routes
            )

        message = raised.exception.format_message()
        self.assertIn("T002", message)
        self.assertIn("A站", message)
        self.assertIn("侧线发车", message)
        self.assertNotIn("T001不满足", message)


if __name__ == "__main__":
    unittest.main()
