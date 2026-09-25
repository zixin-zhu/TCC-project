"""正式单站窗口的结构、交互和关闭生命周期测试。"""

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QPushButton

from app.core.enums import ConnectionState, RunningDirection, TrackState
from app.core.models import PeerSnapshot
from app.infrastructure.config_loader import (
    load_coding_rules,
    load_project_config,
    load_telegram_catalog,
)
from app.services.alarm_service import AlarmService
from app.services.tcc_controller import TccController
from app.ui.main_window import TccMainWindow


ROOT = Path(__file__).resolve().parents[2]


class MemoryPersistence:
    def __init__(self) -> None:
        self.operations = []
        self.telegrams = []
        self.closed = False
        self.direction = None

    def save_operation(self, entry):  # type: ignore[no-untyped-def]
        self.operations.append(entry)
        return True

    def save_telegram(self, entry):  # type: ignore[no-untyped-def]
        self.telegrams.append(entry)
        return True

    def save_direction_authority(self, entry):  # type: ignore[no-untyped-def]
        self.direction = entry
        return True

    def load_direction_authority(self, _station_id, *, now_ms):  # type: ignore[no-untyped-def]
        return self.direction

    def close(self) -> None:
        self.closed = True


class FakeNetworkThread:
    def __init__(self, *, stop_result: bool = True) -> None:
        self.stopped = False
        self.stop_result = stop_result

    def stop(self, *, timeout_ms: int = 3000) -> bool:
        self.stopped = True
        return self.stop_result


def _controller() -> TccController:
    controller = TccController(
        load_project_config(ROOT / "configs", "A"),
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=MemoryPersistence(),
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot("B", {"Q1": TrackState.CLEAR}, 0, 10_000)
    )
    controller.restore_authoritative_direction(RunningDirection.A_TO_B)
    return controller


def test_window_has_all_required_pages_and_no_empty_buttons(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = TccMainWindow(_controller())
    qtbot.addWidget(window)

    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "总览拓扑",
        "轨道编码",
        "信号",
        "应答器/LEU",
        "临时限速",
        "区间改方",
        "网络",
        "日志告警",
    ]
    assert window.station_label.text() == "A站列控中心 · SERVER"
    assert all(button.text().strip() for button in window.findChildren(QPushButton))


def test_track_command_flows_through_controller_and_refreshes_snapshot(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = _controller()
    window = TccMainWindow(controller)
    qtbot.addWidget(window)
    window.track_selector.setCurrentText("Q2")
    index = window.track_state_selector.findData(TrackState.OCCUPIED)
    window.track_state_selector.setCurrentIndex(index)

    qtbot.mouseClick(window.apply_track_button, Qt.LeftButton)

    assert controller.snapshot.tracks["Q2"] is TrackState.OCCUPIED
    assert "成功" in window.operation_result.text()


def test_route_controls_and_operation_log_are_functional(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = _controller()
    window = TccMainWindow(controller)
    qtbot.addWidget(window)
    window.route_selector.setCurrentText("A_DEPART")

    qtbot.mouseClick(window.establish_route_button, Qt.LeftButton)

    assert "A_DEPART" in controller.snapshot.active_route_ids
    assert window.operation_table.rowCount() >= 1
    assert window.operation_table.item(0, 1).text() == "建立进路 A_DEPART"


def test_close_stops_network_then_closes_persistence(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = _controller()
    network = FakeNetworkThread()
    window = TccMainWindow(controller, network_thread=network)
    qtbot.addWidget(window)

    window.close()

    assert network.stopped is True
    assert controller.persistence.closed is True


def test_close_is_rejected_when_network_thread_does_not_stop(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = _controller()
    network = FakeNetworkThread(stop_result=False)
    window = TccMainWindow(controller, network_thread=network)
    qtbot.addWidget(window)

    assert window.close() is False
    assert controller.persistence.closed is False
    assert "网络线程" in window.operation_result.text()
