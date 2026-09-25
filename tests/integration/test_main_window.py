"""正式单站窗口的结构、交互和关闭生命周期测试。"""

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHeaderView, QPushButton, QTableWidget, QWidget

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
from app.ui.station_detail_widget import StationDetailWidget


ROOT = Path(__file__).resolve().parents[2]


class MemoryPersistence:
    def __init__(self) -> None:
        self.operations = []
        self.telegrams = []
        self.closed = False
        self.close_count = 0
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
        self.close_count += 1


class FakeLifecycle:
    def __init__(
        self,
        controller: TccController,
        events: list[str],
        *,
        stop_result: bool = True,
    ) -> None:
        self.controller = controller
        self.events = events
        self.stopped = False
        self.stop_result = stop_result

    def stop(self, *, timeout_ms: int = 3000) -> bool:
        self.events.append("stop:lifecycle")
        self.stopped = True
        if self.stop_result:
            self.controller.close()
            self.events.append("close:controller")
        return self.stop_result


def _controller(station_id: str = "A") -> TccController:
    controller = TccController(
        load_project_config(ROOT / "configs", station_id),
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
        PeerSnapshot(
            "B" if station_id == "A" else "A",
            {"Q1": TrackState.CLEAR},
            0,
            10_000,
        )
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
        "列车演示",
        "网络",
        "日志告警",
    ]
    assert window.station_label.text() == "A站列控中心 · SERVER"
    assert all(button.text().strip() for button in window.findChildren(QPushButton))


def test_station_detail_is_embeddable_and_preserves_nine_function_pages(qtbot) -> None:  # type: ignore[no-untyped-def]
    parent = QWidget()
    detail = StationDetailWidget(_controller(), parent=parent)
    qtbot.addWidget(parent)

    assert detail.parent() is parent
    assert [detail.tabs.tabText(i) for i in range(detail.tabs.count())] == [
        "总览拓扑",
        "轨道编码",
        "信号",
        "应答器/LEU",
        "临时限速",
        "区间改方",
        "列车演示",
        "网络",
        "日志告警",
    ]
    assert detail.track_table.rowCount() == 8
    assert detail.signal_table.rowCount() > 0
    assert "simulation_envelope" in detail.envelope_text.toPlainText()


def test_station_detail_can_omit_train_page_for_future_dual_coordinator(qtbot) -> None:  # type: ignore[no-untyped-def]
    detail = StationDetailWidget(_controller(), include_train_page=False)
    qtbot.addWidget(detail)

    assert "列车演示" not in [
        detail.tabs.tabText(i) for i in range(detail.tabs.count())
    ]


def test_window_pages_are_accessible_at_minimum_supported_size(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = TccMainWindow(_controller())
    window.resize(1280, 800)
    qtbot.addWidget(window)
    window.show()

    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        assert window.tabs.currentWidget().isVisible()

    expected_actions = {
        "建立进路",
        "取消进路",
        "应用轨道状态",
        "应用灯丝状态",
        "预存",
        "执行",
        "撤销",
        "申请区间改方",
        "创建列车",
        "发送选中列车",
        "开始运行",
        "暂停",
        "复位列车",
    }
    assert expected_actions.issubset(
        {button.text() for button in window.findChildren(QPushButton)}
    )
    for table in window.findChildren(QTableWidget):
        last_column = table.columnCount() - 1
        assert (
            table.horizontalHeader().sectionResizeMode(last_column)
            == QHeaderView.Stretch
        )


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


def test_train_demo_uses_controller_track_source(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = _controller()
    assert controller.establish_route("A_DEPART").success
    window = TccMainWindow(controller)
    qtbot.addWidget(window)

    qtbot.mouseClick(window.create_train_button, Qt.LeftButton)
    qtbot.mouseClick(window.dispatch_train_button, Qt.LeftButton)

    assert controller.snapshot.tracks["Q1"] is TrackState.OCCUPIED
    assert window.train_table.item(0, 2).text() == "Q1"


def test_close_delegates_ownership_to_lifecycle_without_double_close(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = _controller()
    events: list[str] = []
    lifecycle = FakeLifecycle(controller, events)
    window = TccMainWindow(controller, lifecycle=lifecycle)
    qtbot.addWidget(window)

    window.close()

    assert lifecycle.stopped is True
    assert events == ["stop:lifecycle", "close:controller"]
    assert controller.persistence.closed is True
    assert controller.persistence.close_count == 1


def test_close_without_lifecycle_closes_controller_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = _controller()
    window = TccMainWindow(controller)
    qtbot.addWidget(window)

    assert window.close() is True
    assert controller.persistence.close_count == 1


def test_close_is_rejected_when_network_thread_does_not_stop(qtbot) -> None:  # type: ignore[no-untyped-def]
    controller = _controller()
    lifecycle = FakeLifecycle(controller, [], stop_result=False)
    window = TccMainWindow(controller, lifecycle=lifecycle)
    qtbot.addWidget(window)

    assert window.close() is False
    assert controller.persistence.closed is False
    assert "运行时" in window.operation_result.text()
