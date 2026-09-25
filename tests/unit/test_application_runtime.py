"""网络线程信号必须经主线程桥接到控制器。"""

from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal

from app.application import ApplicationRuntime, ThreadSafeStateProvider
from app.core.enums import ConnectionState, RunningDirection
from app.network.protocol import MessageType, ProtocolMessage


ROOT = Path(__file__).resolve().parents[2]


class FakeWorker(QObject):
    state_changed = pyqtSignal(object)
    message_received = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    message_sent = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.submitted = []

    def submit(self, message_type, payload, *, state_version):  # type: ignore[no-untyped-def]
        self.submitted.append((message_type, payload, state_version))


class FakeThread:
    def __init__(self, *, stop_result: bool = True) -> None:
        self.started = False
        self.stopped = False
        self.stop_result = stop_result

    def start(self) -> None:
        self.started = True

    def stop(self, *, timeout_ms: int = 3000) -> bool:
        self.stopped = True
        return self.stop_result


def test_thread_safe_provider_returns_copies() -> None:
    provider = ThreadSafeStateProvider()
    original = {"state_version": 1, "boundary_states": {"Q1": "CLEAR"}}
    provider.update(original)
    first = provider()
    first["state_version"] = 99

    assert provider()["state_version"] == 1


def test_runtime_routes_worker_state_signal_to_controller(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    worker = FakeWorker()
    thread = FakeThread()
    runtime = ApplicationRuntime.build(
        station_id="A",
        config_dir=ROOT / "configs",
        data_dir=tmp_path,
        worker=worker,
        network_thread=thread,
    )

    worker.state_changed.emit(ConnectionState.DEGRADED)
    qtbot.waitUntil(
        lambda: runtime.controller.snapshot.connection_state
        is ConnectionState.DEGRADED,
        timeout=1000,
    )

    assert runtime.controller.snapshot.connection_state is ConnectionState.DEGRADED
    runtime.start()
    assert thread.started
    runtime.stop()
    assert thread.stopped


def test_runtime_updates_network_metrics_from_worker_signals(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    worker = FakeWorker()
    runtime = ApplicationRuntime.build(
        station_id="A",
        config_dir=ROOT / "configs",
        data_dir=tmp_path,
        worker=worker,
        network_thread=FakeThread(),
    )
    initial_sent = runtime.controller.snapshot.network_sent

    worker.message_sent.emit(object())
    qtbot.waitUntil(
        lambda: runtime.controller.snapshot.network_sent == initial_sent + 1,
        timeout=1000,
    )

    assert runtime.controller.snapshot.network_sent == initial_sent + 1


def _incoming(message_type, state_version, payload):  # type: ignore[no-untyped-def]
    return ProtocolMessage(
        magic="TCCSIM",
        version=1,
        message_type=message_type,
        message_id=f"test-{message_type.value}-{state_version}",
        sequence=state_version + 1,
        station_id="B",
        peer_station_id="A",
        timestamp_ms=100,
        state_version=state_version,
        payload=payload,
    )


def test_incremental_boundary_update_does_not_require_direction_field(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    worker = FakeWorker()
    runtime = ApplicationRuntime.build(
        station_id="A",
        config_dir=ROOT / "configs",
        data_dir=tmp_path,
        worker=worker,
        network_thread=FakeThread(),
    )
    boundary_ids = [
        item.id
        for item in runtime.controller.config.topology.sections
        if item.id.startswith("Q")
    ]
    full_states = {item: "CLEAR" for item in boundary_ids}
    worker.state_changed.emit(ConnectionState.HEALTHY)
    qtbot.waitUntil(
        lambda: runtime.controller.snapshot.connection_state
        is ConnectionState.HEALTHY,
        timeout=1000,
    )
    submitted_before_sync = len(worker.submitted)
    worker.message_received.emit(
        _incoming(
            MessageType.STATE_SYNC,
            1,
            {
                "state_version": 1,
                "boundary_states": full_states,
                "running_direction": "A_TO_B",
            },
        )
    )
    qtbot.waitUntil(lambda: runtime.peer_sync.snapshot is not None, timeout=1000)
    # 接收对站全量状态只更新本地派生显示，不得无条件回发同一状态，
    # 否则两站会形成 STATE_SYNC 回声循环。
    assert len(worker.submitted) == submitted_before_sync

    worker.message_received.emit(
        _incoming(
            MessageType.TRACK_BOUNDARY,
            2,
            {
                "state_version": 2,
                "boundary_id": boundary_ids[0],
                "state": "OCCUPIED",
            },
        )
    )
    qtbot.waitUntil(
        lambda: runtime.peer_sync.snapshot is not None
        and runtime.peer_sync.snapshot.state_version == 2,
        timeout=1000,
    )

    assert runtime.controller.snapshot.connection_state is not ConnectionState.DEGRADED
    assert runtime.peer_sync.snapshot.state_version == 2


def test_generic_error_message_is_not_misparsed_as_direction_protocol(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    worker = FakeWorker()
    runtime = ApplicationRuntime.build(
        station_id="A",
        config_dir=ROOT / "configs",
        data_dir=tmp_path,
        worker=worker,
        network_thread=FakeThread(),
    )

    worker.message_received.emit(
        _incoming(MessageType.ERROR, 0, {"reason": "普通协议错误"})
    )
    qtbot.wait(20)

    assert runtime.controller.snapshot.connection_state is ConnectionState.DISCONNECTED
    assert any(
        alarm.code == "PEER_PROTOCOL_ERROR"
        for alarm in runtime.controller.snapshot.alarms
    )


def test_direction_reject_error_reaches_direction_state_machine(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    worker = FakeWorker()
    runtime = ApplicationRuntime.build(
        station_id="A",
        config_dir=ROOT / "configs",
        data_dir=tmp_path,
        worker=worker,
        network_thread=FakeThread(),
    )
    boundary_ids = [
        item.id
        for item in runtime.controller.config.topology.sections
        if item.id.startswith("Q")
    ]
    worker.state_changed.emit(ConnectionState.HEALTHY)
    worker.message_received.emit(
        _incoming(
            MessageType.STATE_SYNC,
            1,
            {
                "state_version": 1,
                "boundary_states": {item: "CLEAR" for item in boundary_ids},
                "running_direction": "A_TO_B",
            },
        )
    )
    qtbot.waitUntil(
        lambda: not runtime.controller.snapshot.direction_operation_locked,
        timeout=1000,
    )
    assert runtime.controller.request_direction_change(
        RunningDirection.B_TO_A
    ).success
    prepare = next(
        item for item in reversed(worker.submitted)
        if item[0] is MessageType.DIRECTION_PREPARE
    )
    payload = dict(prepare[1])
    payload.update(
        {
            "kind": "REJECT",
            "reject_code": "PEER_REJECTED",
            "reason": "区间占用",
            "responder_state_version": 1,
        }
    )

    worker.message_received.emit(_incoming(MessageType.ERROR, 1, payload))
    qtbot.waitUntil(
        lambda: not runtime.controller.snapshot.direction_operation_locked,
        timeout=1000,
    )

    assert runtime.controller.snapshot.operation_logs[0].operation == "处理对站改方消息"
    assert not any(
        alarm.code == "PEER_PROTOCOL_ERROR"
        for alarm in runtime.controller.snapshot.alarms
    )


def test_invalid_full_sync_direction_never_enters_peer_snapshot(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    worker = FakeWorker()
    runtime = ApplicationRuntime.build(
        station_id="A",
        config_dir=ROOT / "configs",
        data_dir=tmp_path,
        worker=worker,
        network_thread=FakeThread(),
    )
    boundary_ids = [
        item.id
        for item in runtime.controller.config.topology.sections
        if item.id.startswith("Q")
    ]

    worker.message_received.emit(
        _incoming(
            MessageType.STATE_SYNC,
            1,
            {
                "state_version": 1,
                "boundary_states": {item: "CLEAR" for item in boundary_ids},
                "running_direction": "INVALID",
            },
        )
    )
    qtbot.waitUntil(
        lambda: runtime.controller.snapshot.connection_state
        is ConnectionState.DEGRADED,
        timeout=1000,
    )

    assert runtime.peer_sync.snapshot is None


def test_stop_failure_keeps_controller_open(tmp_path: Path) -> None:
    runtime = ApplicationRuntime.build(
        station_id="A",
        config_dir=ROOT / "configs",
        data_dir=tmp_path,
        worker=FakeWorker(),
        network_thread=FakeThread(stop_result=False),
    )

    assert runtime.stop() is False
    runtime.controller.update_network_metrics(received=1, sent=1)
