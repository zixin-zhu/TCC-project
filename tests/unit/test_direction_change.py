"""区间改方四阶段事务的守卫、幂等与失败恢复测试。"""

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

import pytest
from hypothesis import given, settings, strategies as st

from app.core.enums import ConnectionState, DirectionPhase, RunningDirection, TrackState
from app.domain.direction_change import (
    DirectionActionType,
    DirectionChangeMachine,
    DirectionGuard,
    DirectionMessageKind,
    DirectionRejectCode,
)


def _safe_guard(*, local_version: int = 10, peer_version: int = 20) -> DirectionGuard:
    return DirectionGuard(
        connection_state=ConnectionState.HEALTHY,
        peer_snapshot_fresh=True,
        required_section_ids=frozenset({"Q1", "Q2"}),
        section_states={"Q1": TrackState.CLEAR, "Q2": TrackState.CLEAR},
        active_route_ids=frozenset(),
        local_state_version=local_version,
        peer_state_version=peer_version,
    )


def _sent_message(outcome):  # type: ignore[no-untyped-def]
    return next(
        action.message
        for action in outcome.actions
        if action.action_type is DirectionActionType.SEND
    )


def _tx(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"tcc-test/{label}"))


@pytest.mark.parametrize(
    ("guard", "code"),
    [
        (replace(_safe_guard(), connection_state=ConnectionState.DEGRADED), DirectionRejectCode.COMMUNICATION_UNHEALTHY),
        (replace(_safe_guard(), peer_snapshot_fresh=False), DirectionRejectCode.PEER_SNAPSHOT_STALE),
        (replace(_safe_guard(), section_states={"Q1": TrackState.OCCUPIED}), DirectionRejectCode.SECTION_UNSAFE),
        (replace(_safe_guard(), section_states={"Q1": TrackState.FAULT_OCCUPIED}), DirectionRejectCode.SECTION_UNSAFE),
        (replace(_safe_guard(), section_states={"Q1": TrackState.SHUNT_BAD}), DirectionRejectCode.SECTION_UNSAFE),
        (replace(_safe_guard(), section_states={"Q1": TrackState.CLEAR}), DirectionRejectCode.SECTION_UNSAFE),
        (replace(_safe_guard(), active_route_ids=frozenset({"A_DEPART"})), DirectionRejectCode.ROUTE_CONFLICT),
    ],
)
def test_request_rejects_every_unsafe_guard_without_direction_change(
    guard: DirectionGuard, code: DirectionRejectCode
) -> None:
    machine = DirectionChangeMachine(
        station_id="A", peer_station_id="B", current_direction=RunningDirection.A_TO_B
    )

    outcome = machine.start_request(
        RunningDirection.B_TO_A,
        guard,
        now_ms=1000,
        transaction_id=_tx("unsafe"),
    )

    assert not outcome.accepted
    assert outcome.reject_code is code
    assert machine.current_direction is RunningDirection.A_TO_B
    assert not any(action.action_type is DirectionActionType.APPLY for action in outcome.actions)


@given(
    st.sampled_from(
        [TrackState.OCCUPIED, TrackState.FAULT_OCCUPIED, TrackState.SHUNT_BAD]
    )
)
@settings(max_examples=30)
def test_any_non_clear_section_never_produces_apply(state: TrackState) -> None:
    """强不变量：任一非空闲区段都不得产生方向应用 Action。"""
    machine = DirectionChangeMachine(
        station_id="A", peer_station_id="B", current_direction=RunningDirection.A_TO_B
    )
    guard = replace(_safe_guard(), section_states={"Q1": TrackState.CLEAR, "Q2": state})

    outcome = machine.start_request(
        RunningDirection.B_TO_A, guard, now_ms=1000, transaction_id=_tx("property")
    )

    assert not any(action.action_type is DirectionActionType.APPLY for action in outcome.actions)
    assert machine.current_direction is RunningDirection.A_TO_B


def test_approve_only_reserves_and_never_changes_responder_direction() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A,
            _safe_guard(),
            now_ms=1000,
            transaction_id=_tx("approve"),
        )
    )

    approved = responder.handle(
        prepare,
        _safe_guard(local_version=20, peer_version=10),
        now_ms=1100,
    )

    assert approved.accepted
    assert _sent_message(approved).kind is DirectionMessageKind.APPROVE
    assert responder.current_direction is RunningDirection.A_TO_B
    assert not any(action.action_type is DirectionActionType.APPLY for action in approved.actions)


def test_commit_rechecks_guard_and_rejects_new_occupancy_without_switching() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("recheck")
        )
    )
    approve = _sent_message(
        responder.handle(prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100)
    )
    commit = _sent_message(requester.handle(approve, _safe_guard(), now_ms=1200))

    rejected = responder.handle(
        commit,
        replace(
            _safe_guard(local_version=20, peer_version=10),
            section_states={"Q1": TrackState.OCCUPIED},
        ),
        now_ms=1300,
    )

    assert not rejected.accepted
    assert rejected.reject_code is DirectionRejectCode.SECTION_UNSAFE
    assert _sent_message(rejected).kind is DirectionMessageKind.REJECT
    assert responder.current_direction is RunningDirection.A_TO_B
    assert not responder.has_active_transaction


def test_duplicate_prepare_is_idempotent_and_returns_same_approval() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("dup")
        )
    )

    first = responder.handle(prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100)
    duplicate = responder.handle(prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1150)

    assert _sent_message(duplicate) == _sent_message(first)
    assert not any(
        action.action_type
        in {DirectionActionType.APPLY, DirectionActionType.LOCK, DirectionActionType.UNLOCK}
        for action in duplicate.actions
    )
    assert responder.current_direction is RunningDirection.A_TO_B


def test_wrong_transaction_and_old_version_are_rejected_deterministically() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("version")
        )
    )
    wrong_uuid = replace(prepare, transaction_id=_tx("other"))
    old_version = replace(prepare, requester_state_version=9)

    responder.handle(prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1050)
    wrong = responder.handle(wrong_uuid, _safe_guard(local_version=20, peer_version=10), now_ms=1100)
    stale_responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    stale = stale_responder.handle(old_version, _safe_guard(local_version=20, peer_version=10), now_ms=1100)

    assert not wrong.accepted
    assert wrong.reject_code is DirectionRejectCode.WRONG_TRANSACTION
    assert not stale.accepted
    assert stale.reject_code is DirectionRejectCode.VERSION_MISMATCH


def test_wait_timeout_and_disconnect_release_transaction_and_keep_original() -> None:
    for failure in ("timeout", "disconnect"):
        machine = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B, timeout_ms=500)
        machine.start_request(
            RunningDirection.B_TO_A,
            _safe_guard(),
            now_ms=1000,
            transaction_id=_tx(failure),
        )

        outcome = machine.expire(now_ms=1500) if failure == "timeout" else machine.disconnect()

        assert not outcome.accepted
        assert outcome.reject_code in {
            DirectionRejectCode.TIMEOUT,
            DirectionRejectCode.DISCONNECTED,
        }
        assert machine.current_direction is RunningDirection.A_TO_B
        assert not machine.has_active_transaction
        assert machine.operation_locked is True


def test_commit_ack_timeout_keeps_authority_truth_locked_and_projection_original() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B, timeout_ms=500)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B, timeout_ms=500)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("commit-timeout")
        )
    )
    approve = _sent_message(
        responder.handle(prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100)
    )
    requester.handle(approve, _safe_guard(), now_ms=1200)

    timed_out = requester.expire(now_ms=1700)
    responder_disconnected = responder.disconnect()

    assert timed_out.reject_code is DirectionRejectCode.TIMEOUT
    assert responder_disconnected.reject_code is DirectionRejectCode.DISCONNECTED
    assert requester.current_direction is RunningDirection.B_TO_A
    assert responder.current_direction is RunningDirection.A_TO_B
    assert not requester.has_active_transaction
    assert not responder.has_active_transaction
    assert requester.operation_locked is True
    assert responder.operation_locked is True


def test_late_approve_is_rejected_by_local_transaction_deadline() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B, timeout_ms=500)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B, timeout_ms=5000)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("late")
        )
    )
    approve = _sent_message(
        responder.handle(prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100)
    )

    late = requester.handle(approve, _safe_guard(), now_ms=1500)

    assert not late.accepted
    assert late.reject_code is DirectionRejectCode.TIMEOUT
    assert requester.current_direction is RunningDirection.A_TO_B
    assert not requester.has_active_transaction


def test_concurrent_opposite_request_is_rejected_while_reservation_exists() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("first")
        )
    )
    responder.handle(prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100)

    concurrent = responder.start_request(
        RunningDirection.B_TO_A,
        _safe_guard(local_version=20, peer_version=10),
        now_ms=1200,
        transaction_id=_tx("second"),
    )

    assert not concurrent.accepted
    assert concurrent.reject_code is DirectionRejectCode.NOT_AUTHORITY


def test_only_authority_station_can_start_direction_change() -> None:
    """B 站只保存权威投影，不能形成第二个独立方向真值。"""
    projection = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)

    outcome = projection.start_request(
        RunningDirection.B_TO_A,
        _safe_guard(local_version=20, peer_version=10),
        now_ms=1000,
        transaction_id=_tx("not-authority"),
    )

    assert not outcome.accepted
    assert outcome.reject_code is DirectionRejectCode.NOT_AUTHORITY
    assert projection.current_direction is RunningDirection.A_TO_B
    assert projection.operation_locked is False


def test_ack_delivery_failure_keeps_authority_projection_and_locks_operation() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("ack-loss")
        )
    )
    approve = _sent_message(
        responder.handle(prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100)
    )
    commit = _sent_message(requester.handle(approve, _safe_guard(), now_ms=1200))
    pending_ack = responder.handle(
        commit, _safe_guard(local_version=20, peer_version=10), now_ms=1300
    )
    assert any(action.action_type is DirectionActionType.APPLY for action in pending_ack.actions)
    assert responder.has_active_transaction

    locked = responder.disconnect()

    assert responder.current_direction is RunningDirection.B_TO_A
    assert responder.operation_locked is True
    assert locked.phase is DirectionPhase.FAULT_LOCKED
    assert not any(action.action_type is DirectionActionType.UNLOCK for action in locked.actions)


def test_projection_confirmation_does_not_unlock_authority_before_ack() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("peer-proof")
        )
    )
    approve = _sent_message(
        responder.handle(prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100)
    )
    commit = _sent_message(requester.handle(approve, _safe_guard(), now_ms=1200))
    ack = _sent_message(
        responder.handle(commit, _safe_guard(local_version=20, peer_version=10), now_ms=1300)
    )

    projection_confirmed = responder.confirm_peer_applied(
        requester.export_recovery_record(),
        _safe_guard(local_version=20, peer_version=10),
    )
    assert projection_confirmed.accepted
    assert not responder.has_active_transaction
    assert responder.operation_locked is False
    assert requester.operation_locked is True

    requester.handle(ack, _safe_guard(), now_ms=1400)
    assert requester.operation_locked is False


def test_lost_application_confirmation_keeps_projection_locked_until_safe_recovery() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("recover-confirm")
        )
    )
    approve = _sent_message(
        responder.handle(prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100)
    )
    commit = _sent_message(requester.handle(approve, _safe_guard(), now_ms=1200))
    ack = _sent_message(
        responder.handle(commit, _safe_guard(local_version=20, peer_version=10), now_ms=1300)
    )
    requester.handle(ack, _safe_guard(), now_ms=1400)
    evidence = requester.export_recovery_record()

    disconnected = responder.disconnect()
    assert responder.current_direction is RunningDirection.B_TO_A
    assert responder.operation_locked is True
    assert disconnected.phase is DirectionPhase.FAULT_LOCKED

    unsafe = responder.confirm_peer_applied(
        evidence,
        replace(
            _safe_guard(local_version=20, peer_version=10),
            section_states={"Q1": TrackState.OCCUPIED},
        ),
    )
    recovered = responder.confirm_peer_applied(
        evidence, _safe_guard(local_version=20, peer_version=10)
    )

    assert not unsafe.accepted
    assert responder.operation_locked is False
    assert recovered.accepted
    assert responder.current_direction is RunningDirection.B_TO_A
    assert any(
        action.action_type is DirectionActionType.UNLOCK
        for action in recovered.actions
    )


def test_authority_applies_before_commit_and_failure_never_rolls_back_truth() -> None:
    """A 一旦发布权威方向，后续网络失败只能锁闭，不能回滚成第二种真值。"""
    authority = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    projection = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        authority.start_request(
            RunningDirection.B_TO_A,
            _safe_guard(),
            now_ms=1000,
            transaction_id=_tx("authority-commit"),
        )
    )
    approve = _sent_message(
        projection.handle(
            prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100
        )
    )

    committing = authority.handle(approve, _safe_guard(), now_ms=1200)
    failed = authority.disconnect()

    assert committing.phase is DirectionPhase.COMMITTING
    assert authority.current_direction is RunningDirection.B_TO_A
    assert authority.operation_locked is True
    assert failed.phase is DirectionPhase.FAULT_LOCKED
    assert authority.current_direction is RunningDirection.B_TO_A


def test_fault_locked_machine_rejects_new_transaction_until_safe_resync() -> None:
    authority = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    disconnected = authority.disconnect()

    blocked = authority.start_request(
        RunningDirection.B_TO_A,
        _safe_guard(),
        now_ms=1000,
        transaction_id=_tx("blocked-by-lock"),
    )
    unsafe_recovery = authority.restore_from_authority(
        RunningDirection.A_TO_B,
        replace(_safe_guard(), peer_snapshot_fresh=False),
    )
    recovered = authority.restore_from_authority(
        RunningDirection.A_TO_B, _safe_guard()
    )

    assert disconnected.phase is DirectionPhase.FAULT_LOCKED
    assert blocked.reject_code is DirectionRejectCode.RECOVERY_PENDING
    assert not unsafe_recovery.accepted
    assert recovered.accepted
    assert authority.operation_locked is False


def test_projection_resyncs_only_from_authority_and_then_unlocks() -> None:
    projection = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    projection.disconnect()

    recovered = projection.restore_from_authority(
        RunningDirection.B_TO_A,
        _safe_guard(local_version=20, peer_version=10),
    )

    assert recovered.accepted
    assert projection.current_direction is RunningDirection.B_TO_A
    assert projection.operation_locked is False
    assert any(
        action.action_type is DirectionActionType.APPLY for action in recovered.actions
    )


def test_projection_rejects_prepare_not_owned_by_authority() -> None:
    projection = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    authority = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    prepare = replace(
        _sent_message(
            authority.start_request(
                RunningDirection.B_TO_A,
                _safe_guard(),
                now_ms=1000,
                transaction_id=_tx("forged-authority"),
            )
        ),
        requester_station_id="C",
    )

    outcome = projection.handle(
        prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100
    )

    assert not outcome.accepted
    assert outcome.reject_code is DirectionRejectCode.NOT_AUTHORITY


def test_same_kind_and_uuid_with_changed_content_is_not_treated_as_duplicate() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    responder = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("fingerprint")
        )
    )
    first = responder.handle(
        prepare, _safe_guard(local_version=20, peer_version=10), now_ms=1100
    )
    tampered = replace(prepare, requester_state_version=9)

    second = responder.handle(
        tampered, _safe_guard(local_version=20, peer_version=10), now_ms=1150
    )

    assert first.accepted
    assert not second.accepted
    assert second.reject_code in {
        DirectionRejectCode.WRONG_TRANSACTION,
        DirectionRejectCode.VERSION_MISMATCH,
        DirectionRejectCode.OUT_OF_ORDER,
    }


def test_unmatched_reject_never_generates_another_reject() -> None:
    requester = DirectionChangeMachine("A", "B", RunningDirection.A_TO_B)
    receiver = DirectionChangeMachine("B", "A", RunningDirection.A_TO_B)
    prepare = _sent_message(
        requester.start_request(
            RunningDirection.B_TO_A, _safe_guard(), now_ms=1000, transaction_id=_tx("reject-loop")
        )
    )
    rejection = replace(
        prepare,
        kind=DirectionMessageKind.REJECT,
        reject_code=DirectionRejectCode.SECTION_UNSAFE,
        reason="区间占用",
    )

    outcome = receiver.handle(
        rejection, _safe_guard(local_version=20, peer_version=10), now_ms=1100
    )

    assert not outcome.accepted
    assert not any(action.action_type is DirectionActionType.SEND for action in outcome.actions)
