"""站间全量与增量状态同步的领域边界测试。"""

from app.core.enums import TrackState
from app.core.exceptions import ProtocolError
from app.network.protocol import MessageType, ProtocolMessage
from app.services.peer_sync_service import PeerSyncService


def test_full_sync_creates_peer_snapshot_with_receive_time() -> None:
    service = PeerSyncService(peer_station_id="B", allowed_boundary_ids={"AB"})

    snapshot = service.apply_full_sync(
        {
            "boundary_states": {"AB": "OCCUPIED"},
            "state_version": 7,
        },
        received_at_ms=1234,
    )

    assert snapshot.station_id == "B"
    assert snapshot.boundary_states == {"AB": TrackState.OCCUPIED}
    assert snapshot.state_version == 7
    assert snapshot.received_at_ms == 1234


def test_incremental_update_requires_baseline_and_monotonic_version() -> None:
    service = PeerSyncService(peer_station_id="B", allowed_boundary_ids={"AB"})

    try:
        service.apply_boundary_update(
            {"boundary_id": "AB", "state": "CLEAR", "state_version": 1},
            received_at_ms=100,
        )
    except ProtocolError as exc:
        assert "全量" in str(exc)
    else:
        raise AssertionError("没有全量基线时不应接受增量")

    service.apply_full_sync(
        {"boundary_states": {"AB": "CLEAR"}, "state_version": 3},
        received_at_ms=100,
    )
    updated = service.apply_boundary_update(
        {"boundary_id": "AB", "state": "SHUNT_BAD", "state_version": 4},
        received_at_ms=200,
    )
    assert updated.boundary_states["AB"] is TrackState.SHUNT_BAD

    try:
        service.apply_boundary_update(
            {"boundary_id": "AB", "state": "CLEAR", "state_version": 4},
            received_at_ms=300,
        )
    except ProtocolError as exc:
        assert "版本" in str(exc)
    else:
        raise AssertionError("重复状态版本不应覆盖新状态")


def test_sync_rejects_unknown_boundary_or_track_state() -> None:
    service = PeerSyncService(peer_station_id="B", allowed_boundary_ids={"AB"})

    for payload in (
        {"boundary_states": {"OTHER": "CLEAR"}, "state_version": 1},
        {"boundary_states": {"AB": "INVALID"}, "state_version": 1},
    ):
        try:
            service.apply_full_sync(payload, received_at_ms=100)
        except ProtocolError:
            pass
        else:
            raise AssertionError(f"非法同步载荷未被拒绝：{payload}")


def test_protocol_message_version_must_match_payload_before_snapshot_changes() -> None:
    service = PeerSyncService(peer_station_id="B", allowed_boundary_ids={"AB"})
    message = ProtocolMessage(
        magic="TCCSIM",
        version=1,
        message_type=MessageType.STATE_SYNC,
        message_id="sync-bad",
        sequence=3,
        station_id="B",
        peer_station_id="A",
        timestamp_ms=100,
        state_version=8,
        payload={"boundary_states": {"AB": "CLEAR"}, "state_version": 7},
    )

    try:
        service.validate_and_apply(message, received_at_ms=100)
    except ProtocolError as exc:
        assert "版本" in str(exc)
    else:
        raise AssertionError("报文头与载荷版本不一致时必须拒绝")
    assert service.snapshot is None


def test_full_sync_cannot_roll_back_within_same_connection() -> None:
    service = PeerSyncService(peer_station_id="B", allowed_boundary_ids={"AB"})
    service.apply_full_sync(
        {"boundary_states": {"AB": "OCCUPIED"}, "state_version": 5},
        received_at_ms=100,
    )

    try:
        service.apply_full_sync(
            {"boundary_states": {"AB": "CLEAR"}, "state_version": 4},
            received_at_ms=200,
        )
    except ProtocolError as exc:
        assert "版本" in str(exc)
    else:
        raise AssertionError("同一连接中的全量同步不允许版本回退")
