"""列车页面下拉选择、表格选中和 2D 场景高亮的集成测试。"""

from PyQt5.QtCore import Qt

from app.core.enums import ConnectionState, RunningDirection, TrackState
from app.core.models import PeerSnapshot
from app.services.alarm_service import AlarmService
from app.services.dual_train_coordinator import DualTrainCoordinator
from app.services.tcc_controller import TccController
from app.ui.dual_operations_pages import TrainOperationsPage
from tests.unit.test_dual_train_coordinator import ROOT, _MemoryPersistence


def _controller(station_id: str) -> TccController:
    from app.infrastructure.config_loader import (
        load_coding_rules,
        load_project_config,
        load_telegram_catalog,
    )

    controller = TccController(
        load_project_config(ROOT / "configs", station_id),
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=_MemoryPersistence(),
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
        send_direction=lambda _message: None,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot(
            "B" if station_id == "A" else "A",
            {f"Q{index}": TrackState.CLEAR for index in range(1, 5)},
            0,
            10_000,
        )
    )
    controller.restore_authoritative_direction(RunningDirection.A_TO_B)
    return controller


def test_train_selector_drives_scene_and_table_selection(qtbot) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = _controller("A"), _controller("B")
    coordinator = DualTrainCoordinator(station_a, station_b)
    page = TrainOperationsPage(station_a, station_b, coordinator)
    qtbot.addWidget(page)

    first = coordinator.create_train()
    second = coordinator.create_train()
    coordinator.trains_changed.emit(tuple(coordinator.trains.values()))

    assert page.train_selector.count() == 2
    page.train_selector.setCurrentIndex(page.train_selector.findData(second.train_id))
    assert page._selected_train_id() == second.train_id
    assert page.train_scene.selected_train_id == second.train_id
    assert page.train_table.currentRow() == 1

    qtbot.mouseClick(page.train_table.viewport(), Qt.LeftButton)
