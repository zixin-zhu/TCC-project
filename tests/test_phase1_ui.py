import os
import sys
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from ui.main_window import MainWindow
from ui.tcc_overview import TccOverviewWidget
from models.route import RouteType
class FakeNetworkWorker(QObject):
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    message_received = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.running = False
        self.started = False

    def start(self):
        self.started = True
        self.running = True

    def stop(self):
        self.running = False

    def wait(self, timeout):
        return True

    def send_message(self, message):
        pass


class FakeServerWorker(FakeNetworkWorker):
    pass


class FakeClientWorker(FakeNetworkWorker):
    pass


class PhaseOneUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_overview_matches_word_section_7_1_structure(self):
        view = TccOverviewWidget()
        contract = view.layout_contract()

        self.assertEqual(contract["stations"], ["A站", "B站"])
        self.assertEqual(contract["approach_sections"]["A站SN外方"], 3)
        self.assertEqual(contract["approach_sections"]["B站X外方"], 3)
        self.assertEqual(contract["interval_section_count"], 38)
        self.assertEqual(contract["block_section_count"], 19)
        self.assertEqual(contract["track_sections_per_block"], 2)
        self.assertTrue(contract["continuous_layout"])
        self.assertEqual(contract["display_direction"], "下行")
        self.assertGreaterEqual(len(contract["active_balise_groups"]), 2)

    def test_station_yards_follow_word_signal_and_balise_layout(self):
        view = TccOverviewWidget()

        station_a = view.station_layout_contract("A")
        station_b = view.station_layout_contract("B")

        expected_common_signals = {
            "X": "RIGHT",
            "S3": "LEFT",
            "S1": "LEFT",
            "X3": "RIGHT",
            "X1": "RIGHT",
        }
        self.assertEqual(
            station_a["signals"],
            {**expected_common_signals, "SN": "LEFT"},
        )
        self.assertEqual(
            station_b["signals"],
            {**expected_common_signals, "S": "LEFT"},
        )
        self.assertEqual(
            station_a["approach_sections"],
            ["X1LQ", "X2LQ", "X3LQ"],
        )
        self.assertEqual(
            station_b["approach_sections"],
            ["X1JG", "X2JG", "X3JG"],
        )
        self.assertEqual(station_a["approach_side"], "AFTER_SN")
        self.assertEqual(station_b["approach_side"], "BEFORE_X")
        self.assertEqual(station_a["active_balise_count"], 3)
        self.assertEqual(station_b["active_balise_count"], 3)
        self.assertEqual(station_a["passive_balise_count"], 2)
        self.assertEqual(station_b["passive_balise_count"], 2)
        self.assertEqual(view.layout_contract()["interval_signal_direction"], "RIGHT_FIXED")

    def test_overview_uses_black_background(self):
        view = TccOverviewWidget()
        self.assertEqual(view.background_color, QColor("#05070a"))

    def test_main_window_uses_reference_three_zone_layout(self):
        window = MainWindow()

        self.assertIsNotNone(window.findChild(QGroupBox, "visualization_area"))
        self.assertIsNotNone(window.findChild(QGroupBox, "communication_area"))
        self.assertIsNotNone(window.findChild(QGroupBox, "operation_area"))
        self.assertIsInstance(window.simulation_view, TccOverviewWidget)
        self.assertIsNotNone(
            window.findChild(QScrollArea, "visualization_scroll_area")
        )

        visible_text = []
        for widget_type in (QLabel, QPushButton, QGroupBox):
            for widget in window.findChildren(widget_type):
                text = widget.title() if isinstance(widget, QGroupBox) else widget.text()
                visible_text.append(text)

        self.assertFalse(any("日志" in text for text in visible_text))
        self.assertFalse(any("查看A站应答器" in text for text in visible_text))
        self.assertFalse(any("查看B站应答器" in text for text in visible_text))
        window.close()

    def test_station_roles_disconnect_and_operation_controls(self):
        window = MainWindow()

        self.assertFalse(hasattr(window.panel_a, "role_label"))
        self.assertFalse(hasattr(window.panel_b, "role_label"))
        self.assertEqual(window.panel_a.network_button.text(), "启动通信")
        self.assertEqual(window.panel_b.network_button.text(), "启动通信")
        self.assertEqual(window.panel_a.disconnect_button.text(), "断开连接")
        self.assertEqual(window.panel_b.disconnect_button.text(), "断开连接")

        visible_labels = [label.text() for label in window.findChildren(QLabel)]
        self.assertFalse(any("通信角色" in text for text in visible_labels))

        self.assertEqual(window.departure_mode_combo.count(), 2)
        self.assertEqual(window.departure_mode_combo.itemText(0), "正线发车")
        self.assertEqual(window.departure_mode_combo.itemText(1), "侧线发车")
        self.assertEqual(window.arrival_mode_combo.itemText(0), "正线接车")
        self.assertEqual(window.arrival_mode_combo.itemText(1), "侧线接车")
        self.assertEqual(window.clear_trains_button.text(), "一键清车")

        for object_name in (
            "tsr_start_section",
            "tsr_end_section",
            "tsr_speed",
            "tsr_apply_button",
            "tsr_cancel_button",
        ):
            self.assertIsNotNone(window.findChild(QWidget, object_name))

        window.close()

    def test_network_roles_and_tsr_actions_are_wired_to_services(self):
        window = MainWindow()

        window.tsr_start_combo.setCurrentText("G05")
        window.tsr_end_combo.setCurrentText("G08")
        window.tsr_speed_combo.setCurrentText("80 km/h")
        window.apply_temporary_speed_restriction()
        self.assertEqual(window.temporary_speed_service.speed_for("G06"), 80)
        self.assertEqual(window.active_tsr_combo.count(), 1)

        restriction_id = window.active_tsr_combo.currentData()
        window.cancel_temporary_speed_restriction()
        self.assertIsNotNone(restriction_id)
        self.assertEqual(window.temporary_speed_service.active_restrictions(), [])

        balise_info = window.get_balise_information("A站SN口_JZ")
        self.assertIn("ETCS-254", balise_info["packets"])
        self.assertGreater(window.simulation_view.receivers(window.simulation_view.balise_clicked), 0)
        window.close()

    def test_first_started_station_becomes_server_and_second_becomes_client(self):
        for first, second in (("A", "B"), ("B", "A")):
            with self.subTest(first=first):
                window = MainWindow()
                with patch("ui.main_window.ServerNetworkWorker", FakeServerWorker), patch(
                    "ui.main_window.ClientNetworkWorker", FakeClientWorker, create=True
                ):
                    window.start_network(first)
                    window.start_network(second)

                self.assertIsInstance(window.network_workers[first], FakeServerWorker)
                self.assertIsInstance(window.network_workers[second], FakeClientWorker)
                self.assertEqual(window.network_workers[first].port, 9000)
                self.assertEqual(window.network_workers[second].port, 9000)
                self.assertEqual(window.network_server_station, first)
                self.assertEqual(window.network_modes[first], "SERVER")
                self.assertEqual(window.network_modes[second], "CLIENT")
                for station in ("A", "B"):
                    status = window.get_panel_by_role(station).network_status_label.text()
                    self.assertNotIn("Server", status)
                    self.assertNotIn("Client", status)
                    self.assertNotIn("服务器", status)
                    self.assertNotIn("客户端", status)
                window.disconnect_network(first)
                window.close()

    def test_disconnecting_either_station_resets_both_sides_and_next_election(self):
        window = MainWindow()
        with patch("ui.main_window.ServerNetworkWorker", FakeServerWorker), patch(
            "ui.main_window.ClientNetworkWorker", FakeClientWorker, create=True
        ):
            window.start_network("A")
            window.start_network("B")
            workers = list(window.network_workers.values())
            window.disconnect_network("B")

        self.assertEqual(window.network_workers, {})
        self.assertEqual(window.network_modes, {})
        self.assertIsNone(window.network_server_station)
        self.assertTrue(all(not worker.running for worker in workers))
        for panel in (window.panel_a, window.panel_b):
            self.assertTrue(panel.network_button.isEnabled())
            self.assertFalse(panel.disconnect_button.isEnabled())
            self.assertEqual(panel.network_status_label.text(), "通信状态：未启动")
        window.close()

    def test_expected_socket_close_does_not_replace_idle_status_with_error(self):
        window = MainWindow()
        window.panel_b.set_network_status("通信状态：未启动")

        with patch("ui.main_window.QMessageBox.warning"):
            window.on_network_error("B", "[Errno 9] Bad file descriptor")

        self.assertEqual(window.panel_b.network_status_label.text(), "通信状态：未启动")
        window.close()

    def test_disconnect_and_clear_train_actions(self):
        class FakeWorker:
            running = True

            def stop(self):
                self.running = False

            def wait(self, timeout):
                return True

        window = MainWindow()
        window.network_workers["A"] = FakeWorker()
        window.panel_a.disconnect_button.setEnabled(True)
        window.disconnect_network("A")
        self.assertNotIn("A", window.network_workers)
        self.assertTrue(window.panel_a.network_button.isEnabled())
        self.assertFalse(window.panel_a.disconnect_button.isEnabled())

        window.engine.simulation_time = 12.5
        window.route_service.establish_route("A", RouteType.MAIN_DEPART)
        window.train_service.add_waiting_train()
        window.clear_all_trains()
        self.assertEqual(window.train_service.trains, {})
        self.assertEqual(window.train_service.waiting_queue, [])
        self.assertEqual(window.route_service.active_routes(), [])
        self.assertEqual(window.active_route_combo.currentData(), None)
        self.assertEqual(window.engine.simulation_time, 12.5)
        window.close()

    def test_reset_clears_routes_and_preserves_route_service_binding(self):
        window = MainWindow()
        window.route_service.establish_route("A", RouteType.MAIN_DEPART)

        window.reset_simulation()

        self.assertEqual(window.route_service.active_routes(), [])
        self.assertIs(window.train_service.route_service, window.route_service)
        self.assertEqual(window.active_route_combo.currentData(), None)
        window.close()

    def test_train_keeps_selected_departure_and_arrival_modes(self):
        window = MainWindow()
        window.departure_mode_combo.setCurrentText("侧线发车")
        window.arrival_mode_combo.setCurrentText("正线接车")

        window.add_waiting_train()

        train = window.train_service.trains["T001"]
        self.assertEqual(train.departure_mode, "SIDE")
        self.assertEqual(train.station_track, "3G")
        self.assertEqual(train.arrival_mode, "MAIN")
        self.assertEqual(train.arrival_track, "1G")
        window.close()

    def test_compact_operation_layout_contract(self):
        window = MainWindow()

        direction_group = window.findChild(QGroupBox, "direction_change_area")
        route_group = window.findChild(QGroupBox, "route_management_area")
        speed_group = window.findChild(QGroupBox, "temporary_speed_area")
        self.assertIsNotNone(direction_group)
        self.assertIsNotNone(route_group)
        self.assertIsNotNone(speed_group)
        self.assertEqual(window.operation_top_layout.stretch(0), 1)
        self.assertEqual(window.operation_top_layout.stretch(1), 2)
        self.assertEqual(window.operation_top_layout.stretch(2), 4)

        distance_index = window.train_status_grid.indexOf(window.info_distance)
        braking_index = window.train_status_grid.indexOf(window.info_braking)
        self.assertEqual(window.train_status_grid.getItemPosition(distance_index)[:2], (0, 4))
        self.assertEqual(window.train_status_grid.getItemPosition(braking_index)[:2], (1, 4))

        self.assertIsInstance(window.train_selector_layout, QHBoxLayout)
        self.assertLessEqual(window.train_selector_layout.spacing(), 5)
        self.assertEqual(
            window.bottom_widget.sizePolicy().verticalPolicy(),
            QSizePolicy.Maximum,
        )
        window.close()

    def test_route_panel_uses_one_two_four_layout_contract(self):
        window = MainWindow()

        groups = [
            window.operation_top_layout.itemAt(index).widget()
            for index in range(3)
        ]
        self.assertEqual(
            [group.objectName() for group in groups],
            [
                "direction_change_area",
                "route_management_area",
                "temporary_speed_area",
            ],
        )
        self.assertEqual(
            [window.operation_top_layout.stretch(index) for index in range(3)],
            [1, 2, 4],
        )
        self.assertEqual(
            [
                window.route_station_combo.itemText(index)
                for index in range(window.route_station_combo.count())
            ],
            ["A站", "B站"],
        )
        self.assertEqual(
            [
                window.route_type_combo.itemText(index)
                for index in range(window.route_type_combo.count())
            ],
            ["正线接车", "侧线接车", "正线发车", "侧线发车"],
        )
        window.close()

    def test_route_panel_establishes_and_cancels_selected_route(self):
        window = MainWindow()

        window.route_station_combo.setCurrentText("A站")
        window.route_type_combo.setCurrentText("正线发车")
        window.route_establish_button.click()

        self.assertEqual(window.active_route_combo.count(), 1)
        self.assertIn("A站｜正线发车｜1G｜已建立", window.active_route_combo.currentText())
        self.assertTrue(window.route_cancel_button.isEnabled())

        window.route_cancel_button.click()

        self.assertEqual(window.route_service.active_routes(), [])
        self.assertEqual(window.active_route_combo.count(), 1)
        self.assertEqual(window.active_route_combo.currentText(), "暂无已建立进路")
        self.assertFalse(window.route_cancel_button.isEnabled())
        window.close()

    def test_locked_route_disables_cancel_button(self):
        window = MainWindow()
        route = window.route_service.establish_route("A", RouteType.MAIN_DEPART)
        window.route_service.lock_route(route.route_id, "T001")

        window.refresh_route_controls()

        self.assertIn("已锁闭", window.active_route_combo.currentText())
        self.assertFalse(window.route_cancel_button.isEnabled())
        window.close()

    def test_route_highlight_contract_maps_main_and_side_tracks(self):
        expected = (
            ("A", RouteType.MAIN_DEPART, "1G", "RIGHT"),
            ("A", RouteType.SIDE_RECEIVE, "3G", "RIGHT"),
            ("B", RouteType.MAIN_RECEIVE, "1G", "LEFT"),
            ("B", RouteType.SIDE_DEPART, "3G", "LEFT"),
        )

        for station, route_type, track, throat in expected:
            with self.subTest(station=station, route_type=route_type):
                contract = TccOverviewWidget.route_highlight_contract(
                    station,
                    route_type,
                )
                self.assertEqual(contract["track"], track)
                self.assertEqual(contract["interval_throat"], throat)

        station_a = TccOverviewWidget.station_layout_contract("A")["signals"]
        station_b = TccOverviewWidget.station_layout_contract("B")["signals"]
        for signal_name in ("X", "S3", "S1", "X3", "X1"):
            self.assertEqual(station_a[signal_name], station_b[signal_name])
        self.assertEqual(station_a["SN"], "LEFT")
        self.assertEqual(station_b["S"], "LEFT")

    def test_overview_accepts_active_route_snapshot(self):
        view = TccOverviewWidget()
        routes = [
            {
                "route_id": "A-MAIN-DEPART-001",
                "station": "A",
                "route_type": RouteType.MAIN_DEPART,
                "track": "1G",
                "state": "ESTABLISHED",
            }
        ]

        view.set_state([], [], "A_TO_B", routes=routes)
        routes[0]["track"] = "3G"

        self.assertIsInstance(view.routes, tuple)
        self.assertEqual(view.routes[0]["track"], "1G")


if __name__ == "__main__":
    unittest.main()
