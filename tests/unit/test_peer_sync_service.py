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


def test_full_sync_preserves_peer_route_and_lock_metadata() -> None:
    service = PeerSyncService(peer_station_id="B", allowed_boundary_ids={"AB"})

    snapshot = service.apply_full_sync(
        {
            "boundary_states": {"AB": "CLEAR"},
            "state_version": 7,
            "active_route_ids": ["B_DEPART"],
            "direction_operation_locked": True,
        },
        received_at_ms=1234,
    )

    assert snapshot.active_route_ids == ("B_DEPART",)
    assert snapshot.direction_operation_locked is True


def test_heartbeat_refreshes_snapshot_liveness_without_changing_version() -> None:
    """心跳只能刷新活性时间，不能伪造状态版本或轨道状态变化。"""
    service = PeerSyncService(peer_station_id="B", allowed_boundary_ids={"AB"})
    original = service.apply_full_sync(
        {
            "boundary_states": {"AB": "CLEAR"},
            "state_version": 7,
        },
        received_at_ms=100,
    )

    refreshed = service.refresh_liveness(received_at_ms=250)

    assert refreshed is not original
    assert refreshed.station_id == original.station_id
    assert refreshed.boundary_states == original.boundary_states
    assert refreshed.state_version == original.state_version
    assert refreshed.received_at_ms == 250


def test_heartbeat_cannot_create_snapshot_without_full_sync() -> None:
    """没有全量基线时，心跳不能把连接伪装成已有状态快照。"""
    service = PeerSyncService(peer_station_id="B", allowed_boundary_ids={"AB"})

    try:
        service.refresh_liveness(received_at_ms=250)
    except ProtocolError as exc:
        assert "全量" in str(exc)
    else:
        raise AssertionError("没有全量基线时心跳不应创建快照")


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
