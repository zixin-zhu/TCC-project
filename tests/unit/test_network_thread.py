"""Qt worker-object 的线程归属、退避和可中断退出测试。"""

import socket
import time

import pytest
from PyQt5.QtCore import QCoreApplication, QThread

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
