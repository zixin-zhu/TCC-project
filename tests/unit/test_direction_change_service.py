"""改方 Action 到统一运行状态的应用服务测试。"""

from pathlib import Path
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.core.enums import ConnectionState, DirectionPhase, RunningDirection, SignalAspect, TrackState
from app.core.models import StationRuntimeState
from app.domain.direction_change import (
    DirectionAction,
    DirectionActionType,
    DirectionChangeMachine,
    DirectionOutcome,
)
from app.domain.route_control import RouteControlService
from app.domain.signal_control import SignalControlService
from app.infrastructure.config_loader import load_project_config
from app.services.direction_change_service import (
    DirectionChangeCoordinator,
    DirectionChangeService,
)


ROOT = Path(__file__).resolve().parents[2]


def _tx(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"tcc-coordinator/{label}"))


def _guard(
    coordinator: DirectionChangeCoordinator, peer_version: int
):
    return coordinator.build_guard(
        connection_state=ConnectionState.HEALTHY,
        peer_snapshot_fresh=True,
        required_section_ids=frozenset({"Q1", "Q2"}),
        section_states={"Q1": TrackState.CLEAR, "Q2": TrackState.CLEAR},
        peer_state_version=peer_version,
    )


def test_service_applies_direction_and_lock_actions_once() -> None:
    runtime = StationRuntimeState.create("A", ("Q1", "Q2"))
    service = DirectionChangeService(runtime)
    outcome = DirectionOutcome(
        accepted=True,
        phase=DirectionPhase.COMMITTING,
        reason="测试权威提交",
        reject_code=None,
        actions=(
            DirectionAction(DirectionActionType.LOCK, reason="事务进行中"),
            DirectionAction(
                DirectionActionType.APPLY,
                direction=RunningDirection.B_TO_A,
                reason="A 站权威提交",
            ),
        ),
    )

    first = service.apply(outcome)
    second = service.apply(outcome)

    assert runtime.running_direction is RunningDirection.B_TO_A
    assert runtime.direction_operation_locked is True
    # 锁闭是本地故障安全门禁，不参与事务快照版本；只有方向真值变化增版。
    assert runtime.state_version == 1
    assert first.state_changed is True
    assert second.state_changed is False


def test_service_unlocks_and_returns_protocol_messages_without_sending_them() -> None:
    runtime = StationRuntimeState.create("B", ("Q1", "Q2"))
    runtime.direction_operation_locked = True
    service = DirectionChangeService(runtime)
    outcome = DirectionOutcome(
        accepted=True,
        phase=DirectionPhase.COMPLETED,
        reason="投影确认",
        reject_code=None,
        actions=(
            DirectionAction(DirectionActionType.UNLOCK, reason="恢复完成"),
            DirectionAction(DirectionActionType.LOG, reason="可恢复行车作业"),
        ),
    )

    result = service.apply(outcome)

    assert runtime.direction_operation_locked is False
    assert runtime.state_version == 0
    assert result.messages == ()
    assert result.logs == ("可恢复行车作业",)


def test_coordinator_uses_real_runtime_versions_and_protects_before_send() -> None:
    runtime_a = StationRuntimeState.create("A", ("Q1", "Q2"))
    runtime_b = StationRuntimeState.create("B", ("Q1", "Q2"))
    sent_a = []
    sent_b = []

    def send_a(message):  # type: ignore[no-untyped-def]
        assert runtime_a.direction_operation_locked
        sent_a.append(message)

    def send_b(message):  # type: ignore[no-untyped-def]
        assert runtime_b.direction_operation_locked
        sent_b.append(message)

    coordinator_a = DirectionChangeCoordinator(
        DirectionChangeMachine("A", "B", RunningDirection.A_TO_B),
        runtime_a,
        send_message=send_a,
    )
    coordinator_b = DirectionChangeCoordinator(
        DirectionChangeMachine("B", "A", RunningDirection.A_TO_B),
        runtime_b,
        send_message=send_b,
    )

    coordinator_a.start_request(
        RunningDirection.B_TO_A,
        _guard(coordinator_a, runtime_b.state_version),
        now_ms=1000,
        transaction_id=_tx("real-runtime"),
    )
    coordinator_b.handle(
        sent_a.pop(),
        _guard(coordinator_b, runtime_a.state_version),
        now_ms=1100,
    )
    coordinator_a.handle(
        sent_b.pop(),
        _guard(coordinator_a, runtime_b.state_version),
        now_ms=1200,
    )
    # A 应用权威方向后版本增至 1，但 COMMIT 仍携带事务开始时的快照版本 0；
    # B 以事务快照复核，本地 LOCK 本身不应造成版本自失效。
    coordinator_b.handle(
        sent_a.pop(),
        _guard(coordinator_b, peer_version=0),
        now_ms=1300,
    )
    coordinator_a.handle(
        sent_b.pop(),
        _guard(coordinator_a, runtime_b.state_version),
        now_ms=1400,
    )
    coordinator_b.confirm_authority_applied(
        coordinator_a.machine.export_recovery_record(),
        _guard(coordinator_b, runtime_a.state_version),
    )

    assert runtime_a.running_direction is RunningDirection.B_TO_A
    assert runtime_b.running_direction is RunningDirection.B_TO_A
    assert runtime_a.state_version == 1
    assert runtime_b.state_version == 1
    assert runtime_a.direction_operation_locked is False
    assert runtime_b.direction_operation_locked is False


def test_precommit_disconnect_stays_locked_and_blocks_route_and_signals() -> None:
    config = load_project_config(ROOT / "configs", "A")
    runtime = StationRuntimeState.create(
        "A", (section.id for section in config.topology.sections)
    )
    sent = []
    coordinator = DirectionChangeCoordinator(
        DirectionChangeMachine("A", "B", RunningDirection.A_TO_B),
        runtime,
        send_message=sent.append,
    )
    coordinator.start_request(
        RunningDirection.B_TO_A,
        coordinator.build_guard(
            connection_state=ConnectionState.HEALTHY,
            peer_snapshot_fresh=True,
            required_section_ids=frozenset({"Q1", "Q2"}),
            section_states={"Q1": TrackState.CLEAR, "Q2": TrackState.CLEAR},
            peer_state_version=0,
        ),
        now_ms=1000,
        transaction_id=_tx("disconnect-before-commit"),
    )

    coordinator.on_connection_state(ConnectionState.DISCONNECTED)
    route = RouteControlService(config.topology).establish("A_DEPART", runtime)
    signals = SignalControlService(config.topology).recalculate(runtime, [])

    assert runtime.direction_operation_locked is True
    assert route.success is False
    assert all(item.aspect is SignalAspect.RED for item in signals)
    assert all("方向安全锁闭" in item.reason for item in signals)


def test_degraded_or_stale_guard_fails_closed_through_coordinator() -> None:
    for unsafe_guard in ("degraded", "stale"):
        runtime = StationRuntimeState.create("A", ("Q1", "Q2"))
        coordinator = DirectionChangeCoordinator(
            DirectionChangeMachine("A", "B", RunningDirection.A_TO_B), runtime
        )
        guard = _guard(coordinator, peer_version=0)
        guard = replace(
            guard,
            connection_state=(
                ConnectionState.DEGRADED
                if unsafe_guard == "degraded"
                else ConnectionState.HEALTHY
            ),
            peer_snapshot_fresh=unsafe_guard != "stale",
        )

        result = coordinator.start_request(
            RunningDirection.B_TO_A,
            guard,
            now_ms=1000,
            transaction_id=_tx(f"fail-closed-{unsafe_guard}"),
        )

        assert not result.outcome.accepted
        assert result.outcome.phase is DirectionPhase.FAULT_LOCKED
        assert runtime.direction_operation_locked is True


def test_send_failure_immediately_fault_locks_machine_and_runtime() -> None:
    runtime_a = StationRuntimeState.create("A", ("Q1", "Q2"))
    coordinator_a = DirectionChangeCoordinator(
        DirectionChangeMachine("A", "B", RunningDirection.A_TO_B), runtime_a
    )
    prepare = coordinator_a.start_request(
        RunningDirection.B_TO_A,
        _guard(coordinator_a, peer_version=0),
        now_ms=1000,
        transaction_id=_tx("send-failure"),
    ).execution.messages[0]

    runtime_b = StationRuntimeState.create("B", ("Q1", "Q2"))

    def fail_send(_message):  # type: ignore[no-untyped-def]
        raise OSError("模拟发送失败")

    coordinator_b = DirectionChangeCoordinator(
        DirectionChangeMachine("B", "A", RunningDirection.A_TO_B),
        runtime_b,
        send_message=fail_send,
    )
    unsafe = replace(
        _guard(coordinator_b, peer_version=0),
        section_states={"Q1": TrackState.OCCUPIED, "Q2": TrackState.CLEAR},
    )

    with pytest.raises(OSError, match="模拟发送失败"):
        coordinator_b.handle(prepare, unsafe, now_ms=1100)

    assert coordinator_b.machine.phase is DirectionPhase.FAULT_LOCKED
    assert coordinator_b.machine.operation_locked is True
    assert runtime_b.direction_operation_locked is True


def test_coordinator_rejects_initial_lock_state_drift() -> None:
    runtime = StationRuntimeState.create("A", ("Q1", "Q2"))
    runtime.direction_operation_locked = True

    with pytest.raises(ValueError, match="初始锁闭状态不一致"):
        DirectionChangeCoordinator(
            DirectionChangeMachine("A", "B", RunningDirection.A_TO_B), runtime
        )
