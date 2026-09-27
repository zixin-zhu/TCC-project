"""阶段 1：双站一致性检查，不把 A 站写死为永久权威。"""

from app.core.enums import (
    ConnectionState,
    DirectionPhase,
    RunningDirection,
    TrackState,
)
from app.core.models import LocalAuthorityState, OperationResult, PeerSnapshot
from app.domain.interstation_agreement import (
    InterstationAgreement,
    can_change_direction,
)


def _authority(station_id: str, version: int = 4) -> LocalAuthorityState:
    return LocalAuthorityState(
        station_id=station_id,
        tracks={"Q1": TrackState.CLEAR, "Q2": TrackState.CLEAR},
        signals={},
        active_route_ids=(),
        telegram_version=1,
        state_version=version,
    )


def _peer(station_id: str = "A", version: int = 8, **kwargs: object) -> PeerSnapshot:
    values: dict[str, object] = {
        "boundary_states": {"Q1": TrackState.CLEAR, "Q2": TrackState.CLEAR},
        "received_at_ms": 1000,
    }
    values.update(kwargs)
    return PeerSnapshot(
        station_id=station_id,
        boundary_states=values.pop("boundary_states"),  # type: ignore[arg-type]
        state_version=version,
        received_at_ms=values.pop("received_at_ms"),  # type: ignore[arg-type]
        **values,
    )


def _agreement(local: int = 4, peer: int = 8, **kwargs: object) -> InterstationAgreement:
    return InterstationAgreement(
        direction=RunningDirection.B_TO_A,
        requester_station="B",
        responder_station="A",
        phase=DirectionPhase.PREPARING,
        transaction_id="tx-1",
        local_version=local,
        peer_version=peer,
        expires_at_ms=9000,
        **kwargs,
    )


def test_b_station_can_be_requester_when_both_local_authorities_are_safe() -> None:
    result = can_change_direction(
        _authority("B"),
        _peer(),
        _agreement(),
        now_ms=2000,
    )

    assert isinstance(result, OperationResult)
    assert result.success is True


def test_direction_change_rejects_peer_occupancy_and_version_mismatch() -> None:
    occupied = can_change_direction(
        _authority("B"),
        _peer(boundary_states={"Q1": TrackState.FAULT_OCCUPIED, "Q2": TrackState.CLEAR}),
        _agreement(),
        now_ms=2000,
    )
    mismatch = can_change_direction(
        _authority("B"),
        _peer(),
        _agreement(peer=99),
        now_ms=2000,
    )

    assert occupied.success is False
    assert "占用" in occupied.reason
    assert mismatch.success is False
    assert "版本" in mismatch.reason


def test_direction_change_rejects_active_route_and_stale_peer_snapshot() -> None:
    active_route = can_change_direction(
        LocalAuthorityState(
            station_id="B",
            tracks={"Q1": TrackState.CLEAR},
            signals={},
            active_route_ids=("B_DEPART",),
            telegram_version=1,
            state_version=4,
        ),
        _peer(),
        _agreement(),
        now_ms=2000,
    )
    stale = can_change_direction(
        _authority("B"),
        _peer(received_at_ms=-10000),
        _agreement(),
        now_ms=2000,
    )

    assert active_route.success is False
    assert "进路" in active_route.reason
    assert stale.success is False
    assert "快照" in stale.reason
