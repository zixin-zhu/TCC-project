"""CTCS-2 单线区间改方四阶段事务状态机。

状态机不依赖 Qt、socket 或 UI，只读取调用方提供的安全守卫快照，并产出
结构化 Action。控制器负责发送消息、记录日志和把 APPLY Action 应用到统一
运行状态。这样可以独立验证“批准只预留、提交前复核、失败保持原方向”。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Mapping
from uuid import UUID, uuid4

from app.core.enums import ConnectionState, DirectionPhase, RunningDirection, TrackState


class DirectionMessageKind(str, Enum):
    PREPARE = "PREPARE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    COMMIT = "COMMIT"
    ACK = "ACK"


class DirectionActionType(str, Enum):
    SEND = "SEND"
    APPLY = "APPLY"
    RELEASE = "RELEASE"
    LOCK = "LOCK"
    UNLOCK = "UNLOCK"
    LOG = "LOG"


class DirectionRejectCode(str, Enum):
    COMMUNICATION_UNHEALTHY = "COMMUNICATION_UNHEALTHY"
    PEER_SNAPSHOT_STALE = "PEER_SNAPSHOT_STALE"
    SECTION_UNSAFE = "SECTION_UNSAFE"
    ROUTE_CONFLICT = "ROUTE_CONFLICT"
    ACTIVE_TRANSACTION = "ACTIVE_TRANSACTION"
    ALREADY_DIRECTION = "ALREADY_DIRECTION"
    WRONG_TRANSACTION = "WRONG_TRANSACTION"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    DIRECTION_MISMATCH = "DIRECTION_MISMATCH"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    TIMEOUT = "TIMEOUT"
    DISCONNECTED = "DISCONNECTED"
    PEER_REJECTED = "PEER_REJECTED"
    NO_ACTIVE_TRANSACTION = "NO_ACTIVE_TRANSACTION"
    NOT_AUTHORITY = "NOT_AUTHORITY"
    RECOVERY_PENDING = "RECOVERY_PENDING"


@dataclass(frozen=True)
class DirectionGuard:
    """一次判定使用的不可变安全条件快照。"""

    connection_state: ConnectionState
    peer_snapshot_fresh: bool
    required_section_ids: frozenset[str]
    section_states: Mapping[str, TrackState]
    active_route_ids: frozenset[str]
    local_state_version: int
    peer_state_version: int


@dataclass(frozen=True)
class DirectionWireMessage:
    """可映射到阶段 4 DIRECTION_* payload 的领域消息。"""

    kind: DirectionMessageKind
    transaction_id: str
    requester_station_id: str
    responder_station_id: str
    source_station_id: str
    target_station_id: str
    original_direction: RunningDirection
    target_direction: RunningDirection
    requester_state_version: int
    expected_responder_state_version: int
    responder_state_version: int | None
    deadline_ms: int
    reject_code: DirectionRejectCode | None = None
    reason: str = ""


@dataclass(frozen=True)
class DirectionAction:
    action_type: DirectionActionType
    message: DirectionWireMessage | None = None
    direction: RunningDirection | None = None
    reason: str = ""


@dataclass(frozen=True)
class DirectionOutcome:
    accepted: bool
    phase: DirectionPhase
    reason: str
    reject_code: DirectionRejectCode | None
    actions: tuple[DirectionAction, ...] = ()


@dataclass(frozen=True)
class DirectionRecoveryRecord:
    """可持久化并在重连全量同步中交换的事务恢复证据。"""

    transaction_id: str
    requester_station_id: str
    responder_station_id: str
    original_direction: RunningDirection
    target_direction: RunningDirection
    requester_state_version: int
    responder_state_version: int | None
    requester_applied: bool


@dataclass
class _Transaction:
    transaction_id: str
    source_station_id: str
    target_station_id: str
    original_direction: RunningDirection
    target_direction: RunningDirection
    requester_state_version: int
    expected_responder_state_version: int
    responder_state_version: int | None
    deadline_ms: int
    requester: bool
    phase: DirectionPhase


_REASONS: Mapping[DirectionRejectCode, str] = {
    DirectionRejectCode.COMMUNICATION_UNHEALTHY: "站间通信不是 HEALTHY",
    DirectionRejectCode.PEER_SNAPSHOT_STALE: "对站快照已过期",
    DirectionRejectCode.SECTION_UNSAFE: "区间存在占用、故障占用或分路不良",
    DirectionRejectCode.ROUTE_CONFLICT: "存在活动进路",
    DirectionRejectCode.ACTIVE_TRANSACTION: "已有活动改方事务",
    DirectionRejectCode.ALREADY_DIRECTION: "当前已经是目标方向",
    DirectionRejectCode.WRONG_TRANSACTION: "事务 UUID 与活动事务不一致",
    DirectionRejectCode.VERSION_MISMATCH: "双方状态版本与事务记录不一致",
    DirectionRejectCode.DIRECTION_MISMATCH: "原方向或目标方向不一致",
    DirectionRejectCode.OUT_OF_ORDER: "改方消息顺序不合法",
    DirectionRejectCode.TIMEOUT: "改方事务超时",
    DirectionRejectCode.DISCONNECTED: "改方期间站间通信中断",
    DirectionRejectCode.PEER_REJECTED: "对站拒绝改方",
    DirectionRejectCode.NO_ACTIVE_TRANSACTION: "当前没有活动改方事务",
    DirectionRejectCode.NOT_AUTHORITY: "只有 A 站方向权威可以发起改方",
    DirectionRejectCode.RECOVERY_PENDING: "方向处于安全锁闭，必须先完成权威同步恢复",
}

_FAULT_LOCK_CODES = frozenset(
    {
        DirectionRejectCode.COMMUNICATION_UNHEALTHY,
        DirectionRejectCode.PEER_SNAPSHOT_STALE,
        DirectionRejectCode.VERSION_MISMATCH,
        DirectionRejectCode.DIRECTION_MISMATCH,
        DirectionRejectCode.TIMEOUT,
        DirectionRejectCode.DISCONNECTED,
    }
)


class DirectionChangeMachine:
    """单站改方状态机；相同输入消息返回缓存结果以保证幂等。"""

    def __init__(
        self,
        station_id: str,
        peer_station_id: str,
        current_direction: RunningDirection,
        *,
        timeout_ms: int = 5000,
        authority_station_id: str = "A",
    ) -> None:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms 必须为正数")
        self.station_id = station_id
        self.peer_station_id = peer_station_id
        self.current_direction = current_direction
        self.timeout_ms = timeout_ms
        self.authority_station_id = authority_station_id
        self.phase = DirectionPhase.IDLE
        self.operation_locked = False
        self._transaction: _Transaction | None = None
        self._last_recovery: DirectionRecoveryRecord | None = None
        self._responses: OrderedDict[DirectionWireMessage, DirectionOutcome] = OrderedDict()

    @property
    def has_active_transaction(self) -> bool:
        return self._transaction is not None

    def start_request(
        self,
        target_direction: RunningDirection,
        guard: DirectionGuard,
        *,
        now_ms: int,
        transaction_id: str | None = None,
    ) -> DirectionOutcome:
        if self.station_id != self.authority_station_id:
            return self._reject(DirectionRejectCode.NOT_AUTHORITY)
        if self.operation_locked:
            return self._reject(DirectionRejectCode.RECOVERY_PENDING)
        if self._transaction is not None:
            return self._reject(DirectionRejectCode.ACTIVE_TRANSACTION)
        if target_direction is self.current_direction:
            return self._reject(DirectionRejectCode.ALREADY_DIRECTION)
        unsafe = self._guard_failure(guard)
        if unsafe is not None:
            if unsafe in _FAULT_LOCK_CODES:
                return self._fault_lock(unsafe)
            return self._reject(unsafe)

        tx_id = transaction_id or str(uuid4())
        try:
            UUID(tx_id)
        except (ValueError, TypeError, AttributeError):
            return self._reject(DirectionRejectCode.WRONG_TRANSACTION)
        self._last_recovery = None
        deadline = now_ms + self.timeout_ms
        self._transaction = _Transaction(
            transaction_id=tx_id,
            source_station_id=self.station_id,
            target_station_id=self.peer_station_id,
            original_direction=self.current_direction,
            target_direction=target_direction,
            requester_state_version=guard.local_state_version,
            expected_responder_state_version=guard.peer_state_version,
            responder_state_version=None,
            deadline_ms=deadline,
            requester=True,
            phase=DirectionPhase.WAIT_PEER,
        )
        self.phase = DirectionPhase.WAIT_PEER
        self.operation_locked = True
        message = self._message(DirectionMessageKind.PREPARE)
        return DirectionOutcome(
            True,
            self.phase,
            "改方申请已生成，等待对站批准",
            None,
            (
                DirectionAction(DirectionActionType.LOCK, reason="改方事务开始"),
                DirectionAction(DirectionActionType.SEND, message=message),
            ),
        )

    def handle(
        self, message: DirectionWireMessage, guard: DirectionGuard, *, now_ms: int
    ) -> DirectionOutcome:
        cached = self._responses.get(message)
        if cached is not None:
            # 重复报文需要重发协议响应，但绝不能重复执行 APPLY/LOCK/UNLOCK。
            # 否则一个完成后的旧 PREPARE 可能把已经解除的运行态再次锁住。
            replay_actions = tuple(
                action
                for action in cached.actions
                if action.action_type in {DirectionActionType.SEND, DirectionActionType.LOG}
            )
            return DirectionOutcome(
                cached.accepted,
                cached.phase,
                cached.reason,
                cached.reject_code,
                replay_actions,
            )
        if message.target_station_id != self.station_id or message.source_station_id != self.peer_station_id:
            return self._remember(message, self._reject(DirectionRejectCode.WRONG_TRANSACTION))
        if message.kind is DirectionMessageKind.REJECT:
            if (
                self._transaction is not None
                and message.transaction_id == self._transaction.transaction_id
            ):
                return self._remember(message, self._handle_reject(message))
            return self._remember(
                message,
                self._reject_without_reply(DirectionRejectCode.WRONG_TRANSACTION),
            )
        if self._transaction is not None and now_ms >= self._transaction.deadline_ms:
            return self._remember(
                message,
                self._abort_with_message(message, DirectionRejectCode.TIMEOUT),
            )
        if message.deadline_ms <= now_ms:
            return self._remember(
                message,
                self._reject_for_message(message, DirectionRejectCode.TIMEOUT),
            )

        if message.kind is DirectionMessageKind.PREPARE:
            outcome = self._handle_prepare(message, guard, now_ms)
        elif self._transaction is None:
            outcome = self._reject_for_message(
                message, DirectionRejectCode.WRONG_TRANSACTION
            )
        elif message.transaction_id != self._transaction.transaction_id:
            outcome = self._reject_for_message(
                message, DirectionRejectCode.WRONG_TRANSACTION
            )
        elif message.kind is DirectionMessageKind.APPROVE:
            outcome = self._handle_approve(message, guard, now_ms)
        elif message.kind is DirectionMessageKind.COMMIT:
            outcome = self._handle_commit(message, guard, now_ms)
        elif message.kind is DirectionMessageKind.ACK:
            outcome = self._handle_ack(message)
        else:
            outcome = self._reject_for_message(message, DirectionRejectCode.OUT_OF_ORDER)
        return self._remember(message, outcome)

    def expire(self, *, now_ms: int) -> DirectionOutcome:
        tx = self._transaction
        if tx is None:
            return self._reject(DirectionRejectCode.NO_ACTIVE_TRANSACTION)
        if now_ms < tx.deadline_ms:
            return DirectionOutcome(True, tx.phase, "事务尚未超时", None)
        return self._abort(DirectionRejectCode.TIMEOUT)

    def disconnect(self) -> DirectionOutcome:
        if self._transaction is None:
            self.phase = DirectionPhase.FAULT_LOCKED
            self.operation_locked = True
            reason = _REASONS[DirectionRejectCode.DISCONNECTED]
            return DirectionOutcome(
                False,
                self.phase,
                reason,
                DirectionRejectCode.DISCONNECTED,
                (
                    DirectionAction(DirectionActionType.LOCK, reason=reason),
                    DirectionAction(DirectionActionType.LOG, reason=reason),
                ),
            )
        return self._abort(DirectionRejectCode.DISCONNECTED)

    def restore_from_authority(
        self,
        authoritative_direction: RunningDirection,
        guard: DirectionGuard,
    ) -> DirectionOutcome:
        """完成重连全量同步，并在安全条件复核后解除方向作业锁闭。

        A 站只接受与本站权威真值一致的同步结果；B 站则把 A 站方向覆盖到
        本地投影。调用方必须先由阶段 4 校验全量同步的站点、序号与版本。
        """
        unsafe = self._guard_failure(guard)
        if unsafe is not None:
            self.phase = DirectionPhase.FAULT_LOCKED
            self.operation_locked = True
            return DirectionOutcome(
                False,
                self.phase,
                f"权威同步恢复失败：{_REASONS[unsafe]}",
                unsafe,
                (DirectionAction(DirectionActionType.LOCK, reason=_REASONS[unsafe]),),
            )
        if (
            self.station_id == self.authority_station_id
            and authoritative_direction is not self.current_direction
        ):
            self.phase = DirectionPhase.FAULT_LOCKED
            self.operation_locked = True
            reason = _REASONS[DirectionRejectCode.DIRECTION_MISMATCH]
            return DirectionOutcome(
                False,
                self.phase,
                reason,
                DirectionRejectCode.DIRECTION_MISMATCH,
                (
                    DirectionAction(DirectionActionType.LOCK, reason=reason),
                    DirectionAction(DirectionActionType.LOG, reason=reason),
                ),
            )

        actions: list[DirectionAction] = []
        if self.current_direction is not authoritative_direction:
            self.current_direction = authoritative_direction
            actions.append(
                DirectionAction(
                    DirectionActionType.APPLY,
                    direction=authoritative_direction,
                    reason="按 A 站全量同步刷新方向投影",
                )
            )
        self._transaction = None
        self._last_recovery = None
        self.phase = DirectionPhase.COMPLETED
        self.operation_locked = False
        actions.extend(
            (
                DirectionAction(DirectionActionType.UNLOCK, reason="权威方向同步完成"),
                DirectionAction(DirectionActionType.LOG, reason="方向安全锁闭已解除"),
            )
        )
        return DirectionOutcome(
            True,
            self.phase,
            "权威方向同步及安全复核完成",
            None,
            tuple(actions),
        )

    def export_recovery_record(self) -> DirectionRecoveryRecord:
        """导出应用层事务证据；阶段 6 将其持久化并随全量同步交换。"""
        if self._last_recovery is not None:
            return self._last_recovery
        tx = self._transaction
        if tx is None:
            raise RuntimeError("当前没有可导出的改方恢复记录")
        return self._recovery_record(
            tx,
            requester_applied=(
                tx.requester and self.current_direction is tx.target_direction
            ),
        )

    def confirm_peer_applied(
        self, record: DirectionRecoveryRecord, guard: DirectionGuard
    ) -> DirectionOutcome:
        """B 站用 A 站提交证据恢复投影，并在重新通过守卫后解除锁闭。"""
        unsafe = self._guard_failure(guard)
        if unsafe is not None:
            self.operation_locked = True
            self.phase = DirectionPhase.FAULT_LOCKED
            return DirectionOutcome(
                False,
                self.phase,
                f"恢复校验失败：{_REASONS[unsafe]}",
                unsafe,
                (DirectionAction(DirectionActionType.LOCK, reason=_REASONS[unsafe]),),
            )
        tx = self._transaction
        if tx is None:
            pending = self._last_recovery
            if (
                pending is None
                or pending.requester_applied
                or record.transaction_id != pending.transaction_id
                or record.requester_station_id != pending.requester_station_id
                or record.responder_station_id != pending.responder_station_id
                or record.original_direction is not pending.original_direction
                or record.target_direction is not pending.target_direction
                or record.requester_state_version != pending.requester_state_version
                or record.responder_state_version != pending.responder_state_version
                or not record.requester_applied
            ):
                return self._reject(DirectionRejectCode.WRONG_TRANSACTION)
            self.current_direction = record.target_direction
            self._last_recovery = record
            self.phase = DirectionPhase.COMPLETED
            self.operation_locked = False
            return DirectionOutcome(
                True,
                self.phase,
                "重连恢复记录一致，重新应用目标方向",
                None,
                (
                    DirectionAction(
                        DirectionActionType.APPLY,
                        direction=record.target_direction,
                        reason="根据申请方持久化证据恢复改方",
                    ),
                    DirectionAction(DirectionActionType.UNLOCK, reason="权威投影恢复完成"),
                    DirectionAction(DirectionActionType.LOG, reason="改方恢复完成"),
                ),
            )
        if tx.requester or tx.phase is not DirectionPhase.COMMITTING:
            return self._reject(DirectionRejectCode.WRONG_TRANSACTION)
        expected = self._recovery_record(tx, requester_applied=True)
        if record != expected:
            return self._reject(DirectionRejectCode.VERSION_MISMATCH)
        self._transaction = None
        self.phase = DirectionPhase.COMPLETED
        self._last_recovery = record
        self.operation_locked = False
        return DirectionOutcome(
            True,
            self.phase,
            "已收到申请方完成 APPLY 的应用层证据，响应方提交完成",
            None,
            (
                DirectionAction(DirectionActionType.UNLOCK, reason="权威投影已确认"),
                DirectionAction(DirectionActionType.LOG, reason="改方事务完成"),
            ),
        )

    def _handle_prepare(
        self, message: DirectionWireMessage, guard: DirectionGuard, now_ms: int
    ) -> DirectionOutcome:
        if message.requester_station_id != self.authority_station_id:
            return self._reject_for_message(message, DirectionRejectCode.NOT_AUTHORITY)
        if self.operation_locked and self._transaction is None:
            return self._reject_for_message(
                message, DirectionRejectCode.RECOVERY_PENDING
            )
        if self._transaction is not None:
            code = (
                DirectionRejectCode.WRONG_TRANSACTION
                if message.transaction_id != self._transaction.transaction_id
                else DirectionRejectCode.OUT_OF_ORDER
            )
            return self._reject_for_message(message, code)
        if (
            message.original_direction is not self.current_direction
            or message.target_direction is self.current_direction
        ):
            return self._fault_lock_for_message(
                message, DirectionRejectCode.DIRECTION_MISMATCH
            )
        if (
            message.requester_state_version != guard.peer_state_version
            or message.expected_responder_state_version != guard.local_state_version
        ):
            return self._fault_lock_for_message(
                message, DirectionRejectCode.VERSION_MISMATCH
            )
        unsafe = self._guard_failure(guard)
        if unsafe is not None:
            if unsafe in _FAULT_LOCK_CODES:
                return self._fault_lock_for_message(message, unsafe)
            return self._reject_for_message(message, unsafe)

        self._transaction = _Transaction(
            transaction_id=message.transaction_id,
            source_station_id=message.source_station_id,
            target_station_id=message.target_station_id,
            original_direction=message.original_direction,
            target_direction=message.target_direction,
            requester_state_version=message.requester_state_version,
            expected_responder_state_version=message.expected_responder_state_version,
            responder_state_version=guard.local_state_version,
            deadline_ms=now_ms + self.timeout_ms,
            requester=False,
            phase=DirectionPhase.APPROVED,
        )
        self._last_recovery = None
        self.phase = DirectionPhase.APPROVED
        self.operation_locked = True
        approve = self._message(DirectionMessageKind.APPROVE)
        return DirectionOutcome(
            True,
            self.phase,
            "安全条件满足，已预留；方向尚未切换",
            None,
            (
                DirectionAction(DirectionActionType.LOCK, reason="已为权威改方预留"),
                DirectionAction(DirectionActionType.SEND, message=approve),
            ),
        )

    def _handle_approve(
        self, message: DirectionWireMessage, guard: DirectionGuard, now_ms: int
    ) -> DirectionOutcome:
        tx = self._require_transaction()
        if not tx.requester or tx.phase is not DirectionPhase.WAIT_PEER:
            return self._reject_for_message(message, DirectionRejectCode.OUT_OF_ORDER)
        if not (
            message.original_direction is tx.original_direction
            and message.target_direction is tx.target_direction
            and message.requester_state_version == tx.requester_state_version
            and message.requester_state_version == guard.local_state_version
            and message.expected_responder_state_version
            == tx.expected_responder_state_version
            and message.expected_responder_state_version == guard.peer_state_version
            and message.responder_state_version == guard.peer_state_version
        ):
            return self._abort_with_message(message, DirectionRejectCode.VERSION_MISMATCH)
        unsafe = self._guard_failure(guard)
        if unsafe is not None:
            return self._abort_with_message(message, unsafe)
        tx.responder_state_version = message.responder_state_version
        tx.deadline_ms = now_ms + self.timeout_ms
        tx.phase = DirectionPhase.COMMITTING
        self.phase = DirectionPhase.COMMITTING
        # A 站是唯一方向权威。复核通过后先提交权威真值，再向 B 发布投影；
        # 此后失败只能保持锁闭，不能把权威方向回滚成另一种真值。
        self.current_direction = tx.target_direction
        self.operation_locked = True
        commit = self._message(DirectionMessageKind.COMMIT)
        return DirectionOutcome(
            True,
            self.phase,
            "对站已批准，A 站提交权威方向并发送 COMMIT 投影",
            None,
            (
                DirectionAction(
                    DirectionActionType.APPLY,
                    direction=tx.target_direction,
                    reason="A 站提交唯一权威方向",
                ),
                DirectionAction(DirectionActionType.SEND, message=commit),
            ),
        )

    def _handle_commit(
        self, message: DirectionWireMessage, guard: DirectionGuard, now_ms: int
    ) -> DirectionOutcome:
        tx = self._require_transaction()
        if tx.requester or tx.phase is not DirectionPhase.APPROVED:
            return self._reject_for_message(message, DirectionRejectCode.OUT_OF_ORDER)
        if not self._versions_match(message, guard):
            return self._abort_with_message(message, DirectionRejectCode.VERSION_MISMATCH)
        unsafe = self._guard_failure(guard)
        if unsafe is not None:
            return self._abort_with_message(message, unsafe)

        self.current_direction = tx.target_direction
        self.operation_locked = True
        self.phase = DirectionPhase.COMMITTING
        tx.phase = DirectionPhase.COMMITTING
        tx.deadline_ms = now_ms + self.timeout_ms
        ack = self._message(DirectionMessageKind.ACK)
        outcome = DirectionOutcome(
            True,
            self.phase,
            "COMMIT 复核通过，应用 A 站权威方向投影并等待最终确认",
            None,
            (
                DirectionAction(DirectionActionType.APPLY, direction=tx.target_direction),
                DirectionAction(DirectionActionType.SEND, message=ack),
            ),
        )
        return outcome

    def _handle_ack(self, message: DirectionWireMessage) -> DirectionOutcome:
        tx = self._require_transaction()
        if not tx.requester or tx.phase is not DirectionPhase.COMMITTING:
            return self._reject_for_message(message, DirectionRejectCode.OUT_OF_ORDER)
        if not self._wire_matches_transaction(message, tx):
            return self._abort_with_message(message, DirectionRejectCode.VERSION_MISMATCH)
        self.phase = DirectionPhase.COMPLETED
        self._last_recovery = self._recovery_record(tx, requester_applied=True)
        self.operation_locked = False
        outcome = DirectionOutcome(
            True,
            self.phase,
            "收到 B 站投影 ACK，A 站解除方向作业锁闭",
            None,
            (DirectionAction(DirectionActionType.UNLOCK, reason="B 站权威投影已确认"),),
        )
        self._transaction = None
        return outcome

    def _handle_reject(self, message: DirectionWireMessage) -> DirectionOutcome:
        code = message.reject_code or DirectionRejectCode.PEER_REJECTED
        return self._abort(code, reason=message.reason or _REASONS[code])

    def _guard_failure(self, guard: DirectionGuard) -> DirectionRejectCode | None:
        if guard.connection_state is not ConnectionState.HEALTHY:
            return DirectionRejectCode.COMMUNICATION_UNHEALTHY
        if not guard.peer_snapshot_fresh:
            return DirectionRejectCode.PEER_SNAPSHOT_STALE
        if set(guard.section_states) != set(guard.required_section_ids):
            return DirectionRejectCode.SECTION_UNSAFE
        if any(state is not TrackState.CLEAR for state in guard.section_states.values()):
            return DirectionRejectCode.SECTION_UNSAFE
        if guard.active_route_ids:
            return DirectionRejectCode.ROUTE_CONFLICT
        return None

    def _versions_match(
        self, message: DirectionWireMessage, guard: DirectionGuard
    ) -> bool:
        tx = self._require_transaction()
        return (
            self._wire_matches_transaction(message, tx)
            and message.requester_state_version == (
                guard.local_state_version if tx.requester else guard.peer_state_version
            )
            and message.responder_state_version == (
                guard.peer_state_version if tx.requester else guard.local_state_version
            )
        )

    @staticmethod
    def _wire_matches_transaction(
        message: DirectionWireMessage, tx: _Transaction
    ) -> bool:
        return (
            message.original_direction is tx.original_direction
            and message.target_direction is tx.target_direction
            and message.requester_state_version == tx.requester_state_version
            and message.expected_responder_state_version
            == tx.expected_responder_state_version
            and message.responder_state_version == tx.responder_state_version
        )

    def _message(
        self,
        kind: DirectionMessageKind,
        *,
        reject_code: DirectionRejectCode | None = None,
        reason: str = "",
    ) -> DirectionWireMessage:
        tx = self._require_transaction()
        source = self.station_id
        target = self.peer_station_id
        return DirectionWireMessage(
            kind=kind,
            transaction_id=tx.transaction_id,
            requester_station_id=tx.source_station_id,
            responder_station_id=tx.target_station_id,
            source_station_id=source,
            target_station_id=target,
            original_direction=tx.original_direction,
            target_direction=tx.target_direction,
            requester_state_version=tx.requester_state_version,
            expected_responder_state_version=tx.expected_responder_state_version,
            responder_state_version=tx.responder_state_version,
            deadline_ms=tx.deadline_ms,
            reject_code=reject_code,
            reason=reason,
        )

    def _reject_for_message(
        self, message: DirectionWireMessage, code: DirectionRejectCode
    ) -> DirectionOutcome:
        reason = _REASONS[code]
        rejection = DirectionWireMessage(
            kind=DirectionMessageKind.REJECT,
            transaction_id=message.transaction_id,
            requester_station_id=message.requester_station_id,
            responder_station_id=message.responder_station_id,
            source_station_id=self.station_id,
            target_station_id=self.peer_station_id,
            original_direction=message.original_direction,
            target_direction=message.target_direction,
            requester_state_version=message.requester_state_version,
            expected_responder_state_version=message.expected_responder_state_version,
            responder_state_version=message.responder_state_version,
            deadline_ms=message.deadline_ms,
            reject_code=code,
            reason=reason,
        )
        return DirectionOutcome(
            False,
            DirectionPhase.REJECTED,
            reason,
            code,
            (DirectionAction(DirectionActionType.SEND, message=rejection),),
        )

    def _abort_with_message(
        self, message: DirectionWireMessage, code: DirectionRejectCode
    ) -> DirectionOutcome:
        outcome = self._reject_for_message(message, code)
        tx = self._transaction
        must_lock = code in _FAULT_LOCK_CODES
        if tx is not None and (
            self.current_direction is tx.target_direction or must_lock
        ):
            # 权威方向已提交或 B 已应用权威投影时，失败只能进入安全锁闭。
            # 回滚会重新制造两个可独立解释的方向真值，因此严禁回滚。
            if self.current_direction is tx.target_direction:
                self._last_recovery = self._recovery_record(
                    tx, requester_applied=tx.requester
                )
            self._transaction = None
            self.phase = DirectionPhase.FAULT_LOCKED
            self.operation_locked = True
            return DirectionOutcome(
                False,
                self.phase,
                outcome.reason,
                outcome.reject_code,
                outcome.actions
                + (
                    DirectionAction(DirectionActionType.LOCK, reason=outcome.reason),
                    DirectionAction(DirectionActionType.LOG, reason=outcome.reason),
                ),
            )
        self._transaction = None
        self.phase = DirectionPhase.REJECTED
        self.operation_locked = False
        return DirectionOutcome(
            outcome.accepted,
            outcome.phase,
            outcome.reason,
            outcome.reject_code,
            outcome.actions
            + (
                DirectionAction(DirectionActionType.RELEASE, reason=outcome.reason),
                DirectionAction(DirectionActionType.UNLOCK, reason=outcome.reason),
            ),
        )

    def _abort(
        self, code: DirectionRejectCode, *, reason: str | None = None
    ) -> DirectionOutcome:
        text = reason or _REASONS[code]
        tx = self._transaction
        must_lock = code in _FAULT_LOCK_CODES
        if tx is not None and (
            self.current_direction is tx.target_direction or must_lock
        ):
            # A 已提交权威方向，或 B 已应用该权威投影。网络失败时保留方向
            # 并锁闭行车作业，等待重连后用 A 的记录恢复，绝不反向 APPLY。
            if self.current_direction is tx.target_direction:
                self._last_recovery = self._recovery_record(
                    tx, requester_applied=tx.requester
                )
            self._transaction = None
            self.phase = DirectionPhase.FAULT_LOCKED
            self.operation_locked = True
            return DirectionOutcome(
                False,
                self.phase,
                text,
                code,
                (
                    DirectionAction(DirectionActionType.LOCK, reason=text),
                    DirectionAction(DirectionActionType.LOG, reason=text),
                ),
            )
        self._transaction = None
        self.phase = DirectionPhase.REJECTED
        self.operation_locked = False
        return DirectionOutcome(
            False,
            self.phase,
            text,
            code,
            (
                DirectionAction(DirectionActionType.RELEASE, reason=text),
                DirectionAction(DirectionActionType.UNLOCK, reason=text),
                DirectionAction(DirectionActionType.LOG, reason=text),
            ),
        )

    def _reject(self, code: DirectionRejectCode) -> DirectionOutcome:
        return DirectionOutcome(
            False,
            DirectionPhase.REJECTED,
            _REASONS[code],
            code,
            (DirectionAction(DirectionActionType.LOG, reason=_REASONS[code]),),
        )

    def _fault_lock(self, code: DirectionRejectCode) -> DirectionOutcome:
        """无法确认通信、投影或版本时遵循 fail-closed，禁止恢复行车。"""
        reason = _REASONS[code]
        self.phase = DirectionPhase.FAULT_LOCKED
        self.operation_locked = True
        return DirectionOutcome(
            False,
            self.phase,
            reason,
            code,
            (
                DirectionAction(DirectionActionType.LOCK, reason=reason),
                DirectionAction(DirectionActionType.LOG, reason=reason),
            ),
        )

    def _fault_lock_for_message(
        self, message: DirectionWireMessage, code: DirectionRejectCode
    ) -> DirectionOutcome:
        rejection = self._reject_for_message(message, code)
        self.phase = DirectionPhase.FAULT_LOCKED
        self.operation_locked = True
        return DirectionOutcome(
            False,
            self.phase,
            rejection.reason,
            code,
            rejection.actions
            + (DirectionAction(DirectionActionType.LOCK, reason=rejection.reason),),
        )

    def _reject_without_reply(self, code: DirectionRejectCode) -> DirectionOutcome:
        """REJECT 是终止消息，无法关联时只记录，绝不再回发 REJECT。"""
        return DirectionOutcome(
            False,
            DirectionPhase.REJECTED,
            _REASONS[code],
            code,
            (DirectionAction(DirectionActionType.LOG, reason=_REASONS[code]),),
        )

    def _require_transaction(self) -> _Transaction:
        if self._transaction is None:
            raise RuntimeError("内部错误：需要活动事务")
        return self._transaction

    @staticmethod
    def _recovery_record(
        tx: _Transaction, *, requester_applied: bool
    ) -> DirectionRecoveryRecord:
        return DirectionRecoveryRecord(
            transaction_id=tx.transaction_id,
            requester_station_id=tx.source_station_id,
            responder_station_id=tx.target_station_id,
            original_direction=tx.original_direction,
            target_direction=tx.target_direction,
            requester_state_version=tx.requester_state_version,
            responder_state_version=tx.responder_state_version,
            requester_applied=requester_applied,
        )

    def _remember(
        self,
        message: DirectionWireMessage,
        outcome: DirectionOutcome,
    ) -> DirectionOutcome:
        self._responses[message] = outcome
        self._responses.move_to_end(message)
        while len(self._responses) > 256:
            self._responses.popitem(last=False)
        return outcome
