"""单进程双运行时的真实 TCP、SQLite 与 Qt 线程集成测试。"""

import json
import shutil
import socket
from pathlib import Path

from app.core.enums import ConnectionState
from app.dual_application import DualStationApplication


ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    """由操作系统分配测试端口，降低与本机其他程序冲突的概率。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _copy_configs_with_port(target: Path, port: int) -> None:
    shutil.copytree(ROOT / "configs", target)
    for filename in ("station_a.json", "station_b.json"):
        path = target / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["network"]["port"] = port
        payload["network"]["heartbeat_interval_ms"] = 50
        payload["network"]["degraded_after_ms"] = 500
        payload["network"]["disconnect_after_ms"] = 1000
        payload["network"]["reconnect_delays_ms"] = [20, 40, 50]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_real_dual_runtime_reaches_healthy_and_closes_without_leaks(
    tmp_path: Path, qtbot
) -> None:  # type: ignore[no-untyped-def]
    """A 真监听后 B 握手成功，关闭后两条 Qt 网络线程均应退出。"""
    config_dir = tmp_path / "configs"
    data_root = tmp_path / "data"
    _copy_configs_with_port(config_dir, _free_port())
    application = DualStationApplication.build(
        config_dir=config_dir, data_root=data_root
    )

    application.start()
    try:
        qtbot.waitUntil(
            lambda: (
                application.station_a.controller.snapshot.connection_state
                is ConnectionState.HEALTHY
                and application.station_b.controller.snapshot.connection_state
                is ConnectionState.HEALTHY
                and application.interface_status.startup_complete
            ),
            timeout=4000,
        )
        active_startup_lock = [
            (
                station.controller.config.station.station_id,
                station.controller.snapshot.connection_state.value,
                station.controller.snapshot.direction_operation_locked,
                station.controller.snapshot.telegram.mode.value,
                station.controller.snapshot.telegram.reason,
                item.level.value,
                item.message,
            )
            for station in (application.station_a, application.station_b)
            for item in station.controller.snapshot.alarms
            if item.code == "LEU_DEFAULT"
            and item.active
            and item.level.value == "CRITICAL"
            and "方向或进路处于安全锁闭" in item.message
        ]
        assert not active_startup_lock, active_startup_lock
        assert (data_root / "A" / "tcc_a.db").is_file()
        assert (data_root / "B" / "tcc_b.db").is_file()
    finally:
        stopped = application.stop(timeout_ms=2000)

    assert stopped
    assert not application.station_a.network_thread.thread.isRunning()
    assert not application.station_b.network_thread.thread.isRunning()


def test_idle_healthy_dual_station_stays_unlocked_after_multiple_timeout_windows(
    tmp_path: Path, qtbot
) -> None:  # type: ignore[no-untyped-def]
    """空闲区间连续收到心跳时，不得因没有状态变化而快照过期。"""
    config_dir = tmp_path / "configs"
    _copy_configs_with_port(config_dir, _free_port())
    application = DualStationApplication.build(
        config_dir=config_dir, data_root=tmp_path / "data"
    )

    application.start()
    try:
        qtbot.waitUntil(
            lambda: (
                application.station_a.controller.snapshot.connection_state
                is ConnectionState.HEALTHY
                and application.station_b.controller.snapshot.connection_state
                is ConnectionState.HEALTHY
                and not application.station_a.controller.snapshot.direction_operation_locked
                and not application.station_b.controller.snapshot.direction_operation_locked
            ),
            timeout=4000,
        )
        # 当前测试配置的 disconnect_after_ms 为 1000；静置两个以上周期，
        # 若心跳没有刷新 PeerSnapshot.received_at_ms，此处会稳定重现锁闭。
        qtbot.wait(2300)
        for station in (application.station_a, application.station_b):
            snapshot = station.controller.snapshot
            assert snapshot.connection_state is ConnectionState.HEALTHY
            assert snapshot.direction_operation_locked is False
            assert not any(
                alarm.code == "PEER_SNAPSHOT_STALE" for alarm in snapshot.alarms
            )
    finally:
        assert application.stop(timeout_ms=2000)
