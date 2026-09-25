"""Qt worker-object 的线程归属、退避和可中断退出测试。"""

import socket
import time

import pytest
from PyQt5.QtCore import QCoreApplication, QThread
from PyQt5.QtTest import QSignalSpy

from app.core.enums import NetworkRole
from app.core.exceptions import ProtocolError
from app.network.network_worker import (
    NetworkThreadController,
    NetworkWorker,
    PeerConnectionRunner,
    PeerNetworkSettings,
    ReconnectBackoff,
)
from app.network.protocol import MessageType


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_reconnect_backoff_is_capped_at_last_configured_delay() -> None:
    backoff = ReconnectBackoff((1000, 2000, 5000))

    assert [backoff.next_delay_ms() for _ in range(6)] == [1000, 2000, 5000, 5000, 5000, 5000]
    backoff.reset()
    assert backoff.next_delay_ms() == 1000


def test_outgoing_queue_is_bounded() -> None:
    runner = PeerConnectionRunner(
        PeerNetworkSettings(
            role=NetworkRole.CLIENT,
            host="127.0.0.1",
            port=9500,
            station_id="B",
            peer_station_id="A",
        ),
        state_provider=lambda: {"boundary_states": {}, "state_version": 0},
    )
    for index in range(256):
        runner.submit(MessageType.SIGNAL_STATUS, {"index": index})

    with pytest.raises(ProtocolError, match="发送队列"):
        runner.submit(MessageType.SIGNAL_STATUS, {"index": 256})


def test_network_worker_runs_outside_main_thread_and_stops() -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    main_thread_id = int(QThread.currentThreadId())
    settings = PeerNetworkSettings(
        role=NetworkRole.CLIENT,
        host="127.0.0.1",
        port=_unused_port(),
        station_id="B",
        peer_station_id="A",
        socket_timeout_ms=30,
        reconnect_delays_ms=(20, 40, 50),
    )
    worker = NetworkWorker(settings, state_provider=lambda: {"boundary_states": {}, "state_version": 0})
    controller = NetworkThreadController(worker)

    controller.start()
    deadline = time.monotonic() + 1
    while worker.execution_thread_id is None and time.monotonic() < deadline:
        app.processEvents()
        QThread.msleep(5)

    assert worker.execution_thread_id is not None
    assert worker.execution_thread_id != main_thread_id
    assert controller.stop(timeout_ms=1500)
    assert not controller.thread.isRunning()


def test_server_worker_emits_ready_only_after_listener_is_bound(qtbot) -> None:  # type: ignore[no-untyped-def]
    """若就绪信号提前发出，双站编排器可能在 A 尚未监听时启动 B。"""
    settings = PeerNetworkSettings(
        role=NetworkRole.SERVER,
        host="127.0.0.1",
        port=_unused_port(),
        station_id="A",
        peer_station_id="B",
        socket_timeout_ms=30,
    )
    worker = NetworkWorker(
        settings,
        state_provider=lambda: {"boundary_states": {}, "state_version": 0},
    )
    controller = NetworkThreadController(worker)

    with qtbot.waitSignal(worker.server_ready, timeout=1000) as blocker:
        controller.start()

    assert blocker.args == ["127.0.0.1", settings.port]
    assert controller.stop(timeout_ms=1500)


def test_network_worker_converts_runner_startup_error_to_signal(
    qtbot, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """端口占用等启动异常必须转成信号，不能让工作线程静默退出。"""
    settings = PeerNetworkSettings(
        role=NetworkRole.SERVER,
        host="127.0.0.1",
        port=9501,
        station_id="A",
        peer_station_id="B",
    )
    worker = NetworkWorker(settings, state_provider=lambda: {})
    error_spy = QSignalSpy(worker.error_occurred)
    finished_spy = QSignalSpy(worker.finished)

    def fail_to_start() -> None:
        raise OSError("address already in use")

    monkeypatch.setattr(worker._runner, "run", fail_to_start)

    worker.run()

    assert len(error_spy) == 1
    assert "网络线程启动失败" in error_spy[0][0]
    assert "address already in use" in error_spy[0][0]
    assert len(finished_spy) == 1
