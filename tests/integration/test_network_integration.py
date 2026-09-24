"""A Server/B Client 在临时端口上的握手、心跳、同步和重连测试。"""

import socket
import threading
import time
from collections.abc import Callable

from app.core.enums import ConnectionState, NetworkRole
from app.network.network_worker import PeerConnectionRunner, PeerNetworkSettings
from app.network.protocol import MessageType, ProtocolMessage


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("等待网络状态超时")


def _settings(role: NetworkRole, port: int, station: str, peer: str) -> PeerNetworkSettings:
    return PeerNetworkSettings(
        role=role,
        host="127.0.0.1",
        port=port,
        station_id=station,
        peer_station_id=peer,
        heartbeat_interval_ms=40,
        socket_timeout_ms=40,
        degraded_after_ms=300,
        disconnect_after_ms=600,
        reconnect_delays_ms=(20, 40, 50),
    )


def test_delayed_server_causes_client_retry_then_both_sync_and_close_cleanly() -> None:
    port = _free_port()
    stop_a = threading.Event()
    stop_b = threading.Event()
    states_a: list[ConnectionState] = []
    states_b: list[ConnectionState] = []
    timed_states_b: list[tuple[ConnectionState, float]] = []
    received_a: list[ProtocolMessage] = []
    received_b: list[ProtocolMessage] = []
    errors: list[str] = []

    runner_b = PeerConnectionRunner(
        _settings(NetworkRole.CLIENT, port, "B", "A"),
        state_provider=lambda: {"boundary_states": {"AB": "CLEAR"}, "state_version": 2},
        stop_event=stop_b,
        on_state=lambda state: (
            states_b.append(state),
            timed_states_b.append((state, time.monotonic())),
        ),
        on_message=received_b.append,
        on_error=errors.append,
    )
    thread_b = threading.Thread(target=runner_b.run, name="test-client")
    # 断线期间排队的旧增量必须由随后全量同步取代，不能跨会话补发。
    runner_b.submit(MessageType.SIGNAL_STATUS, {"stale": True}, state_version=1)
    thread_b.start()
    _wait_until(lambda: ConnectionState.CONNECTING in states_b)

    runner_a = PeerConnectionRunner(
        _settings(NetworkRole.SERVER, port, "A", "B"),
        state_provider=lambda: {"boundary_states": {"AB": "OCCUPIED"}, "state_version": 4},
        stop_event=stop_a,
        on_state=states_a.append,
        on_message=received_a.append,
        on_error=errors.append,
    )
    thread_a = threading.Thread(target=runner_a.run, name="test-server")
    thread_a.start()

    _wait_until(
        lambda: ConnectionState.HEALTHY in states_a
        and ConnectionState.HEALTHY in states_b
        and any(item.message_type is MessageType.STATE_SYNC for item in received_a)
        and any(item.message_type is MessageType.STATE_SYNC for item in received_b)
    )
    _wait_until(
        lambda: any(item.message_type is MessageType.HEARTBEAT for item in received_a)
        and any(item.message_type is MessageType.HEARTBEAT for item in received_b)
    )

    # 主动关闭服务端，客户端必须保持运行并进入重连；新服务端上线后，
    # 双方重新握手且各自再次发送全量基线，而不是沿用旧会话增量。
    stop_a.set()
    thread_a.join(timeout=2)
    assert not thread_a.is_alive()
    _wait_until(lambda: states_b.count(ConnectionState.CONNECTING) >= 2)
    disconnected_at = next(
        timestamp
        for state, timestamp in reversed(timed_states_b)
        if state is ConnectionState.DISCONNECTED
    )

    stop_a2 = threading.Event()
    runner_a2 = PeerConnectionRunner(
        _settings(NetworkRole.SERVER, port, "A", "B"),
        state_provider=lambda: {"boundary_states": {"AB": "SHUNT_BAD"}, "state_version": 5},
        stop_event=stop_a2,
        on_state=states_a.append,
        on_message=received_a.append,
        on_error=errors.append,
    )
    thread_a2 = threading.Thread(target=runner_a2.run, name="test-server-restarted")
    thread_a2.start()
    _wait_until(
        lambda: states_b.count(ConnectionState.HEALTHY) >= 2
        and sum(item.message_type is MessageType.STATE_SYNC for item in received_b) >= 2
    )
    reconnecting_at = next(
        timestamp
        for state, timestamp in timed_states_b
        if state is ConnectionState.CONNECTING and timestamp > disconnected_at
    )

    stop_a2.set()
    stop_b.set()
    thread_a2.join(timeout=2)
    thread_b.join(timeout=2)

    assert not thread_a2.is_alive()
    assert not thread_b.is_alive()
    assert not errors
    assert reconnecting_at - disconnected_at >= 0.015
    assert not any(item.message_type is MessageType.SIGNAL_STATUS for item in received_a)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as rebound:
        rebound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rebound.bind(("127.0.0.1", port))


def test_pre_handshake_disconnects_advance_client_backoff() -> None:
    """TCP 成功但握手失败不能重置退避，否则会形成一秒重连风暴。"""
    port = _free_port()
    stop = threading.Event()
    accepted_at: list[float] = []

    def reject_before_handshake() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(1)
            listener.settimeout(1)
            for _ in range(3):
                transport, _address = listener.accept()
                accepted_at.append(time.monotonic())
                transport.close()

    server = threading.Thread(target=reject_before_handshake, name="rejecting-server")
    server.start()
    runner = PeerConnectionRunner(
        _settings(NetworkRole.CLIENT, port, "B", "A"),
        state_provider=lambda: {"boundary_states": {"AB": "CLEAR"}, "state_version": 1},
        stop_event=stop,
    )
    client = threading.Thread(target=runner.run, name="backoff-client")
    client.start()

    _wait_until(lambda: len(accepted_at) == 3)
    stop.set()
    server.join(timeout=2)
    client.join(timeout=2)

    assert not server.is_alive()
    assert not client.is_alive()
    assert accepted_at[1] - accepted_at[0] >= 0.015
    assert accepted_at[2] - accepted_at[1] >= 0.035
