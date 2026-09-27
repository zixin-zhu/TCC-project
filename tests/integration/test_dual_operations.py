"""双站真实操作页与唯一列车协调器的界面集成测试。"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QPushButton

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


def _click_pending_action(detail, qtbot, action: str = "同意") -> None:  # type: ignore[no-untyped-def]
    """点击待处理表格中第一条申请的行内操作按钮。"""
    assert detail.shared_pending_table.rowCount() == 1
    action_cell = detail.shared_pending_table.cellWidget(0, 4)
    assert action_cell is not None
    button = next(
        item for item in action_cell.findChildren(QPushButton) if item.text() == action
    )
    qtbot.mouseClick(button, Qt.LeftButton)


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
    assert runtime.station_a.controller.snapshot.tracks["Q2"] is TrackState.CLEAR
    assert runtime.station_b.controller.snapshot.tracks["Q2"] is TrackState.CLEAR
    assert "已提交申请，正在等待 A/B 站确认" in page.shared_request_status.text()
    assert window.station_a_detail.shared_pending_table.rowCount() == 0
    assert window.station_b_detail.shared_pending_table.rowCount() == 1
    assert [
        window.station_b_detail.shared_pending_table.horizontalHeaderItem(index).text()
        for index in range(5)
    ] == ["申请编号", "时间", "申请站", "内容", "操作"]
    assert "A站申请将Q2区段状态由空闲修改为占用" in window.station_b_detail.shared_pending_table.item(0, 3).text()

    _click_pending_action(window.station_b_detail, qtbot)
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
    _click_pending_action(window.station_b_detail, qtbot)
    assert "对站写入失败" in window.station_b_detail.operation_result.text()
    assert runtime.station_a.controller.snapshot.tracks["Q2"] is TrackState.OCCUPIED
    assert runtime.station_b.controller.snapshot.tracks["Q2"] is TrackState.OCCUPIED


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


def test_direction_request_uses_station_at_current_direction_origin(qtbot) -> None:  # type: ignore[no-untyped-def]
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

    assert calls == []
    assert window.station_a_detail.shared_pending_table.rowCount() == 0
    assert window.station_b_detail.shared_pending_table.rowCount() == 1
    assert "A站申请将方向由A_TO_B改为B_TO_A" in window.station_b_detail.shared_pending_table.item(0, 3).text()
    _click_pending_action(window.station_b_detail, qtbot)
    assert calls == [("A", RunningDirection.B_TO_A)]
    assert "目标=A站" in page.result_label.text()
    assert "已提交申请" in page.result_label.text()
    assert "测试拒绝" in window.station_b_detail.operation_result.text()
    assert page.table.rowCount() == 2
    assert page.table.item(0, 0).text() == "A站（请求方）"
    assert page.table.item(1, 0).text() == "B站（应答方）"
    assert "方向一致" in page.precondition_label.text()


def test_direction_requester_role_reverses_after_direction_switch(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, runtime = _window(qtbot)
    assert runtime.station_a.controller.restore_authoritative_direction(
        RunningDirection.B_TO_A
    ).success
    assert runtime.station_b.controller.restore_authoritative_direction(
        RunningDirection.B_TO_A
    ).success
    window.aggregator.update_a(runtime.station_a.controller.snapshot)
    window.aggregator.update_b(runtime.station_b.controller.snapshot)
    calls: list[str] = []

    runtime.station_a.controller.request_direction_change = (  # type: ignore[method-assign]
        lambda _direction: (calls.append("A") or OperationResult(False, "不应调用"))
    )
    runtime.station_b.controller.request_direction_change = (  # type: ignore[method-assign]
        lambda direction: (calls.append("B") or OperationResult(False, "测试拒绝"))
    )
    page = window.direction_operations_page
    page.direction_selector.setCurrentIndex(
        page.direction_selector.findData(RunningDirection.A_TO_B)
    )
    qtbot.mouseClick(page.request_button, Qt.LeftButton)

    assert calls == []
    assert window.station_a_detail.shared_pending_table.rowCount() == 1
    assert window.station_b_detail.shared_pending_table.rowCount() == 0
    assert "B站申请将方向由B_TO_A改为A_TO_B" in window.station_a_detail.shared_pending_table.item(0, 3).text()
    _click_pending_action(window.station_a_detail, qtbot)
    assert calls == ["B"]
    assert page.table.item(0, 0).text() == "A站（应答方）"
    assert page.table.item(1, 0).text() == "B站（请求方）"


def test_each_station_control_exposes_shared_request_panel_and_network_buttons(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, _runtime = _window(qtbot)

    assert window.station_a_detail.shared_pending_table.columnCount() == 5
    assert window.station_b_detail.shared_pending_table.columnCount() == 5
    assert window.station_a_detail.findChild(QPushButton, "approveSharedRequestButtonA") is None
    assert window.station_b_detail.findChild(QPushButton, "approveSharedRequestButtonB") is None
    assert window.station_a_detail.findChild(QPushButton, "injectANetworkFaultButton") is not None
    assert window.station_b_detail.findChild(QPushButton, "injectBNetworkFaultButton") is not None
    assert window.findChild(QPushButton, "globalRecoverDirectionButton") is not None
    assert window.station_a_detail.findChild(QPushButton, "recoverDirectionButtonA") is None
    assert window.station_b_detail.findChild(QPushButton, "recoverDirectionButtonB") is None
    assert window.station_a_detail.findChild(QPushButton, "reviewDirectionRequestButtonA") is None
    assert window.station_b_detail.findChild(QPushButton, "reviewDirectionRequestButtonB") is None


def test_direction_disconnect_drill_faults_current_responder(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, runtime = _window(qtbot)
    order: list[str] = []
    page = window.direction_operations_page

    def request_a(_direction: RunningDirection) -> OperationResult:
        order.append("request:A")
        return OperationResult(True, "请求已排队")

    def request_b(_direction: RunningDirection) -> OperationResult:
        order.append("request:B")
        return OperationResult(True, "请求已排队")

    def fault_b(station_id: str, enabled: bool) -> OperationResult:
        order.append(f"fault:{station_id}:{enabled}")
        return OperationResult(True, "教学网络故障已注入")

    runtime.station_a.controller.request_direction_change = request_a  # type: ignore[method-assign]
    runtime.station_b.controller.request_direction_change = request_b  # type: ignore[method-assign]
    page._fault_handler = fault_b

    qtbot.mouseClick(page.disconnect_drill_button, Qt.LeftButton)

    assert order == ["fault:B:True"]
    assert window.station_a_detail.shared_pending_table.rowCount() == 0
    assert window.station_b_detail.shared_pending_table.rowCount() == 1
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


def test_network_page_exposes_reversible_a_station_fault_controls(qtbot) -> None:  # type: ignore[no-untyped-def]
    window, runtime = _window(qtbot)
    page = window.network_status_page

    qtbot.mouseClick(page.inject_a_button, Qt.LeftButton)
    assert runtime.station_a.controller.snapshot.connection_state.value == "DEGRADED"
    assert "A站" in page.result_label.text()
    qtbot.mouseClick(page.restore_a_button, Qt.LeftButton)
    assert runtime.station_a.controller.snapshot.connection_state.value == "HEALTHY"


def test_network_page_labels_total_and_business_counters_distinctly(qtbot) -> None:  # type: ignore[no-untyped-def]
    """通信页必须明确区分协议总数、业务报文数和心跳数。"""
    window, runtime = _window(qtbot)
    page = window.network_status_page
    runtime.station_a.controller.update_network_metrics(
        received=20,
        sent=22,
        business_received=3,
        business_sent=4,
        heartbeat_received=17,
        heartbeat_sent=18,
    )
    window.aggregator.update_a(runtime.station_a.controller.snapshot)
    window.aggregator.update_b(runtime.station_b.controller.snapshot)

    headers = [
        page.table.horizontalHeaderItem(index).text()
        for index in range(page.table.columnCount())
    ]
    values = [
        page.table.item(row, column).text()
        for row in range(page.table.rowCount())
        for column in range(page.table.columnCount())
    ]
    assert headers == [
        "站点",
        "角色",
        "连接状态",
        "协议发送",
        "协议接收",
        "业务发送",
        "业务接收",
        "心跳发送",
        "心跳接收",
        "状态版本",
        "作业锁闭",
    ]
    assert "22" in values
    assert "20" in values
    assert "4" in values
    assert "3" in values


def test_all_formal_comboboxes_have_role_width(qtbot) -> None:  # type: ignore[no-untyped-def]
    """双站窗口和嵌入的单站详情页所有下拉框都必须走公共宽度策略。"""
    window, _runtime = _window(qtbot)
    combos = window.findChildren(QComboBox)

    assert combos
    assert all(combo.property("comboRole") for combo in combos)
    assert all(combo.minimumWidth() >= 100 for combo in combos)
    assert all(combo.view().minimumWidth() >= combo.minimumWidth() for combo in combos)


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
        # 当前方向已为 B→A，反向改方由 B 请求、A 应答，因此演练会中断 A 链路。
        qtbot.mouseClick(window.network_status_page.restore_a_button, Qt.LeftButton)
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
