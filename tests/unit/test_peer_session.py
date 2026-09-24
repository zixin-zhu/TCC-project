"""协议会话的握手、去重、序号和同步门禁测试。"""

from app.core.enums import ConnectionState
from app.core.exceptions import ProtocolError
from app.network.protocol import (
    MessageType,
    PeerProtocolSession,
    ProtocolMessage,
    SessionAction,
)


def _incoming(
    message_type: MessageType,
    *,
    sequence: int,
    message_id: str | None = None,
    state_version: int = 0,
    payload: object | None = None,
) -> ProtocolMessage:
    return ProtocolMessage(
        magic="TCCSIM",
        version=1,
        message_type=message_type,
        message_id=message_id or f"peer-{sequence}",
        sequence=sequence,
        station_id="B",
        peer_station_id="A",
        timestamp_ms=1000 + sequence,
        state_version=state_version,
        payload={} if payload is None else payload,
    )


def _handshaken_session() -> PeerProtocolSession:
    session = PeerProtocolSession(local_station_id="A", peer_station_id="B")
    session.on_transport_connected(now_ms=900)
    assert session.accept(_incoming(MessageType.HELLO, sequence=1)).action is SessionAction.SEND_ACK
    assert session.accept(_incoming(MessageType.ACK, sequence=2)).accepted
    assert session.connection_state is ConnectionState.HEALTHY
    return session


def test_transport_connection_enters_handshaking_not_healthy() -> None:
    session = PeerProtocolSession(local_station_id="A", peer_station_id="B")

    hello = session.on_transport_connected(now_ms=1234)

    assert session.connection_state is ConnectionState.HANDSHAKING
    assert hello.message_type is MessageType.HELLO
    assert hello.sequence == 1


def test_business_message_is_rejected_before_handshake() -> None:
    session = PeerProtocolSession(local_station_id="A", peer_station_id="B")
    session.on_transport_connected(now_ms=900)

    result = session.accept(_incoming(MessageType.TRACK_BOUNDARY, sequence=1))

    assert not result.accepted
    assert "握手" in result.reason


def test_both_hello_and_ack_are_required_before_healthy() -> None:
    session = PeerProtocolSession(local_station_id="A", peer_station_id="B")
    session.on_transport_connected(now_ms=900)

    hello_result = session.accept(_incoming(MessageType.HELLO, sequence=1))
    assert hello_result.accepted
    assert hello_result.action is SessionAction.SEND_ACK
    assert session.connection_state is ConnectionState.HANDSHAKING

    ack_result = session.accept(_incoming(MessageType.ACK, sequence=2))
    assert ack_result.accepted
    assert session.connection_state is ConnectionState.HEALTHY
    assert session.requires_full_sync


def test_duplicate_message_id_and_non_increasing_sequence_are_rejected() -> None:
    session = _handshaken_session()
    assert session.accept(_incoming(MessageType.STATE_SYNC, sequence=3)).accepted
    assert session.accept(_incoming(MessageType.HEARTBEAT, sequence=4, message_id="same")).accepted

    duplicate = session.accept(
        _incoming(MessageType.HEARTBEAT, sequence=5, message_id="same")
    )
    stale_sequence = session.accept(_incoming(MessageType.HEARTBEAT, sequence=4))

    assert not duplicate.accepted
    assert "重复" in duplicate.reason
    assert not stale_sequence.accepted
    assert "序号" in stale_sequence.reason


def test_incremental_message_waits_for_full_sync_after_handshake() -> None:
    session = _handshaken_session()

    blocked = session.accept(_incoming(MessageType.TRACK_BOUNDARY, sequence=3))
    baseline = session.accept(
        _incoming(MessageType.STATE_SYNC, sequence=4, state_version=9)
    )
    incremental = session.accept(
        _incoming(MessageType.TRACK_BOUNDARY, sequence=5, state_version=10)
    )

    assert not blocked.accepted
    assert "全量同步" in blocked.reason
    assert baseline.accepted
    assert not session.requires_full_sync
    assert incremental.accepted


def test_semantically_invalid_sync_does_not_open_baseline_gate() -> None:
    session = _handshaken_session()

    def reject(_message: ProtocolMessage) -> None:
        raise ProtocolError("同步载荷非法")

    result = session.accept(
        _incoming(MessageType.STATE_SYNC, sequence=3),
        received_at_ms=2000,
        semantic_validator=reject,
    )

    assert not result.accepted
    assert "同步载荷非法" in result.reason
    assert session.requires_full_sync


def test_rejected_prebaseline_traffic_does_not_refresh_liveness() -> None:
    session = _handshaken_session()

    rejected = session.accept(
        _incoming(MessageType.TRACK_BOUNDARY, sequence=3),
        received_at_ms=4000,
    )

    assert not rejected.accepted
    # 最后有效消息仍是 timestamp=1002 的 ACK，而不是 4000 的拒绝消息。
    assert session.evaluate_liveness(
        now_ms=4502,
        degraded_after_ms=3500,
        disconnect_after_ms=6000,
    ) is ConnectionState.DEGRADED


def test_heartbeat_timeout_moves_from_healthy_to_degraded_then_disconnected() -> None:
    session = _handshaken_session()
    assert session.accept(_incoming(MessageType.STATE_SYNC, sequence=3)).accepted

    assert session.evaluate_liveness(now_ms=4503, degraded_after_ms=3500, disconnect_after_ms=6000) is ConnectionState.DEGRADED
    assert session.evaluate_liveness(now_ms=7003, degraded_after_ms=3500, disconnect_after_ms=6000) is ConnectionState.DISCONNECTED


def test_reconnect_resets_peer_sequence_ids_and_sync_baseline() -> None:
    session = _handshaken_session()
    assert session.accept(_incoming(MessageType.STATE_SYNC, sequence=3)).accepted
    session.on_transport_disconnected()

    session.on_transport_connected(now_ms=2000)

    assert session.connection_state is ConnectionState.HANDSHAKING
    assert session.requires_full_sync
    assert session.accept(_incoming(MessageType.HELLO, sequence=1)).accepted
