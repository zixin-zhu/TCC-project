"""双站摘要卡与全局状态条的关键信息展示测试。"""

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QLabel

from app.core.enums import ConnectionState, RunningDirection
from app.infrastructure.config_loader import load_project_config
from app.ui.dual_snapshot import DualStationSnapshotAggregator
from app.ui.global_status_bar import GlobalStatusBar
from app.ui.station_summary_card import StationSummaryCard
from tests.integration.test_main_window import _controller


ROOT = Path(__file__).resolve().parents[2]


def _model():  # type: ignore[no-untyped-def]
    station_a = _controller().snapshot
    station_b_controller = _controller("B")
    aggregator = DualStationSnapshotAggregator()
    aggregator.update_a(station_a)
    aggregator.update_b(station_b_controller.snapshot)
    assert aggregator.snapshot is not None
    return aggregator.snapshot


def test_station_card_shows_all_required_operational_fields(qtbot) -> None:  # type: ignore[no-untyped-def]
    model = _model()
    card = StationSummaryCard(load_project_config(ROOT / "configs", "A"))
    qtbot.addWidget(card)
    card.set_snapshot(model.station_a)

    visible_text = "\n".join(
        label.text() for label in card.findChildren(QLabel)
    )
    for expected in (
        "A站列控中心",
        "SERVER",
        "HEALTHY",
        "状态版本",
        "A_TO_B",
        "作业允许",
        "活动进路",
        "Q1",
        "SA",
        "LEU_A_1",
        "临时限速",
        "活动告警",
        "发送/接收",
    ):
        assert expected in visible_text
    assert card.communication_label.property("connectionState") == "HEALTHY"


def test_station_card_button_only_emits_navigation_request(qtbot) -> None:  # type: ignore[no-untyped-def]
    model = _model()
    card = StationSummaryCard(load_project_config(ROOT / "configs", "B"))
    qtbot.addWidget(card)
    card.set_snapshot(model.station_b)
    spy = QSignalSpy(card.navigate_requested)

    qtbot.mouseClick(card.navigate_button, Qt.LeftButton)

    assert spy[0] == ["B"]


def test_global_status_bar_exposes_text_and_semantic_state(qtbot) -> None:  # type: ignore[no-untyped-def]
    model = _model()
    status = GlobalStatusBar()
    qtbot.addWidget(status)

    status.set_snapshot(model)

    assert "运行" in status.lifecycle_label.text()
    assert "通信健康" in status.communication_label.text()
    assert "A→B" in status.direction_label.text()
    assert "作业允许" in status.lock_label.text()
    assert "活动告警" in status.alarm_label.text()
    assert status.communication_label.property("connectionState") == "HEALTHY"
