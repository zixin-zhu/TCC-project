"""正式双站主窗口的导航、快照刷新与关闭所有权测试。"""

from pathlib import Path
from types import SimpleNamespace

from PyQt5.QtCore import Qt

from app.core.enums import ConnectionState, TrackInputSource, TrackState
from app.core.models import OperationResult
from app.dual_application import DualStationApplication
from app.ui.dual_main_window import DualStationMainWindow
from tests.integration.test_dual_application_integration import (
    _copy_configs_with_port,
    _free_port,
)
from tests.integration.test_main_window import _controller


NAVIGATION = [
    "双站总览",
    "联合站场图",
    "A站控制",
    "B站控制",
    "轨道电路",
    "信号机控制",
    "应答器/LEU",
    "临时限速",
    "区间改方",
    "通信状态",
    "列车演示",
    "日志告警",
]


class DualRuntimeStub:
    def __init__(self, *, stop_result: bool = True) -> None:
        self.station_a = SimpleNamespace(controller=_controller("A"))
        self.station_b = SimpleNamespace(controller=_controller("B"))
        self.stop_result = stop_result
        self.stop_count = 0

    def stop(self, *, timeout_ms: int = 3000) -> bool:
        self.stop_count += 1
        if self.stop_result:
            self.station_b.controller.close()
            self.station_a.controller.close()
        return self.stop_result

    def set_station_network_fault(self, station_id: str, enabled: bool):  # type: ignore[no-untyped-def]
        controller = self.station_a.controller if station_id == "A" else self.station_b.controller
        controller.set_connection_state(
            ConnectionState.DEGRADED if enabled else ConnectionState.HEALTHY
        )
        return OperationResult(True, "测试网络状态已切换")


def test_dual_window_has_twelve_real_pages_and_card_navigation(qtbot) -> None:  # type: ignore[no-untyped-def]
    runtime = DualRuntimeStub()
    window = DualStationMainWindow(runtime)
    qtbot.addWidget(window)

    assert [window.navigation.item(i).text() for i in range(12)] == NAVIGATION
    assert window.pages.count() == 12
    assert all(window.pages.widget(i).layout().count() > 0 for i in range(12))
    assert "A站列控中心" in window.station_a_card.identity_label.text()
    assert "B站列控中心" in window.station_b_card.identity_label.text()

    qtbot.mouseClick(window.station_b_card.navigate_button, Qt.LeftButton)

    assert window.navigation.currentRow() == 3
    assert window.pages.currentIndex() == 3


def test_dual_window_refreshes_from_controller_callbacks_without_polling(qtbot) -> None:  # type: ignore[no-untyped-def]
    runtime = DualRuntimeStub()
    window = DualStationMainWindow(runtime)
    qtbot.addWidget(window)

    result = runtime.station_a.controller.set_track_state(
        "Q2", TrackInputSource.OPERATOR, TrackState.OCCUPIED
    )

    assert result.success
    assert window.aggregator.snapshot is not None
    q2 = next(
        item
        for item in window.aggregator.snapshot.sections
        if item.section_id == "Q2"
    )
    assert q2.consistent is False
    assert "安全锁闭" in window.global_status.lock_label.text()
    assert window.corridor.section_status_text("Q2") == "不一致"
    assert window.station_a_detail.establish_route_button.isEnabled() is False
    assert window.station_b_detail.establish_route_button.isEnabled() is False
    assert window.station_a_detail.direction_button.isEnabled() is False
    assert window.corridor_detail_table.rowCount() == len(
        window.aggregator.snapshot.sections
    )
    q2_rows = [
        row
        for row in range(window.corridor_detail_table.rowCount())
        if window.corridor_detail_table.item(row, 0).text() == "Q2"
    ]
    assert len(q2_rows) == 1
    assert window.corridor_detail_table.item(q2_rows[0], 5).text() == "不一致"

    resolved = runtime.station_b.controller.set_track_state(
        "Q2", TrackInputSource.OPERATOR, TrackState.OCCUPIED
    )

    assert resolved.success
    assert window.aggregator.snapshot.operation_locked is False
    assert window.station_a_detail.establish_route_button.isEnabled() is True
    assert window.station_b_detail.establish_route_button.isEnabled() is True


def test_dual_window_delegates_close_to_dual_runtime_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    runtime = DualRuntimeStub()
    window = DualStationMainWindow(runtime)
    qtbot.addWidget(window)

    assert window.close() is True
    assert runtime.stop_count == 1
    assert window.close() is True
    assert runtime.stop_count == 1


def test_dual_window_rejects_close_when_runtime_stop_times_out(qtbot) -> None:  # type: ignore[no-untyped-def]
    runtime = DualRuntimeStub(stop_result=False)
    window = DualStationMainWindow(runtime)
    qtbot.addWidget(window)

    assert window.close() is False
    assert runtime.stop_count == 1
    assert "关闭失败" in window.global_status.lifecycle_label.text()


def test_close_failure_keeps_train_timer_safely_stopped(qtbot) -> None:  # type: ignore[no-untyped-def]
    runtime = DualRuntimeStub(stop_result=False)
    window = DualStationMainWindow(runtime)
    qtbot.addWidget(window)
    window.train_coordinator.timer.start()

    assert window.close() is False

    assert not window.train_coordinator.timer.isActive()
    assert "保持安全停止" in window.global_status.lifecycle_label.text()


def test_real_runtime_drives_dashboard_to_healthy_and_closes_cleanly(
    tmp_path: Path, qtbot
) -> None:  # type: ignore[no-untyped-def]
    config_dir = tmp_path / "configs"
    _copy_configs_with_port(config_dir, _free_port())
    runtime = DualStationApplication.build(
        config_dir=config_dir, data_root=tmp_path / "data"
    )
    window = DualStationMainWindow(runtime)
    qtbot.addWidget(window)

    runtime.start()
    try:
        qtbot.waitUntil(
            lambda: (
                window.aggregator.snapshot is not None
                and window.aggregator.snapshot.communication_healthy
            ),
            timeout=4000,
        )
        assert "通信健康" in window.global_status.communication_label.text()
        assert "SERVER" in window.station_a_card.identity_label.text()
        assert "CLIENT" in window.station_b_card.identity_label.text()
    finally:
        closed = window.close()

    assert closed
    assert not runtime.station_a.network_thread.thread.isRunning()
    assert not runtime.station_b.network_thread.thread.isRunning()
