"""通过内存 transport 编排两个独立改方状态机。"""

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.core.enums import ConnectionState, RunningDirection, TrackState
from app.core.exceptions import ProtocolError
from app.domain.direction_change import (
    DirectionActionType,
    DirectionChangeMachine,
    DirectionGuard,
    DirectionMessageKind,
)
from app.network.protocol import PeerProtocolSession, ProtocolCodec
from app.services.direction_change_protocol import DirectionProtocolAdapter


def _guard(local: int, peer: int) -> DirectionGuard:
    return DirectionGuard(
        connection_state=ConnectionState.HEALTHY,
        peer_snapshot_fresh=True,
        required_section_ids=frozenset({"Q1", "Q2"}),
        section_states={"Q1": TrackState.CLEAR, "Q2": TrackState.CLEAR},
        active_route_ids=frozenset(),
        local_state_version=local,
        peer_state_version=peer,
    )


def _send(outcome):  # type: ignore[no-untyped-def]
    return next(action.message for action in outcome.actions if action.action_type is DirectionActionType.SEND)


def _tx(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"tcc-integration/{label}"))


def _run_success(
    original: RunningDirection, target: RunningDirection
) -> tuple[DirectionChangeMachine, DirectionChangeMachine]:
    a = DirectionChangeMachine("A", "B", original)
    b = DirectionChangeMachine("B", "A", original)
    prepare = _send(a.start_request(target, _guard(10, 20), now_ms=1000, transaction_id=_tx(f"ok-{original.value}")))
    approve = _send(b.handle(prepare, _guard(20, 10), now_ms=1100))
    assert approve.kind is DirectionMessageKind.APPROVE
    assert a.current_direction is original
    assert b.current_direction is original
    authority_commit = a.handle(approve, _guard(10, 20), now_ms=1200)
    commit = _send(authority_commit)
    assert any(
        action.action_type is DirectionActionType.APPLY
        for action in authority_commit.actions
    )
    ack_outcome = b.handle(commit, _guard(20, 10), now_ms=1300)
    ack = _send(ack_outcome)
    assert ack.kind is DirectionMessageKind.ACK
    assert any(action.action_type is DirectionActionType.APPLY for action in ack_outcome.actions)
    completed = a.handle(ack, _guard(10, 20), now_ms=1400)
    assert any(action.action_type is DirectionActionType.UNLOCK for action in completed.actions)
    evidence = DirectionProtocolAdapter.to_recovery_protocol_message(
        a.export_recovery_record(),
        session=PeerProtocolSession(local_station_id="A", peer_station_id="B"),
        now_ms=1450,
    )
    evidence_codec = ProtocolCodec(local_station_id="A", peer_station_id="B")
    recovered = DirectionProtocolAdapter.from_recovery_protocol_message(
        evidence_codec.decode(evidence_codec.encode(evidence))
    )
    responder_completed = b.confirm_peer_applied(recovered, _guard(20, 10))
    assert responder_completed.accepted
    return a, b


def test_successful_change_works_in_both_directions() -> None:
    for original, target in (
        (RunningDirection.A_TO_B, RunningDirection.B_TO_A),
        (RunningDirection.B_TO_A, RunningDirection.A_TO_B),
    ):
        a, b = _run_success(original, target)
        assert a.current_direction is target
        assert b.current_direction is target
        assert not a.has_active_transaction
        assert not b.has_active_transaction


def test_duplicate_commit_and_ack_are_idempotent() -> None:
    a = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    b = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _send(a.start_request(RunningDirection.B_TO_A, _guard(10, 20), now_ms=1000, transaction_id=_tx("idem")))
    approve = _send(b.handle(prepare, _guard(20, 10), now_ms=1100))
    commit = _send(a.handle(approve, _guard(10, 20), now_ms=1200))
    first_ack_outcome = b.handle(commit, _guard(20, 10), now_ms=1300)
    duplicate_ack_outcome = b.handle(commit, _guard(20, 10), now_ms=1350)
    assert _send(duplicate_ack_outcome) == _send(first_ack_outcome)
    assert not any(
        action.action_type in {DirectionActionType.APPLY, DirectionActionType.LOCK}
        for action in duplicate_ack_outcome.actions
    )
    ack = _send(first_ack_outcome)
    first_complete = a.handle(ack, _guard(10, 20), now_ms=1400)
    duplicate_complete = a.handle(ack, _guard(10, 20), now_ms=1450)
    b.confirm_peer_applied(a.export_recovery_record(), _guard(20, 10))
    assert duplicate_complete.phase == first_complete.phase
    assert duplicate_complete.actions == ()
    assert a.current_direction is RunningDirection.B_TO_A
    assert b.current_direction is RunningDirection.B_TO_A


def test_direction_messages_roundtrip_through_stage4_json_crc_protocol() -> None:
    a = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    prepare = _send(
        a.start_request(
            RunningDirection.B_TO_A,
            _guard(10, 20),
            now_ms=1000,
            transaction_id=_tx("protocol"),
        )
    )
    session = PeerProtocolSession(local_station_id="A", peer_station_id="B")
    protocol_message = DirectionProtocolAdapter.to_protocol_message(
        prepare, session=session, now_ms=1000
    )
    encoded = ProtocolCodec(local_station_id="A", peer_station_id="B").encode(
        protocol_message
    )
    decoded = ProtocolCodec(local_station_id="A", peer_station_id="B").decode(encoded)

    assert DirectionProtocolAdapter.from_protocol_message(decoded) == prepare


def test_protocol_adapter_rejects_invalid_uuid_and_wrong_stage_sender() -> None:
    a = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    prepare = _send(
        a.start_request(
            RunningDirection.B_TO_A,
            _guard(10, 20),
            now_ms=1000,
            transaction_id=_tx("role"),
        )
    )
    wrong_role = replace(
        prepare, source_station_id="B", target_station_id="A"
    )
    with pytest.raises(ProtocolError, match="发送角色"):
        DirectionProtocolAdapter.to_protocol_message(
            wrong_role,
            session=PeerProtocolSession(local_station_id="B", peer_station_id="A"),
            now_ms=1000,
        )

    invalid_uuid = replace(prepare, transaction_id="not-a-uuid")
    with pytest.raises(ProtocolError, match="UUID"):
        DirectionProtocolAdapter.to_protocol_message(
            invalid_uuid,
            session=PeerProtocolSession(local_station_id="A", peer_station_id="B"),
            now_ms=1000,
        )


def test_all_direction_message_kinds_roundtrip_with_strict_roles() -> None:
    a = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    b = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _send(
        a.start_request(
            RunningDirection.B_TO_A, _guard(10, 20), now_ms=1000, transaction_id=_tx("all-kinds")
        )
    )
    approve = _send(b.handle(prepare, _guard(20, 10), now_ms=1100))
    commit = _send(a.handle(approve, _guard(10, 20), now_ms=1200))
    ack = _send(b.handle(commit, _guard(20, 10), now_ms=1300))
    rejecting = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    reject = _send(
        rejecting.handle(
            prepare,
            DirectionGuard(
                connection_state=ConnectionState.HEALTHY,
                peer_snapshot_fresh=True,
                required_section_ids=frozenset({"Q1", "Q2"}),
                section_states={"Q1": TrackState.OCCUPIED, "Q2": TrackState.CLEAR},
                active_route_ids=frozenset(),
                local_state_version=20,
                peer_state_version=10,
            ),
            now_ms=1100,
        )
    )

    for index, direction_message in enumerate((prepare, approve, commit, ack, reject)):
        session = PeerProtocolSession(
            local_station_id=direction_message.source_station_id,
            peer_station_id=direction_message.target_station_id,
        )
        protocol_message = DirectionProtocolAdapter.to_protocol_message(
            direction_message, session=session, now_ms=2000 + index
        )
        codec = ProtocolCodec(
            local_station_id=direction_message.source_station_id,
            peer_station_id=direction_message.target_station_id,
        )
        decoded = codec.decode(codec.encode(protocol_message))
        assert DirectionProtocolAdapter.from_protocol_message(decoded) == direction_message


def test_projection_cannot_create_competing_request_or_reject_ping_pong() -> None:
    a = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    b = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare_a = _send(
        a.start_request(
            RunningDirection.B_TO_A, _guard(10, 20), now_ms=1000, transaction_id=_tx("sim-a")
        )
    )
    request_b = b.start_request(
        RunningDirection.B_TO_A,
        _guard(20, 10),
        now_ms=1000,
        transaction_id=_tx("sim-b"),
    )
    assert not request_b.accepted
    assert not any(
        action.action_type is DirectionActionType.SEND for action in request_b.actions
    )
    approve = _send(b.handle(prepare_a, _guard(20, 10), now_ms=1100))
    at_a = a.handle(approve, _guard(10, 20), now_ms=1200)

    assert _send(at_a).kind is DirectionMessageKind.COMMIT
    assert a.current_direction is RunningDirection.B_TO_A
    assert b.current_direction is RunningDirection.A_TO_B
