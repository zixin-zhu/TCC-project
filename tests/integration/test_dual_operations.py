"""双站真实操作页与唯一列车协调器的界面集成测试。"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QPushButton

from app.core.enums import RunningDirection, TrackState
from app.core.models import OperationResult
from app.services.dual_train_coordinator import DualTrainStatus
from app.services.demo_scenarios import DELIVERY_SCENARIOS
from app.dual_application import DualStationApplication
from app.ui.dual_main_window import DualStationMainWindow
from tests.integration.test_dual_application_integration import (
    _copy_configs_with_port,
    _free_port,
)
from tests.integration.test_dual_main_window import DualRuntimeStub


def _window(qtbot):  # type: ignore[no-untyped-def]
    runtime = DualRuntimeStub()
    window = DualStationMainWindow(runtime)
    qtbot.addWidget(window)
    return window, runtime


def test_track_page_routes_station_and_shared_targets_through_controllers(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, runtime = _window(qtbot)
    page = window.track_operations_page

    page.target_selector.setCurrentText("A站")
    page.section_selector.setCurrentText("A_T1")
    page.state_selector.setCurrentIndex(page.state_selector.findData(TrackState.OCCUPIED))
    qtbot.mouseClick(page.apply_button, Qt.LeftButton)

    assert runtime.station_a.controller.snapshot.tracks["A_T1"] is TrackState.OCCUPIED
    assert runtime.station_b.controller.snapshot.tracks["A_T1"] is TrackState.CLEAR
    assert "目标=A站" in page.result_label.text()
    assert "成功" in page.result_label.text()
    assert "版本=" in page.result_label.text()

    page.target_selector.setCurrentText("共享区间")
    assert [page.section_selector.itemText(i) for i in range(page.section_selector.count())] == [
        "Q1", "Q2", "Q3", "Q4"
    ]
    page.section_selector.setCurrentText("Q2")
    qtbot.mouseClick(page.apply_button, Qt.LeftButton)
    assert runtime.station_a.controller.snapshot.tracks["Q2"] is TrackState.OCCUPIED
    assert runtime.station_b.controller.snapshot.tracks["Q2"] is TrackState.OCCUPIED

    original_b_write = runtime.station_b.controller.set_track_state

    def fail_b_clear(section_id, source, state):  # type: ignore[no-untyped-def]
        if section_id == "Q2" and state is TrackState.CLEAR:
            return OperationResult(False, "模拟B站清除失败")
        return original_b_write(section_id, source, state)

    runtime.station_b.controller.set_track_state = fail_b_clear  # type: ignore[method-assign]
    page.state_selector.setCurrentIndex(page.state_selector.findData(TrackState.CLEAR))
    qtbot.mouseClick(page.apply_button, Qt.LeftButton)

    assert runtime.station_a.controller.snapshot.tracks["Q2"] is TrackState.OCCUPIED
    assert runtime.station_b.controller.snapshot.tracks["Q2"] is TrackState.OCCUPIED
    assert "部分失败" in page.result_label.text()


def test_signal_and_tsr_pages_write_only_selected_station(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, runtime = _window(qtbot)
    signal_page = window.signal_operations_page
    signal_page.station_selector.setCurrentText("B站")
    signal_page.signal_selector.setCurrentText("SB")
    signal_page.failure_checkbox.setChecked(True)
    qtbot.mouseClick(signal_page.apply_button, Qt.LeftButton)

    assert "SB" in runtime.station_b.controller.runtime.failed_red_lamp_ids
    assert "SB" not in runtime.station_a.controller.runtime.failed_red_lamp_ids
    assert "目标=B站" in signal_page.result_label.text()

    tsr_page = window.tsr_operations_page
    tsr_page.station_selector.setCurrentText("B站")
    tsr_page.id_input.setCurrentText("TSR-B-TEST")
    qtbot.mouseClick(tsr_page.prestore_button, Qt.LeftButton)
    assert any(
        item.tsr_id == "TSR-B-TEST"
        for item in runtime.station_b.controller.snapshot.temporary_speeds
    )
    assert runtime.station_a.controller.snapshot.temporary_speeds == ()


def test_leu_page_compares_both_stations_and_exposes_detail_tabs(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, _runtime = _window(qtbot)
    page = window.leu_comparison_page

    assert page.summary_table.rowCount() == 2
    assert page.summary_table.item(0, 0).text() == "A站"
    assert page.summary_table.item(1, 0).text() == "B站"
    assert [page.detail_tabs.tabText(i) for i in range(page.detail_tabs.count())] == [
        "逻辑字段", "HEX/CRC", "教学位流"
    ]


def test_direction_request_is_always_sent_by_station_a(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, runtime = _window(qtbot)
    calls: list[tuple[str, RunningDirection]] = []

    def request_a(direction: RunningDirection) -> OperationResult:
        calls.append(("A", direction))
        return OperationResult(False, "测试拒绝")

    def request_b(direction: RunningDirection) -> OperationResult:
        calls.append(("B", direction))
        return OperationResult(True, "不应调用")

    runtime.station_a.controller.request_direction_change = request_a  # type: ignore[method-assign]
    runtime.station_b.controller.request_direction_change = request_b  # type: ignore[method-assign]
    page = window.direction_operations_page
    page.direction_selector.setCurrentIndex(
        page.direction_selector.findData(RunningDirection.B_TO_A)
    )

    qtbot.mouseClick(page.request_button, Qt.LeftButton)

    assert calls == [("A", RunningDirection.B_TO_A)]
    assert "目标=A站" in page.result_label.text()
    assert "测试拒绝" in page.result_label.text()


def test_direction_disconnect_drill_requests_a_before_faulting_b(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, runtime = _window(qtbot)
    order: list[str] = []
    page = window.direction_operations_page

    def request_a(_direction: RunningDirection) -> OperationResult:
        order.append("request:A")
        return OperationResult(True, "请求已排队")

    def fault_b(station_id: str, enabled: bool) -> OperationResult:
        order.append(f"fault:{station_id}:{enabled}")
        return OperationResult(True, "教学网络故障已注入")

    runtime.station_a.controller.request_direction_change = request_a  # type: ignore[method-assign]
    page._fault_handler = fault_b

    qtbot.mouseClick(page.disconnect_drill_button, Qt.LeftButton)

    assert order == ["request:A", "fault:B:True"]
    assert "目标=A/B双站" in page.result_label.text()
    assert "成功" in page.result_label.text()


def test_network_page_exposes_reversible_b_station_fault_controls(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, runtime = _window(qtbot)
    page = window.network_status_page

    qtbot.mouseClick(page.inject_button, Qt.LeftButton)
    assert runtime.station_b.controller.snapshot.connection_state.value == "DEGRADED"
    assert "目标=B站" in page.result_label.text()
    qtbot.mouseClick(page.restore_button, Qt.LeftButton)
    assert runtime.station_b.controller.snapshot.connection_state.value == "HEALTHY"


def test_train_page_controls_unique_cross_station_coordinator(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, runtime = _window(qtbot)
    assert runtime.station_a.controller.establish_route("A_DEPART").success
    page = window.train_operations_page

    qtbot.mouseClick(page.create_button, Qt.LeftButton)
    qtbot.mouseClick(page.dispatch_button, Qt.LeftButton)
    qtbot.mouseClick(page.start_button, Qt.LeftButton)

    train = window.train_coordinator.trains["T001"]
    assert train.status is DualTrainStatus.RUNNING
    assert train.section_id == "A_T1"
    assert page.train_table.rowCount() == 1
    assert page.train_table.item(0, 0).text() == "T001"
    assert page.train_table.columnCount() == 9
    assert "版本=0" not in page.result_label.text()

    qtbot.mouseClick(page.pause_button, Qt.LeftButton)
    assert train.status is DualTrainStatus.STOPPED
    qtbot.mouseClick(page.reset_button, Qt.LeftButton)
    assert train.status is DualTrainStatus.RESET


def test_every_scenario_control_object_exists_in_dual_window(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, _runtime = _window(qtbot)

    for scenario in DELIVERY_SCENARIOS:
        for object_name in scenario.control_object_names:
            button = window.findChild(QPushButton, object_name)
            assert button is not None, f"{scenario.scenario_id}: {object_name}"
            assert button.text().strip()


def test_real_tcp_runtime_runs_forward_changes_direction_and_runs_reverse(
    tmp_path, qtbot
) -> None:  # type: ignore[no-untyped-def]
    """用真实回环 TCP 演练正向到达、正常改方和反向到达。"""
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
        qtbot.waitUntil(
            lambda: (
                window.aggregator.snapshot is not None
                and not window.aggregator.snapshot.operation_locked
            ),
            timeout=4000,
        )
        assert runtime.station_a.controller.establish_route("A_DEPART").success
        forward = window.train_coordinator.create_train()
        assert window.train_coordinator.dispatch(forward.train_id).success
        assert window.train_coordinator.start().success
        window.train_coordinator.tick(300.0)
        assert forward.status is DualTrainStatus.ARRIVED

        assert window.train_coordinator.reset().success
        assert runtime.station_a.controller.cancel_route("A_DEPART").success
        # 列车快速步进会连续产生多份状态同步；改方前等待两站都看到对方
        # 最终空闲版本，模拟操作员确认改方前置条件的真实停顿。
        qtbot.waitUntil(
            lambda: (
                runtime.station_a.controller.peer_snapshot is not None
                and runtime.station_b.controller.peer_snapshot is not None
                and runtime.station_a.controller.peer_snapshot.state_version
                >= runtime.station_b.controller.snapshot.state_version
                and runtime.station_b.controller.peer_snapshot.state_version
                >= runtime.station_a.controller.snapshot.state_version
            ),
            timeout=4000,
        )
        changed = runtime.station_a.controller.request_direction_change(
            RunningDirection.B_TO_A
        )
        assert changed.success
        qtbot.waitUntil(
            lambda: (
                runtime.station_a.controller.snapshot.running_direction == "B_TO_A"
                and runtime.station_b.controller.snapshot.running_direction == "B_TO_A"
                and not runtime.station_a.controller.snapshot.direction_operation_locked
                and not runtime.station_b.controller.snapshot.direction_operation_locked
            ),
            timeout=4000,
        )

        assert runtime.station_b.controller.establish_route("B_DEPART").success
        reverse = window.train_coordinator.create_train()
        assert window.train_coordinator.dispatch(reverse.train_id).success
        assert window.train_coordinator.start().success
        window.train_coordinator.tick(300.0)
        assert reverse.status is DualTrainStatus.ARRIVED

        assert window.train_coordinator.reset().success
        assert runtime.station_b.controller.cancel_route("B_DEPART").success
        qtbot.waitUntil(
            lambda: (
                runtime.station_a.controller.peer_snapshot is not None
                and runtime.station_b.controller.peer_snapshot is not None
                and runtime.station_a.controller.peer_snapshot.state_version
                >= runtime.station_b.controller.snapshot.state_version
                and runtime.station_b.controller.peer_snapshot.state_version
                >= runtime.station_a.controller.snapshot.state_version
            ),
            timeout=4000,
        )
        direction_page = window.direction_operations_page
        direction_page.direction_selector.setCurrentIndex(
            direction_page.direction_selector.findData(RunningDirection.A_TO_B)
        )
        qtbot.mouseClick(direction_page.disconnect_drill_button, Qt.LeftButton)
        assert "成功" in direction_page.result_label.text()
        qtbot.waitUntil(
            lambda: (
                runtime.station_a.controller.snapshot.connection_state.value
                != "HEALTHY"
                and runtime.station_b.controller.snapshot.connection_state.value
                != "HEALTHY"
            ),
            timeout=4000,
        )
        qtbot.mouseClick(window.network_status_page.restore_button, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: (
                runtime.station_a.controller.snapshot.connection_state.value
                == "HEALTHY"
                and runtime.station_b.controller.snapshot.connection_state.value
                == "HEALTHY"
            ),
            timeout=4000,
        )
        qtbot.waitUntil(
            lambda: (
                runtime.station_a.controller.snapshot.running_direction
                == runtime.station_b.controller.snapshot.running_direction
                and not runtime.station_a.controller.snapshot.direction_operation_locked
                and not runtime.station_b.controller.snapshot.direction_operation_locked
            ),
            timeout=4000,
        )
    finally:
        window.close()

    assert not runtime.station_a.network_thread.thread.isRunning()
    assert not runtime.station_b.network_thread.thread.isRunning()
