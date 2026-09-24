"""把纯领域改方 Action 安全地应用到统一车站运行状态。"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.core.enums import ConnectionState, RunningDirection, TrackState
from app.core.models import StationRuntimeState
from app.domain.direction_change import (
    DirectionChangeMachine,
    DirectionGuard,
    DirectionActionType,
    DirectionOutcome,
    DirectionRecoveryRecord,
    DirectionWireMessage,
)


@dataclass(frozen=True)
class DirectionExecutionResult:
    """控制器后续需要发送的消息、审计文本与运行态变化摘要。"""

    messages: tuple[DirectionWireMessage, ...]
    logs: tuple[str, ...]
    state_changed: bool


class DirectionChangeService:
    """执行状态机产出的 Action，不自行决定方向或网络发送时机。

    SEND 仅作为返回值交给阶段 4 网络层，避免领域服务直接操作 socket；
    APPLY/LOCK/UNLOCK 则统一写入 ``StationRuntimeState``，确保轨道编码、
    进路和信号服务读取到同一个方向与锁闭状态。
    """

    def __init__(self, runtime: StationRuntimeState) -> None:
        self.runtime = runtime

    def apply(self, outcome: DirectionOutcome) -> DirectionExecutionResult:
        messages: list[DirectionWireMessage] = []
        logs: list[str] = []
        state_changed = False

        for action in outcome.actions:
            if action.action_type is DirectionActionType.SEND:
                if action.message is None:
                    raise ValueError("SEND Action 缺少改方消息")
                messages.append(action.message)
            elif action.action_type is DirectionActionType.APPLY:
                if action.direction is None:
                    raise ValueError("APPLY Action 缺少目标方向")
                if self.runtime.running_direction is not action.direction:
                    self.runtime.running_direction = action.direction
                    self.runtime.state_version += 1
                    state_changed = True
            elif action.action_type is DirectionActionType.LOCK:
                if not self.runtime.direction_operation_locked:
                    self.runtime.direction_operation_locked = True
                    state_changed = True
            elif action.action_type is DirectionActionType.UNLOCK:
                if self.runtime.direction_operation_locked:
                    self.runtime.direction_operation_locked = False
                    state_changed = True
            elif action.action_type is DirectionActionType.RELEASE:
                # RELEASE 表示释放状态机内部预留，不等价于解除安全锁闭；
                # 是否解锁必须由同一 Outcome 中显式的 UNLOCK Action 决定。
                continue
            elif action.action_type is DirectionActionType.LOG and action.reason:
                logs.append(action.reason)

        return DirectionExecutionResult(tuple(messages), tuple(logs), state_changed)


@dataclass(frozen=True)
class CoordinatedDirectionResult:
    """一次编排的领域结果及其对统一运行态的执行摘要。"""

    outcome: DirectionOutcome
    execution: DirectionExecutionResult


class DirectionChangeCoordinator:
    """改方的唯一生产编排入口，保证先保护运行态、后交付网络消息。

    状态机仍负责纯领域决策；协调器负责把 Action 原子地应用到统一运行态，
    完成后才调用 ``send_message``。因此网络发送异常时，进路和信号已经处于
    锁闭状态，不会出现“报文已发出但运行态尚未保护”的窗口。
    """

    def __init__(
        self,
        machine: DirectionChangeMachine,
        runtime: StationRuntimeState,
        *,
        send_message: Callable[[DirectionWireMessage], None] | None = None,
        write_log: Callable[[str], None] | None = None,
    ) -> None:
        if machine.station_id != runtime.station_id:
            raise ValueError("状态机站点与统一运行态站点不一致")
        if machine.current_direction is not runtime.running_direction:
            raise ValueError("状态机方向与统一运行态初始方向不一致")
        if machine.operation_locked != runtime.direction_operation_locked:
            raise ValueError("状态机与统一运行态初始锁闭状态不一致")
        self.machine = machine
        self.runtime = runtime
        self._service = DirectionChangeService(runtime)
        self._send_message = send_message or (lambda _message: None)
        self._write_log = write_log or (lambda _text: None)

    def build_guard(
        self,
        *,
        connection_state: ConnectionState,
        peer_snapshot_fresh: bool,
        required_section_ids: frozenset[str],
        section_states: Mapping[str, TrackState],
        peer_state_version: int,
    ) -> DirectionGuard:
        """从唯一运行态构造守卫，避免调用方手填本地版本和活动进路。"""
        return DirectionGuard(
            connection_state=connection_state,
            peer_snapshot_fresh=peer_snapshot_fresh,
            required_section_ids=required_section_ids,
            section_states=section_states,
            active_route_ids=frozenset(self.runtime.active_route_ids),
            local_state_version=self.runtime.state_version,
            peer_state_version=peer_state_version,
        )

    def start_request(
        self,
        target_direction: RunningDirection,
        guard: DirectionGuard,
        *,
        now_ms: int,
        transaction_id: str | None = None,
    ) -> CoordinatedDirectionResult:
        return self._execute(
            self.machine.start_request(
                target_direction,
                guard,
                now_ms=now_ms,
                transaction_id=transaction_id,
            )
        )

    def handle(
        self,
        message: DirectionWireMessage,
        guard: DirectionGuard,
        *,
        now_ms: int,
    ) -> CoordinatedDirectionResult:
        return self._execute(self.machine.handle(message, guard, now_ms=now_ms))

    def expire(self, *, now_ms: int) -> CoordinatedDirectionResult:
        return self._execute(self.machine.expire(now_ms=now_ms))

    def on_connection_state(
        self, state: ConnectionState
    ) -> CoordinatedDirectionResult | None:
        """供阶段 4 ``state_changed`` 信号连接；非健康状态立即安全锁闭。"""
        if state is ConnectionState.HEALTHY:
            return None
        return self._execute(self.machine.disconnect())

    def restore_from_authority(
        self,
        authoritative_direction: RunningDirection,
        guard: DirectionGuard,
    ) -> CoordinatedDirectionResult:
        return self._execute(
            self.machine.restore_from_authority(authoritative_direction, guard)
        )

    def confirm_authority_applied(
        self,
        record: DirectionRecoveryRecord,
        guard: DirectionGuard,
    ) -> CoordinatedDirectionResult:
        return self._execute(self.machine.confirm_peer_applied(record, guard))

    def _execute(self, outcome: DirectionOutcome) -> CoordinatedDirectionResult:
        execution = self._service.apply(outcome)
        for text in execution.logs:
            self._write_log(text)
        # DirectionChangeService 已经应用全部 APPLY/LOCK/UNLOCK；此处才允许
        # 把报文交给网络适配层，从编排顺序上消除未保护发送窗口。
        try:
            for message in execution.messages:
                self._send_message(message)
        except Exception:
            # 发送失败即意味着通信状态无法确认。即使当前 Outcome 原本已解除
            # 预留，也必须立即重新锁闭，不能等待异步网络状态信号稍后到达。
            fault = self.machine.disconnect()
            fault_execution = self._service.apply(fault)
            for text in fault_execution.logs:
                self._write_log(text)
            raise
        if self.machine.current_direction is not self.runtime.running_direction:
            raise RuntimeError("改方执行后状态机与统一运行态方向不一致")
        if self.machine.operation_locked != self.runtime.direction_operation_locked:
            raise RuntimeError("改方执行后状态机与统一运行态锁闭状态不一致")
        return CoordinatedDirectionResult(outcome, execution)
