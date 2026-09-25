"""双站同屏模式的真实 TCP 端到端验收。"""

import socket
import sqlite3
from pathlib import Path

from PyQt5.QtCore import Qt

from app.core.enums import ConnectionState, RunningDirection, SignalAspect, TrackState
from app.dual_application import DualLifecycleState, DualStationApplication
from app.ui.dual_main_window import DualStationMainWindow
from tests.integration.test_dual_application_integration import (
    _copy_configs_with_port,
    _free_port,
)


def test_real_window_handshake_sync_fault_and_reconnect(
    tmp_path: Path, qtbot
) -> None:  # type: ignore[no-untyped-def]
    """真实 HELLO/ACK 后完成全量同步，并能从 B 站链路故障自动恢复。"""
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
                and not window.aggregator.snapshot.operation_locked
            ),
            timeout=5000,
        )
        model = window.aggregator.snapshot
        assert model is not None
        assert runtime.station_a.controller.peer_snapshot is not None
        assert runtime.station_b.controller.peer_snapshot is not None
        assert model.station_a.network_sent > 0 and model.station_a.network_received > 0
        assert model.station_b.network_sent > 0 and model.station_b.network_received > 0
        track_page = window.track_operations_page
        track_page.target_selector.setCurrentText("共享区间")
        track_page.section_selector.setCurrentText("Q3")
        track_page.state_selector.setCurrentIndex(
            track_page.state_selector.findData(TrackState.OCCUPIED)
        )
        qtbot.mouseClick(track_page.apply_button, Qt.LeftButton)
        assert runtime.station_a.controller.snapshot.tracks["Q3"] is TrackState.OCCUPIED
        assert runtime.station_b.controller.snapshot.tracks["Q3"] is TrackState.OCCUPIED

        track_page.state_selector.setCurrentIndex(
            track_page.state_selector.findData(TrackState.CLEAR)
        )
        qtbot.mouseClick(track_page.apply_button, Qt.LeftButton)
        qtbot.mouseClick(window.network_status_page.inject_button, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: (
                window.aggregator.snapshot is not None
                and window.aggregator.snapshot.operation_locked
                and not window.aggregator.snapshot.communication_healthy
            ),
            timeout=4000,
        )
        disconnected = window.aggregator.snapshot
        assert disconnected is not None
        counters_before_recovery = (
            disconnected.station_a.network_sent,
            disconnected.station_a.network_received,
            disconnected.station_b.network_sent,
            disconnected.station_b.network_received,
        )

        qtbot.mouseClick(window.network_status_page.restore_button, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: (
                window.aggregator.snapshot is not None
                and window.aggregator.snapshot.communication_healthy
                and not window.aggregator.snapshot.operation_locked
            ),
            timeout=5000,
        )
        recovered = window.aggregator.snapshot
        assert recovered is not None
        counters_after_recovery = (
            recovered.station_a.network_sent,
            recovered.station_a.network_received,
            recovered.station_b.network_sent,
            recovered.station_b.network_received,
        )
        assert all(
            after > before
            for before, after in zip(
                counters_before_recovery, counters_after_recovery, strict=True
            )
        )
        peer_at_a = runtime.station_a.controller.peer_snapshot
        peer_at_b = runtime.station_b.controller.peer_snapshot
        assert peer_at_a is not None and peer_at_b is not None
        assert peer_at_a.boundary_states["Q3"] is TrackState.CLEAR
        assert peer_at_b.boundary_states["Q3"] is TrackState.CLEAR
        assert peer_at_a.state_version >= recovered.station_b.state_version
        assert peer_at_b.state_version >= recovered.station_a.state_version
    finally:
        assert window.close()

    assert not runtime.station_a.network_thread.thread.isRunning()
    assert not runtime.station_b.network_thread.thread.isRunning()


def test_occupied_a_listener_port_prevents_b_start(
    tmp_path: Path, qtbot
) -> None:  # type: ignore[no-untyped-def]
    """A 无法 bind/listen 时，双站编排器必须停在失败态且不启动 B。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = int(occupied.getsockname()[1])
        config_dir = tmp_path / "configs"
        _copy_configs_with_port(config_dir, port)
        runtime = DualStationApplication.build(
            config_dir=config_dir, data_root=tmp_path / "data"
        )
        runtime.start()
        qtbot.waitUntil(
            lambda: runtime.state is DualLifecycleState.FAILED,
            timeout=3000,
        )

    assert "A站启动失败" in runtime.failure_reason
    assert not runtime.station_b.network_thread.thread.isRunning()
    assert runtime.stop(timeout_ms=2000)
    assert runtime.station_a.controller.snapshot.connection_state is not ConnectionState.HEALTHY
    assert runtime.station_a.controller.snapshot.direction_operation_locked


def test_seven_course_scenarios_run_through_real_dual_window_and_reset(
    tmp_path: Path, qtbot
) -> None:  # type: ignore[no-untyped-def]
    """顺序执行七类课程场景，并核对 UI 状态、持久化日志和最终复位。"""
    config_dir = tmp_path / "configs"
    data_root = tmp_path / "data"
    _copy_configs_with_port(config_dir, _free_port())
    runtime = DualStationApplication.build(
        config_dir=config_dir, data_root=data_root
    )
    window = DualStationMainWindow(runtime)
    qtbot.addWidget(window)
    runtime.start()
    try:
        qtbot.waitUntil(
            lambda: (
                window.aggregator.snapshot is not None
                and window.aggregator.snapshot.communication_healthy
                and not window.aggregator.snapshot.operation_locked
            ),
            timeout=5000,
        )

        # 1. 全空闲基线：建立并取消 A 站发车进路。
        a_detail = window.station_a_detail
        a_detail.route_selector.setCurrentText("A_DEPART")
        qtbot.mouseClick(a_detail.establish_route_button, Qt.LeftButton)
        assert "A_DEPART" in runtime.station_a.controller.snapshot.active_route_ids
        qtbot.mouseClick(a_detail.cancel_route_button, Qt.LeftButton)
        assert runtime.station_a.controller.snapshot.active_route_ids == ()

        # 2. 区间占用：共享输入必须同时作用于 A/B，再干净出清。
        track_page = window.track_operations_page
        track_page.target_selector.setCurrentText("共享区间")
        track_page.section_selector.setCurrentText("Q3")
        track_page.state_selector.setCurrentIndex(
            track_page.state_selector.findData(TrackState.OCCUPIED)
        )
        qtbot.mouseClick(track_page.apply_button, Qt.LeftButton)
        assert runtime.station_a.controller.snapshot.tracks["Q3"] is TrackState.OCCUPIED
        assert runtime.station_b.controller.snapshot.tracks["Q3"] is TrackState.OCCUPIED
        track_page.state_selector.setCurrentIndex(
            track_page.state_selector.findData(TrackState.CLEAR)
        )
        qtbot.mouseClick(track_page.apply_button, Qt.LeftButton)
        assert runtime.station_a.controller.snapshot.tracks["Q3"] is TrackState.CLEAR
        assert runtime.station_b.controller.snapshot.tracks["Q3"] is TrackState.CLEAR

        # 3. 轨道故障：保护码可见，清除后双站恢复一致空闲。
        track_page.section_selector.setCurrentText("Q2")
        track_page.state_selector.setCurrentIndex(
            track_page.state_selector.findData(TrackState.FAULT_OCCUPIED)
        )
        qtbot.mouseClick(track_page.apply_button, Qt.LeftButton)
        assert runtime.station_a.controller.snapshot.tracks["Q2"] is TrackState.FAULT_OCCUPIED
        assert runtime.station_a.controller.snapshot.codes["Q2"].code.value == "HU"
        track_page.state_selector.setCurrentIndex(
            track_page.state_selector.findData(TrackState.CLEAR)
        )
        qtbot.mouseClick(track_page.apply_button, Qt.LeftButton)
        assert runtime.station_a.controller.snapshot.tracks["Q2"] is TrackState.CLEAR
        assert runtime.station_b.controller.snapshot.tracks["Q2"] is TrackState.CLEAR

        # 4. 红灯灯丝故障：严重保护显示后可清除。
        signal_page = window.signal_operations_page
        track_page.section_selector.setCurrentText("Q1")
        track_page.state_selector.setCurrentIndex(
            track_page.state_selector.findData(TrackState.FAULT_OCCUPIED)
        )
        qtbot.mouseClick(track_page.apply_button, Qt.LeftButton)
        assert runtime.station_a.controller.snapshot.signals["SA"].aspect is SignalAspect.RED
        signal_page.station_selector.setCurrentText("A站")
        signal_page.signal_selector.setCurrentText("SA")
        signal_page.failure_checkbox.setChecked(True)
        qtbot.mouseClick(signal_page.apply_button, Qt.LeftButton)
        assert runtime.station_a.controller.snapshot.signals["SA"].aspect is SignalAspect.RED_LAMP_FAILURE
        signal_page.failure_checkbox.setChecked(False)
        qtbot.mouseClick(signal_page.apply_button, Qt.LeftButton)
        assert "SA" not in runtime.station_a.controller.runtime.failed_red_lamp_ids
        track_page.state_selector.setCurrentIndex(
            track_page.state_selector.findData(TrackState.CLEAR)
        )
        qtbot.mouseClick(track_page.apply_button, Qt.LeftButton)
        assert runtime.station_a.controller.snapshot.tracks["Q1"] is TrackState.CLEAR
        assert runtime.station_b.controller.snapshot.tracks["Q1"] is TrackState.CLEAR

        # 5. 临时限速：预存、执行、LEU 选报及撤销都从真实页面触发。
        tsr_page = window.tsr_operations_page
        tsr_page.station_selector.setCurrentText("A站")
        tsr_page.id_input.setCurrentText("TSR-E2E")
        qtbot.mouseClick(tsr_page.prestore_button, Qt.LeftButton)
        qtbot.mouseClick(tsr_page.activate_button, Qt.LeftButton)
        assert any(
            item.tsr_id == "TSR-E2E" and item.state.value == "ACTIVE"
            for item in runtime.station_a.controller.snapshot.temporary_speeds
        )
        assert runtime.station_a.controller.snapshot.telegram.mode.value == "SELECTED"
        qtbot.mouseClick(tsr_page.cancel_button, Qt.LeftButton)
        assert any(
            item.tsr_id == "TSR-E2E" and item.state.value == "CANCELLED"
            for item in runtime.station_a.controller.snapshot.temporary_speeds
        )

        # 6. 正常改方：仅 A 发起，等待真实 TCP 四阶段事务在两站落稳。
        qtbot.waitUntil(
            lambda: (
                runtime.station_a.controller.peer_snapshot is not None
                and runtime.station_b.controller.peer_snapshot is not None
                and runtime.station_a.controller.peer_snapshot.state_version
                >= runtime.station_b.controller.snapshot.state_version
                and runtime.station_b.controller.peer_snapshot.state_version
                >= runtime.station_a.controller.snapshot.state_version
            ),
            timeout=5000,
        )
        direction_page = window.direction_operations_page
        direction_page.direction_selector.setCurrentIndex(
            direction_page.direction_selector.findData(RunningDirection.B_TO_A)
        )
        qtbot.mouseClick(direction_page.request_button, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: (
                runtime.station_a.controller.snapshot.running_direction == "B_TO_A"
                and runtime.station_b.controller.snapshot.running_direction == "B_TO_A"
                and window.aggregator.snapshot is not None
                and not window.aggregator.snapshot.operation_locked
            ),
            timeout=5000,
        )

        # 7. 改方中断线：发出反向请求后立即断 B，恢复后必须重新同步并解锁。
        direction_page.direction_selector.setCurrentIndex(
            direction_page.direction_selector.findData(RunningDirection.A_TO_B)
        )
        qtbot.mouseClick(direction_page.disconnect_drill_button, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: (
                window.aggregator.snapshot is not None
                and window.aggregator.snapshot.operation_locked
                and not window.aggregator.snapshot.communication_healthy
            ),
            timeout=4000,
        )
        qtbot.mouseClick(window.network_status_page.restore_button, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: (
                window.aggregator.snapshot is not None
                and window.aggregator.snapshot.communication_healthy
                and window.aggregator.snapshot.direction_consistent
                and not window.aggregator.snapshot.operation_locked
            ),
            timeout=5000,
        )

        # 两站快照和结果栏提供可见证据；操作日志在关闭前已由 SQLite 接收。
        assert "成功" in track_page.result_label.text()
        assert "成功" in signal_page.result_label.text()
        assert "成功" in tsr_page.result_label.text()
        assert runtime.station_a.controller.snapshot.tracks["Q2"] is TrackState.CLEAR
        assert runtime.station_a.controller.snapshot.tracks["Q3"] is TrackState.CLEAR
        assert runtime.station_b.controller.snapshot.tracks["Q2"] is TrackState.CLEAR
        assert runtime.station_b.controller.snapshot.tracks["Q3"] is TrackState.CLEAR
        assert runtime.station_a.controller.snapshot.active_route_ids == ()
    finally:
        assert window.close()

    # 关闭后直接从真实数据库重开读取，证明关键场景日志已经持久化。
    with sqlite3.connect(data_root / "A" / "tcc_a.db") as connection:
        operations_a = "\n".join(
            row[0]
            for row in connection.execute(
                "SELECT operation FROM operation_logs ORDER BY id"
            )
        )
    for expected in (
        "建立进路 A_DEPART",
        "取消进路 A_DEPART",
        "设置区段 Q2",
        "设置区段 Q3",
        "设置灯丝 SA",
        "预存临时限速 TSR-E2E",
        "执行临时限速 TSR-E2E",
        "撤销临时限速 TSR-E2E",
        "申请区间改方",
    ):
        assert expected in operations_a
    with sqlite3.connect(data_root / "B" / "tcc_b.db") as connection:
        operations_b = "\n".join(
            row[0]
            for row in connection.execute(
                "SELECT operation FROM operation_logs ORDER BY id"
            )
        )
    for expected in ("设置区段 Q1", "设置区段 Q2", "设置区段 Q3"):
        assert expected in operations_b
