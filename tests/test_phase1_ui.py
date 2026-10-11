import os
import sys
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
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
from ui.theme import APP_STYLESHEET
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

    @staticmethod
    def mark_communication_ready(window):
        window.connected_stations.update({"A", "B"})
        window.refresh_control_states()

    def assert_complete_warning(self, warning, expected_title):
        title, message = warning.call_args.args[1:3]
        self.assertEqual(title, expected_title)
        self.assertIn("操作失败", message)
        self.assertIn("当前状态", message)
        self.assertIn("处理建议", message)
        return message

    def test_initially_only_station_start_buttons_are_enabled(self):
        window = MainWindow()

        self.assertTrue(window.panel_a.network_button.isEnabled())
        self.assertTrue(window.panel_b.network_button.isEnabled())
        self.assertFalse(window.panel_a.disconnect_button.isEnabled())
        self.assertFalse(window.panel_b.disconnect_button.isEnabled())
        for button in (
            window.panel_a.direction_button,
            window.panel_b.direction_button,
            window.route_establish_button,
            window.route_cancel_button,
            window.tsr_apply_button,
            window.tsr_cancel_button,
            window.add_train_button,
            window.start_button,
            window.pause_button,
            window.reset_button,
            window.clear_trains_button,
        ):
            self.assertFalse(button.isEnabled(), button.text())
        window.close()

    def test_both_connected_events_are_required_to_unlock_operations(self):
        window = MainWindow()
        with patch("ui.main_window.ServerNetworkWorker", FakeServerWorker), patch(
            "ui.main_window.ClientNetworkWorker", FakeClientWorker, create=True
        ):
            window.start_network("A")
            self.assertFalse(window.operation_area.isEnabled())
            window.network_workers["A"].connected.emit()
            self.assertFalse(window.operation_area.isEnabled())

            window.start_network("B")
            self.assertFalse(window.operation_area.isEnabled())
            window.network_workers["B"].connected.emit()

        self.assertTrue(window.communication_ready())
        self.assertTrue(window.operation_area.isEnabled())
        window.disconnect_network("A")
        window.close()

    def test_disconnect_pauses_and_preserves_business_state(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        window.train_service.add_waiting_train()
        route = window.route_service.establish_route(
            "A", RouteType.MAIN_DEPART
        )
        restriction = window.temporary_speed_service.set_restriction(
            "G05", "G08", 80
        )
        window.engine.start()

        window.disconnect_network("A")

        self.assertFalse(window.engine.timer.isActive())
        self.assertFalse(window.communication_ready())
        self.assertFalse(window.operation_area.isEnabled())
        self.assertIn("T001", window.train_service.trains)
        self.assertEqual(window.route_service.active_routes(), [route])
        self.assertEqual(
            window.temporary_speed_service.active_restrictions(),
            [restriction],
        )
        window.close()

    def test_direct_business_handler_before_connection_is_rejected(self):
        window = MainWindow()
        window.tsr_start_combo.setCurrentText("G05")
        window.tsr_end_combo.setCurrentText("G08")

        with patch("ui.main_window.QMessageBox.warning") as warning:
            window.apply_temporary_speed_restriction()

        self.assertEqual(
            window.temporary_speed_service.active_restrictions(), []
        )
        title, message = warning.call_args.args[1:3]
        self.assertEqual(title, "限速设置失败")
        self.assertIn("操作失败", message)
        self.assertIn("当前状态", message)
        self.assertIn("处理建议", message)
        self.assertIn("A站和B站", message)
        window.close()

    def test_direction_rejects_wrong_station_route_combinations(self):
        cases = (
            ("A_TO_B", "B站", "正线发车"),
            ("A_TO_B", "A站", "正线接车"),
            ("B_TO_A", "A站", "侧线发车"),
            ("B_TO_A", "B站", "侧线接车"),
        )

        for direction, station, route_type in cases:
            with self.subTest(
                direction=direction,
                station=station,
                route_type=route_type,
            ):
                window = MainWindow()
                self.mark_communication_ready(window)
                window.simulation_a.set_direction(direction)
                window.simulation_b.set_direction(direction)
                window.route_station_combo.setCurrentText(station)
                window.route_type_combo.setCurrentText(route_type)

                with patch("ui.main_window.QMessageBox.warning") as warning:
                    window.establish_selected_route()

                message = self.assert_complete_warning(
                    warning, "进路建立失败"
                )
                self.assertIn(station, message)
                self.assertIn(route_type, message)
                self.assertEqual(window.route_service.active_routes(), [])
                window.close()

    def test_duplicate_route_popup_names_route_and_recovery(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        window.route_service.establish_route("A", RouteType.MAIN_DEPART)
        window.route_station_combo.setCurrentText("A站")
        window.route_type_combo.setCurrentText("正线发车")

        with patch("ui.main_window.QMessageBox.warning") as warning:
            window.establish_selected_route()

        message = self.assert_complete_warning(warning, "进路建立失败")
        self.assertIn("A站", message)
        self.assertIn("正线发车", message)
        self.assertIn("请勿重复操作", message)
        window.close()

    def test_overlapping_speed_popup_names_both_restrictions(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        first = window.temporary_speed_service.set_restriction(
            "G05", "G10", 120
        )
        window.tsr_start_combo.setCurrentText("G08")
        window.tsr_end_combo.setCurrentText("G12")
        window.tsr_speed_combo.setCurrentText("80 km/h")

        with patch("ui.main_window.QMessageBox.warning") as warning:
            window.apply_temporary_speed_restriction()

        message = self.assert_complete_warning(warning, "限速设置失败")
        self.assertIn(first["id"], message)
        self.assertIn("G05～G10", message)
        self.assertIn("120 km/h", message)
        self.assertIn("G08～G12", message)
        self.assertIn("80 km/h", message)
        window.close()

    def test_direction_change_denial_uses_complete_warning(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        worker = FakeServerWorker("127.0.0.1", 9000)
        worker.start()
        window.network_workers["B"] = worker

        with patch("ui.main_window.QMessageBox.warning") as warning:
            window.request_direction_change("B")

        message = self.assert_complete_warning(warning, "无法改方")
        self.assertIn("本站未建立发车进路", message)
        self.assertIn("B站", message)
        window.close()

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

        expected_active_groups = {
            "JZ": {"signal": "X", "side": "LEFT", "count": 3},
            "FJZ": {"signal": "S", "side": "RIGHT", "count": 3},
            "X1_CZ": {"signal": "X1", "side": "LEFT", "count": 3},
            "X3_CZ": {"signal": "X3", "side": "LEFT", "count": 3},
            "S1_FCZ": {"signal": "S1", "side": "RIGHT", "count": 3},
            "S3_FCZ": {"signal": "S3", "side": "RIGHT", "count": 3},
        }
        self.assertEqual(station_a["active_balise_groups"], expected_active_groups)
        self.assertEqual(station_b["active_balise_groups"], expected_active_groups)

    def test_interval_uses_uniform_sections_with_equipment_aliases(self):
        view = TccOverviewWidget()
        contract = view.layout_contract()

        self.assertEqual(view.SECTION_WIDTH, view.APPROACH_SECTION_WIDTH)
        self.assertEqual(
            contract["section_equipment_aliases"],
            {
                "G01": "X1LQ",
                "G02": "X2LQ",
                "G03": "X3LQ",
                "G36": "X1JG",
                "G37": "X2JG",
                "G38": "X3JG",
            },
        )

    def test_all_station_active_balise_groups_have_click_targets(self):
        view = TccOverviewWidget()
        view.resize(view.minimumWidth(), 360)
        view.show()
        self.app.processEvents()
        view.grab()

        expected = {
            f"{station}站_{signal}_{group}"
            for station in ("A", "B")
            for signal, group in (
                ("X", "JZ"),
                (("SN" if station == "A" else "S"), "FJZ"),
                ("X1", "CZ"),
                ("X3", "CZ"),
                ("S1", "FCZ"),
                ("S3", "FCZ"),
            )
        }
        self.assertEqual(set(view._active_balise_hitboxes), expected)
        view.close()

    def test_station_code_bands_connect_to_interval_and_balises_fit_between(self):
        view = TccOverviewWidget()
        view.resize(view.minimumWidth(), 360)
        view.show()
        self.app.processEvents()
        view.grab()

        rail_y = max(145, int(view.height() * 0.51))
        code_y = rail_y + 30
        side_y = rail_y - 68
        interval_left = view.SIDE_MARGIN + view.STATION_WIDTH
        interval_right = interval_left + view.SECTION_COUNT * view.SECTION_WIDTH

        self.assertEqual(view._station_code_rects["A_THROAT"].right(), interval_left)
        self.assertEqual(view._station_code_rects["B_THROAT"].left(), interval_right)
        self.assertEqual(view._station_code_rects["A_THROAT"].top(), code_y)
        self.assertEqual(view._station_code_rects["B_THROAT"].top(), code_y)

        for balise_id, hitbox in view._active_balise_hitboxes.items():
            track_y = side_y if "X3_CZ" in balise_id or "S3_FCZ" in balise_id else rail_y
            self.assertGreater(hitbox.center().y(), track_y)
            self.assertLess(hitbox.center().y(), track_y + 30)

        self.assertEqual(
            view.balise_geometry_contract(),
            {
                "triangle_half_width": 3,
                "triangle_height": 6,
                "group_spacing": 6,
                "placement": "BETWEEN_RAIL_AND_CODE_BAND",
            },
        )
        view.close()

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
        self.assertEqual(window.start_button.text(), "▶ 发车")
        self.assertEqual(
            [
                window.max_speed_combo.itemText(index)
                for index in range(window.max_speed_combo.count())
            ],
            [
                "80 km/h",
                "120 km/h",
                "160 km/h",
                "200 km/h",
                "250 km/h",
                "300 km/h",
                "350 km/h",
            ],
        )
        self.assertEqual(window.max_speed_combo.currentText(), "120 km/h")
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
        self.mark_communication_ready(window)

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

        window.connected_stations.clear()
        window.refresh_control_states()
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
        self.mark_communication_ready(window)
        window.clear_all_trains()
        self.assertEqual(window.train_service.trains, {})
        self.assertEqual(window.train_service.waiting_queue, [])
        self.assertEqual(
            [route.display_name for route in window.route_service.active_routes()],
            ["正线发车"],
        )
        self.assertEqual(window.engine.simulation_time, 12.5)
        window.close()

    def test_clear_all_trains_unlocks_preserved_routes(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        route = window.route_service.establish_route(
            "A", RouteType.MAIN_DEPART
        )
        train = window.train_service.add_waiting_train("MAIN", "MAIN")
        window.route_service.lock_route(route.route_id, train.train_id)

        window.clear_all_trains()

        self.assertEqual(window.route_service.active_routes(), [route])
        self.assertEqual(route.state, "ESTABLISHED")
        self.assertIsNone(route.train_id)
        window.close()

    def test_reset_returns_all_dispatched_trains_to_departure_and_preserves_routes(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        route = window.route_service.establish_route(
            "A", RouteType.MAIN_DEPART
        )
        receive_route = window.route_service.establish_route(
            "B", RouteType.MAIN_RECEIVE
        )
        restriction = window.temporary_speed_service.set_restriction(
            "G05", "G08", 80
        )
        train = window.train_service.add_waiting_train("MAIN", "MAIN")
        self.assertTrue(window.train_service.dispatch_train(train))
        window.train_service.waiting_queue.clear()
        second = window.train_service.create_train("MAIN", "MAIN")
        second.enter_track("G10")
        second.position = 220.0
        second.speed = 60.0
        train.current_track = "G05"
        train.position = 420.0
        train.speed = 80.0
        train.block_code = "U"
        train.last_balise = "B05"
        window.train_selector.addItem(train.train_id)
        window.train_selector.setCurrentText(train.train_id)
        window.train_service.sync_track_circuits()
        window.simulation_b.track_circuits["G38"].occupy()
        window.engine.simulation_time = 12.5
        window.engine.start()
        window.refresh_control_states()

        window.reset_simulation()

        self.assertEqual(
            window.route_service.active_routes(), [route, receive_route]
        )
        self.assertEqual(route.state, "ESTABLISHED")
        self.assertIsNone(route.train_id)
        self.assertEqual(
            window.temporary_speed_service.active_restrictions(),
            [restriction],
        )
        self.assertIs(window.train_service.trains[train.train_id], train)
        self.assertEqual(train.status, "WAITING")
        self.assertIsNone(train.current_track)
        self.assertEqual(train.position, 0.0)
        self.assertEqual(train.speed, 0.0)
        self.assertEqual(second.status, "WAITING")
        self.assertIsNone(second.current_track)
        self.assertIn(second.train_id, window.train_service.waiting_queue)
        self.assertEqual(train.block_code, "L5")
        self.assertIsNone(train.last_balise)
        self.assertIn(train.train_id, window.train_service.waiting_queue)
        self.assertEqual(window.engine.simulation_time, 0.0)
        self.assertTrue(
            all(
                not track.occupied
                for simulation in (window.simulation_a, window.simulation_b)
                for track in simulation.track_circuits.values()
            )
        )
        self.assertIs(window.train_service.route_service, window.route_service)
        self.assertEqual(window.active_route_combo.currentData(), route.route_id)
        window.close()

    def test_no_selected_train_cannot_dispatch(self):
        window = MainWindow()
        self.mark_communication_ready(window)

        with patch("ui.main_window.QMessageBox.warning") as warning:
            window.dispatch_selected_train()

        self.assertFalse(window.engine.timer.isActive())
        title, message = warning.call_args.args[1:3]
        self.assertEqual(title, "列车发车失败")
        self.assertIn("操作失败", message)
        self.assertIn("没有选中", message)
        self.assertIn("处理建议", message)
        window.close()

    def test_start_rejects_missing_or_mismatched_train_routes(self):
        cases = (
            (None, None, "MAIN", "MAIN", "A站", "正线发车"),
            (
                RouteType.MAIN_DEPART,
                RouteType.MAIN_RECEIVE,
                "SIDE",
                "MAIN",
                "A站",
                "侧线发车",
            ),
            (
                RouteType.MAIN_DEPART,
                RouteType.MAIN_RECEIVE,
                "MAIN",
                "SIDE",
                "B站",
                "侧线接车",
            ),
        )

        for departure_route, receive_route, departure_mode, arrival_mode, station_text, route_text in cases:
            with self.subTest(
                departure_mode=departure_mode,
                arrival_mode=arrival_mode,
            ):
                window = MainWindow()
                self.mark_communication_ready(window)
                if departure_route is not None:
                    window.route_service.establish_route("A", departure_route)
                if receive_route is not None:
                    window.route_service.establish_route("B", receive_route)
                train = window.train_service.add_waiting_train()
                window.refresh_view()
                window.train_selector.setCurrentText(train.train_id)
                window.departure_mode_combo.setCurrentText(
                    "正线发车" if departure_mode == "MAIN" else "侧线发车"
                )
                window.arrival_mode_combo.setCurrentText(
                    "正线接车" if arrival_mode == "MAIN" else "侧线接车"
                )

                with patch("ui.main_window.QMessageBox.warning") as warning:
                    window.dispatch_selected_train()

                self.assertFalse(window.engine.timer.isActive())
                title, message = warning.call_args.args[1:3]
                self.assertEqual(title, "列车发车失败")
                self.assertIn("T001", message)
                self.assertIn(station_text, message)
                self.assertIn(route_text, message)
                window.close()

    def test_matching_routes_start_in_both_directions(self):
        cases = (
            ("A_TO_B", "A", "B"),
            ("B_TO_A", "B", "A"),
        )

        for direction, departure_station, receive_station in cases:
            with self.subTest(direction=direction):
                window = MainWindow()
                self.mark_communication_ready(window)
                window.simulation_a.set_direction(direction)
                window.simulation_b.set_direction(direction)
                window.route_service.establish_route(
                    departure_station, RouteType.SIDE_DEPART
                )
                window.route_service.establish_route(
                    receive_station, RouteType.MAIN_RECEIVE
                )
                train = window.train_service.add_waiting_train()
                window.refresh_view()
                window.train_selector.setCurrentText(train.train_id)
                window.departure_mode_combo.setCurrentText("侧线发车")
                window.arrival_mode_combo.setCurrentText("正线接车")

                window.dispatch_selected_train()

                self.assertTrue(window.engine.timer.isActive())
                self.assertEqual(train.status, "RUNNING")
                self.assertNotIn(train.train_id, window.train_service.waiting_queue)
                window.engine.pause()
                window.close()

    def test_pause_button_toggles_all_active_trains(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        window.route_service.establish_route("A", RouteType.MAIN_DEPART)
        window.route_service.establish_route("B", RouteType.MAIN_RECEIVE)
        train = window.train_service.add_waiting_train("MAIN", "MAIN")
        self.assertTrue(window.train_service.dispatch_train(train))
        window.train_service.waiting_queue.clear()
        window.refresh_view()
        window.train_selector.setCurrentText(train.train_id)
        window.engine.start()

        with patch("ui.main_window.QMessageBox.warning") as warning:
            window.pause_simulation()

        self.assertFalse(window.engine.timer.isActive())
        self.assertEqual(train.status, "STOPPED")
        self.assertEqual(window.pause_button.text(), "▶ 继续")

        window.pause_simulation()

        self.assertTrue(window.engine.timer.isActive())
        self.assertEqual(train.status, "RUNNING")
        self.assertEqual(window.pause_button.text(), "Ⅱ 暂停")
        warning.assert_not_called()
        window.engine.pause()
        window.close()

    def test_pausing_active_train_ignores_later_waiting_train(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        window.route_service.establish_route("A", RouteType.MAIN_DEPART)
        window.route_service.establish_route("B", RouteType.MAIN_RECEIVE)
        running = window.train_service.add_waiting_train("MAIN", "MAIN")
        self.assertTrue(window.train_service.dispatch_train(running))
        window.train_service.waiting_queue.clear()
        window.refresh_view()
        window.train_selector.setCurrentText(running.train_id)
        window.engine.start()

        window.add_waiting_train()
        later = window.train_service.trains["T002"]
        self.assertEqual(window.train_selector.currentText(), running.train_id)
        window.pause_simulation()

        self.assertFalse(window.engine.timer.isActive())
        self.assertEqual(running.status, "STOPPED")
        self.assertEqual(later.status, "WAITING")
        self.assertIsNone(later.departure_mode)
        self.assertIsNone(later.arrival_mode)
        window.close()

    def test_simulation_and_conditional_button_states(self):
        window = MainWindow()
        self.mark_communication_ready(window)

        self.assertFalse(window.start_button.isEnabled())
        self.assertFalse(window.pause_button.isEnabled())
        self.assertFalse(window.reset_button.isEnabled())
        self.assertFalse(window.clear_trains_button.isEnabled())
        self.assertFalse(window.tsr_cancel_button.isEnabled())

        window.route_service.establish_route("A", RouteType.MAIN_DEPART)
        window.route_service.establish_route("B", RouteType.MAIN_RECEIVE)
        train = window.train_service.add_waiting_train()
        window.refresh_view()
        window.train_selector.setCurrentText(train.train_id)
        self.assertTrue(window.start_button.isEnabled())
        self.assertTrue(window.clear_trains_button.isEnabled())

        window.temporary_speed_service.set_restriction("G05", "G08", 80)
        window.refresh_temporary_speed_controls()
        self.assertTrue(window.tsr_cancel_button.isEnabled())

        window.dispatch_selected_train()
        self.assertFalse(window.start_button.isEnabled())
        self.assertTrue(window.pause_button.isEnabled())
        self.assertTrue(window.reset_button.isEnabled())

        window.pause_simulation()
        self.assertFalse(window.start_button.isEnabled())
        self.assertTrue(window.pause_button.isEnabled())
        self.assertEqual(window.pause_button.text(), "▶ 继续")
        self.assertTrue(window.reset_button.isEnabled())
        self.assertTrue(window.clear_trains_button.isEnabled())
        window.close()

    def test_adding_train_does_not_capture_departure_or_arrival_mode(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        window.departure_mode_combo.setCurrentText("侧线发车")
        window.arrival_mode_combo.setCurrentText("正线接车")

        window.add_waiting_train()

        train = window.train_service.trains["T001"]
        self.assertIsNone(train.departure_mode)
        self.assertIsNone(train.station_track)
        self.assertIsNone(train.arrival_mode)
        self.assertIsNone(train.arrival_track)
        window.close()

    def test_start_uses_modes_for_selected_waiting_train_only(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        window.route_service.establish_route("A", RouteType.SIDE_DEPART)
        window.route_service.establish_route("B", RouteType.MAIN_RECEIVE)
        first = window.train_service.add_waiting_train()
        second = window.train_service.add_waiting_train()
        window.refresh_view()
        window.train_selector.setCurrentText(first.train_id)
        window.departure_mode_combo.setCurrentText("侧线发车")
        window.arrival_mode_combo.setCurrentText("正线接车")

        with patch("ui.main_window.QMessageBox.warning") as warning:
            window.dispatch_selected_train()

        self.assertTrue(window.engine.timer.isActive())
        warning.assert_not_called()
        self.assertEqual(first.status, "RUNNING")
        self.assertEqual(first.departure_mode, "SIDE")
        self.assertEqual(first.arrival_mode, "MAIN")
        self.assertFalse(hasattr(window.train_service, "dispatch_target_id"))
        self.assertIsNone(second.departure_mode)
        self.assertIsNone(second.arrival_mode)
        window.engine.pause()
        window.close()

    def test_selected_train_controls_follow_status_and_live_max_speed(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        waiting = window.train_service.add_waiting_train()
        running = window.train_service.create_train("SIDE", "MAIN")
        running.set_max_speed(250)
        running.enter_track("G05")
        window.refresh_view()

        window.train_selector.setCurrentText(waiting.train_id)
        window.sync_selected_train_controls()
        self.assertTrue(window.departure_mode_combo.isEnabled())
        self.assertTrue(window.arrival_mode_combo.isEnabled())
        self.assertTrue(window.max_speed_combo.isEnabled())
        self.assertEqual(window.max_speed_combo.currentText(), "120 km/h")

        window.train_selector.setCurrentText(running.train_id)
        window.sync_selected_train_controls()
        self.assertFalse(window.departure_mode_combo.isEnabled())
        self.assertFalse(window.arrival_mode_combo.isEnabled())
        self.assertTrue(window.max_speed_combo.isEnabled())
        self.assertEqual(window.departure_mode_combo.currentText(), "侧线发车")
        self.assertEqual(window.arrival_mode_combo.currentText(), "正线接车")
        self.assertEqual(window.max_speed_combo.currentText(), "250 km/h")

        current_speed = running.speed
        window.max_speed_combo.setCurrentText("80 km/h")
        self.assertEqual(running.max_speed, 80.0)
        self.assertEqual(running.speed, current_speed)
        self.assertLessEqual(running.target_speed, 80.0)

        running.status = "ARRIVED"
        window.sync_selected_train_controls()
        self.assertFalse(window.max_speed_combo.isEnabled())
        window.close()

    def test_dispatch_button_can_send_second_selected_train_while_engine_runs(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        departure = window.route_service.establish_route(
            "A", RouteType.MAIN_DEPART
        )
        window.route_service.establish_route("B", RouteType.MAIN_RECEIVE)
        first = window.train_service.add_waiting_train()
        second = window.train_service.add_waiting_train()
        window.refresh_view()

        window.train_selector.setCurrentText(first.train_id)
        window.dispatch_selected_train()
        self.assertEqual(first.status, "RUNNING")

        first.current_track = "G03"
        first.position = 200.0
        window.route_service.unlock_route(departure.route_id)
        first.route_id = None
        window.train_service.sync_track_circuits()
        window.train_selector.setCurrentText(second.train_id)
        window.refresh_control_states()
        self.assertTrue(window.start_button.isEnabled())

        window.dispatch_selected_train()

        self.assertEqual(second.status, "RUNNING")
        self.assertTrue(window.engine.timer.isActive())
        self.assertNotEqual(first.current_track, second.current_track)
        window.engine.pause()
        window.close()

    def test_clear_all_trains_removes_waiting_and_running_trains(self):
        window = MainWindow()
        self.mark_communication_ready(window)
        window.route_service.establish_route("A", RouteType.MAIN_DEPART)
        running = window.train_service.add_waiting_train("MAIN", "MAIN")
        self.assertTrue(window.train_service.dispatch_train(running))
        window.train_service.waiting_queue.clear()
        waiting = window.train_service.add_waiting_train()
        window.refresh_view()

        window.clear_all_trains()

        self.assertEqual(window.train_service.trains, {})
        self.assertEqual(window.train_service.waiting_queue, [])
        self.assertNotIn(running.train_id, window.train_service.trains)
        self.assertNotIn(waiting.train_id, window.train_service.trains)
        self.assertTrue(
            all(
                not track.occupied
                for track in window.simulation_a.track_circuits.values()
            )
        )
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
        self.assertEqual(window.operation_top_layout.stretch(1), 4)
        self.assertEqual(window.operation_top_layout.stretch(2), 5)

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

    def test_route_panel_uses_one_four_five_layout_contract(self):
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
            [1, 4, 5],
        )
        self.assertEqual(groups[1].layout().count(), 2)
        self.assertEqual(groups[1].layout().itemAt(0).layout().count(), 5)
        self.assertEqual(groups[1].layout().itemAt(1).layout().count(), 3)
        self.assertEqual(groups[2].layout().count(), 2)
        self.assertEqual(groups[2].layout().itemAt(0).layout().count(), 7)
        self.assertEqual(groups[2].layout().itemAt(1).layout().count(), 3)
        self.assertEqual(window.route_cancel_button.text(), "取消选中进路")
        self.assertEqual(window.tsr_cancel_button.text(), "取消选中限速")
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
        for combo in (
            window.route_station_combo,
            window.route_type_combo,
            window.active_route_combo,
            window.tsr_start_combo,
            window.tsr_end_combo,
            window.tsr_speed_combo,
            window.active_tsr_combo,
        ):
            self.assertEqual(
                combo.sizePolicy().horizontalPolicy(),
                QSizePolicy.Expanding,
            )
        self.assertEqual(window.route_station_label.text(), "车站：")
        self.assertEqual(window.route_type_label.text(), "进路类型：")
        self.assertEqual(window.active_route_label.text(), "已建立进路：")
        self.assertEqual(window.tsr_start_label.text(), "起始区段：")
        self.assertEqual(window.tsr_end_label.text(), "终止区段：")
        self.assertEqual(window.tsr_speed_label.text(), "限速：")
        self.assertEqual(window.active_tsr_label.text(), "已生效限速：")
        self.assertEqual(window.active_route_combo.count(), 0)
        self.assertEqual(window.active_route_combo.currentText(), "")
        self.assertGreaterEqual(groups[1].minimumWidth(), 400)
        self.assertGreaterEqual(groups[2].minimumWidth(), 550)
        for control in (
            window.route_station_label,
            window.route_type_label,
            window.active_route_label,
            window.route_station_combo,
            window.route_type_combo,
            window.route_establish_button,
            window.route_cancel_button,
            window.tsr_start_label,
            window.tsr_end_label,
            window.tsr_speed_label,
            window.active_tsr_label,
            window.tsr_start_combo,
            window.tsr_end_combo,
            window.tsr_speed_combo,
            window.tsr_apply_button,
            window.tsr_cancel_button,
        ):
            control.ensurePolished()
            self.assertGreaterEqual(control.width(), control.minimumSizeHint().width())
        self.assertEqual(
            [window.speed_combo.itemText(index) for index in range(window.speed_combo.count())],
            ["0.5×", "1×", "2×", "5×", "10×", "20×"],
        )
        window.close()

    def test_route_and_speed_combos_fill_space_between_labels_and_actions(self):
        window = MainWindow()
        window.resize(1440, 900)
        window.show()
        self.app.processEvents()

        def horizontal_gap(left_widget, right_widget):
            return right_widget.x() - (left_widget.x() + left_widget.width())

        adjacent_pairs = (
            (window.route_station_label, window.route_station_combo),
            (window.route_station_combo, window.route_type_label),
            (window.route_type_label, window.route_type_combo),
            (window.route_type_combo, window.route_establish_button),
            (window.active_route_label, window.active_route_combo),
            (window.active_route_combo, window.route_cancel_button),
            (window.tsr_start_label, window.tsr_start_combo),
            (window.tsr_start_combo, window.tsr_end_label),
            (window.tsr_end_label, window.tsr_end_combo),
            (window.tsr_speed_label, window.tsr_speed_combo),
            (window.tsr_speed_combo, window.tsr_apply_button),
            (window.active_tsr_label, window.active_tsr_combo),
            (window.active_tsr_combo, window.tsr_cancel_button),
        )
        for left_widget, right_widget in adjacent_pairs:
            gap = horizontal_gap(left_widget, right_widget)
            self.assertGreaterEqual(gap, 0)
            self.assertLessEqual(gap, 4)

        expected_minimum_widths = {
            window.route_station_combo: 85,
            window.route_type_combo: 170,
            window.active_route_combo: 260,
            window.tsr_start_combo: 75,
            window.tsr_end_combo: 75,
            window.tsr_speed_combo: 145,
            window.active_tsr_combo: 380,
        }
        for combo, minimum_width in expected_minimum_widths.items():
            self.assertGreaterEqual(combo.width(), minimum_width)

        window.close()

    def test_operation_rows_use_grid_layout_and_give_space_to_combos(self):
        window = MainWindow()

        route_group = window.findChild(QGroupBox, "route_management_area")
        speed_group = window.findChild(QGroupBox, "temporary_speed_area")
        route_primary = route_group.layout().itemAt(0).layout()
        route_active = route_group.layout().itemAt(1).layout()
        speed_primary = speed_group.layout().itemAt(0).layout()
        speed_active = speed_group.layout().itemAt(1).layout()

        for row in (route_primary, route_active, speed_primary, speed_active):
            self.assertIsInstance(row, QGridLayout)
            self.assertEqual(row.horizontalSpacing(), 0)

        self.assertGreater(route_primary.columnStretch(1), 0)
        self.assertGreater(route_primary.columnStretch(3), 0)
        self.assertGreater(route_active.columnStretch(1), 0)
        self.assertGreater(speed_primary.columnStretch(1), 0)
        self.assertGreater(speed_primary.columnStretch(3), 0)
        self.assertGreater(speed_primary.columnStretch(5), 0)
        self.assertGreater(speed_active.columnStretch(1), 0)
        window.close()

    def test_route_and_speed_controls_inherit_application_font(self):
        window = MainWindow()

        for control in (
            window.route_station_label,
            window.route_type_label,
            window.active_route_label,
            window.route_station_combo,
            window.route_type_combo,
            window.active_route_combo,
            window.route_establish_button,
            window.route_cancel_button,
            window.tsr_start_label,
            window.tsr_end_label,
            window.tsr_speed_label,
            window.active_tsr_label,
            window.tsr_start_combo,
            window.tsr_end_combo,
            window.tsr_speed_combo,
            window.active_tsr_combo,
            window.tsr_apply_button,
            window.tsr_cancel_button,
        ):
            self.assertNotIn("font-size", control.styleSheet())
        window.close()

    def test_combo_popup_has_readable_normal_and_selected_colors(self):
        self.assertIn("QComboBox QAbstractItemView", APP_STYLESHEET)
        self.assertIn(
            "QComboBox QAbstractItemView::item:selected", APP_STYLESHEET
        )
        self.assertIn("color: #1d2a36", APP_STYLESHEET)
        self.assertIn("background: #ffffff", APP_STYLESHEET)
        self.assertIn("selection-color: #1d2a36", APP_STYLESHEET)
        self.assertIn(
            "selection-background-color: #dceefe", APP_STYLESHEET
        )
        self.assertIn(
            "QComboBox QAbstractItemView::item:hover", APP_STYLESHEET
        )
        self.assertIn("background-color: #dceefe", APP_STYLESHEET)

    def test_combo_popup_view_has_explicit_light_blue_hover_feedback(self):
        window = MainWindow()

        for combo in window.findChildren(QComboBox):
            self.assertTrue(combo.view().hasMouseTracking())
            self.assertEqual(
                combo.view().itemDelegate().__class__.__name__,
                "ComboHoverDelegate",
            )
            palette = combo.view().palette()
            self.assertEqual(
                palette.color(QPalette.Highlight), QColor("#dceefe")
            )
            self.assertEqual(
                palette.color(QPalette.HighlightedText), QColor("#1d2a36")
            )
        window.close()

    def test_minimum_window_keeps_operation_controls_readable(self):
        window = MainWindow()
        window.resize(1180, 760)
        window.show()
        self.app.processEvents()
        self.assertGreaterEqual(window.width(), 1600)

        adjacent_pairs = (
            (window.route_station_label, window.route_station_combo),
            (window.route_station_combo, window.route_type_label),
            (window.route_type_label, window.route_type_combo),
            (window.route_type_combo, window.route_establish_button),
            (window.active_route_label, window.active_route_combo),
            (window.active_route_combo, window.route_cancel_button),
            (window.tsr_start_label, window.tsr_start_combo),
            (window.tsr_start_combo, window.tsr_end_label),
            (window.tsr_end_label, window.tsr_end_combo),
            (window.tsr_speed_label, window.tsr_speed_combo),
            (window.tsr_speed_combo, window.tsr_apply_button),
            (window.active_tsr_label, window.active_tsr_combo),
            (window.active_tsr_combo, window.tsr_cancel_button),
        )
        for left_widget, right_widget in adjacent_pairs:
            gap = right_widget.x() - (
                left_widget.x() + left_widget.width()
            )
            self.assertGreaterEqual(gap, 0)
            self.assertLessEqual(gap, 4)

        for control in (
            window.route_station_combo,
            window.route_type_combo,
            window.active_route_combo,
            window.tsr_start_combo,
            window.tsr_end_combo,
            window.tsr_speed_combo,
            window.active_tsr_combo,
            window.route_establish_button,
            window.route_cancel_button,
            window.tsr_apply_button,
            window.tsr_cancel_button,
        ):
            self.assertGreaterEqual(
                control.width(), control.minimumSizeHint().width()
            )
        window.close()

    def test_route_panel_establishes_and_cancels_selected_route(self):
        window = MainWindow()
        self.mark_communication_ready(window)

        window.route_station_combo.setCurrentText("A站")
        window.route_type_combo.setCurrentText("正线发车")
        window.route_establish_button.click()

        self.assertEqual(window.active_route_combo.count(), 1)
        self.assertIn("A站｜正线发车｜1G｜已建立", window.active_route_combo.currentText())
        self.assertTrue(window.route_cancel_button.isEnabled())

        window.route_cancel_button.click()

        self.assertEqual(window.route_service.active_routes(), [])
        self.assertEqual(window.active_route_combo.count(), 0)
        self.assertEqual(window.active_route_combo.currentText(), "")
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
