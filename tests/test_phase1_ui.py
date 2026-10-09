import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
from network.network_worker import ClientNetworkWorker, ServerNetworkWorker


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

        self.assertEqual(window.panel_a.network_role, "Server")
        self.assertEqual(window.panel_b.network_role, "Client")
        self.assertEqual(window.panel_a.disconnect_button.text(), "断开连接")
        self.assertEqual(window.panel_b.disconnect_button.text(), "断开连接")

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

        self.assertIs(window.network_worker_class("A"), ServerNetworkWorker)
        self.assertIs(window.network_worker_class("B"), ClientNetworkWorker)

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
        window.train_service.add_waiting_train()
        window.clear_all_trains()
        self.assertEqual(window.train_service.trains, {})
        self.assertEqual(window.train_service.waiting_queue, [])
        self.assertEqual(window.engine.simulation_time, 12.5)
        window.close()

    def test_compact_operation_layout_contract(self):
        window = MainWindow()

        direction_group = window.findChild(QGroupBox, "direction_change_area")
        speed_group = window.findChild(QGroupBox, "temporary_speed_area")
        self.assertIsNotNone(direction_group)
        self.assertIsNotNone(speed_group)
        self.assertEqual(window.operation_top_layout.stretch(0), 1)
        self.assertEqual(window.operation_top_layout.stretch(1), 3)

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


if __name__ == "__main__":
    unittest.main()
