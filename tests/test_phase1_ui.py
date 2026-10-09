import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton

from ui.main_window import MainWindow
from ui.tcc_overview import TccOverviewWidget


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
        self.assertEqual(contract["interval_section_count"], 8)
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

        visible_text = []
        for widget_type in (QLabel, QPushButton, QGroupBox):
            for widget in window.findChildren(widget_type):
                text = widget.title() if isinstance(widget, QGroupBox) else widget.text()
                visible_text.append(text)

        self.assertFalse(any("日志" in text for text in visible_text))
        window.close()


if __name__ == "__main__":
    unittest.main()
