"""单站 TCC 的唯一写入口与可序列化 UI 快照。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from app.core.enums import ConnectionState, DirectionPhase, RunningDirection, TelegramMode, TrackInputSource, TrackState
from app.core.exceptions import ProtocolError, UnknownTrackSectionError
from app.core.models import (
    CodingRules,
    OperationResult,
    PeerSnapshot,
    ProjectConfig,
    SignalControlResult,
    StationRuntimeState,
    TrackCodingResult,
)
from app.domain.balise_telegram import LogicalTelegramService, SimulationEnvelopeCodec
from app.domain.direction_change import (
    DirectionChangeMachine,
    DirectionMessageKind,
    DirectionRecoveryRecord,
    DirectionWireMessage,
)
from app.domain.leu import LeuContext, LeuService, TelegramSelectionResult
from app.domain.route_control import RouteControlService
from app.domain.signal_control import SignalControlService
from app.domain.temporary_speed import (
    TemporarySpeedRestriction,
    TemporarySpeedService,
    TemporarySpeedState,
)
from app.domain.track_circuit import TrackCircuitCodingService
from app.infrastructure.sqlite_repository import (
    DirectionAuthorityEntry,
    OperationLogEntry,
    TelegramHistoryEntry,
)
from app.services.alarm_service import AlarmLevel, AlarmRecord, AlarmService
from app.services.direction_change_service import DirectionChangeCoordinator


class PersistencePort(Protocol):
    def save_operation(self, entry: OperationLogEntry) -> bool: ...

    def save_telegram(self, entry: TelegramHistoryEntry) -> bool: ...

    def save_direction_authority(self, entry: DirectionAuthorityEntry) -> bool: ...

    def load_direction_authority(
        self, station_id: str, *, now_ms: int
    ) -> DirectionAuthorityEntry | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class TelegramView:
    """明确区分逻辑报文与课程仿真封装，禁止冒充现场位流。"""

    port_id: str
    mode: TelegramMode
    reason: str
    template_id: str
    balise_id: str
    logical_payload: Mapping[str, Any]
    teaching_bit_view: str
    simulation_format: str
    simulation_hex: str
    crc32: str


@dataclass(frozen=True)
class TccSnapshot:
    station_id: str
    station_name: str
    state_version: int
    running_direction: str
    direction_operation_locked: bool
    connection_state: ConnectionState
    tracks: Mapping[str, TrackState]
    codes: Mapping[str, TrackCodingResult]
    signals: Mapping[str, SignalControlResult]
    active_route_ids: tuple[str, ...]
    temporary_speeds: tuple[TemporarySpeedRestriction, ...]
    telegram: TelegramView
    alarms: tuple[AlarmRecord, ...]
    operation_logs: tuple[OperationLogEntry, ...]
    network_received: int
    network_sent: int


class TccController:
    """组合领域服务；UI、网络回调和测试都只能通过本类修改状态。"""

    def __init__(
        self,
        config: ProjectConfig,
        coding_rules: CodingRules,
        telegram_catalog: Mapping[str, Any],
        *,
        alarms: AlarmService,
        persistence: PersistencePort,
        publish_state: Callable[[Mapping[str, Any]], None],
        cache_state: Callable[[Mapping[str, Any]], None] | None = None,
        snapshot_listener: Callable[[TccSnapshot], None],
        stage_listener: Callable[[str], None] | None = None,
        clock_ms: Callable[[], int],
        send_direction: Callable[[DirectionWireMessage], None] | None = None,
        send_direction_confirmation: Callable[[DirectionRecoveryRecord], None]
        | None = None,
    ) -> None:
        self.config = config
        self.alarms = alarms
        self.persistence = persistence
        self._publish_state = publish_state
        self._cache_state = cache_state or (lambda _payload: None)
        self._snapshot_listeners = [snapshot_listener]
        self._stage_listener = stage_listener or (lambda _stage: None)
        self._clock_ms = clock_ms
        self._peer_timeout_ms = coding_rules.peer_timeout_ms
        self._direction_sender = send_direction
        self._direction_confirmation_sender = send_direction_confirmation
        self._closed = False
        self.connection_state = ConnectionState.DISCONNECTED
        self.peer_snapshot: PeerSnapshot | None = None
        self._peer_snapshot_was_fresh = False
        self._deferred_state_sync = False
        restored_authority = (
            persistence.load_direction_authority(
                config.station.station_id, now_ms=self._clock_ms()
            )
            if config.station.station_id == "A"
            else None
        )
        self.runtime = StationRuntimeState.create(
            config.station.station_id,
            (section.id for section in config.topology.sections),
        )
        if restored_authority is not None:
            self.runtime.running_direction = restored_authority.direction
            self.runtime.state_version = restored_authority.state_version
        self._persisted_authoritative_direction = (
            restored_authority.direction if restored_authority is not None else None
        )
        self._pending_recovery = (
            self._parse_recovery_record(restored_authority.recovery)
            if restored_authority is not None
            and restored_authority.recovery is not None
            else None
        )
        self._direction = DirectionChangeCoordinator(
            DirectionChangeMachine(
                config.station.station_id,
                config.station.network.peer_station_id,
                self.runtime.running_direction,
            ),
            self.runtime,
            send_message=self._send_direction,
            before_apply=self._persist_authority_before_direction_apply,
        )
        # 应用启动到完成健康握手和权威全量同步之前必须 fail-closed。
        self._direction.on_connection_state(ConnectionState.DISCONNECTED)
        self._coding = TrackCircuitCodingService(config.topology, coding_rules)
        self._signals = SignalControlService(config.topology)
        self._routes = RouteControlService(config.topology)
        self._telegram_service = LogicalTelegramService(telegram_catalog)
        self._leu = LeuService(
            config.balise_groups,
            self._telegram_service,
            input_timeout_ms=coding_rules.peer_timeout_ms,
        )
        self._leu_connected = True
        line_length = sum(
            section.length_m
            for section in config.topology.sections
            if section.id.startswith("Q")
        )
        self._temporary_speeds = TemporarySpeedService(0, line_length)
        self._latest_codes: list[TrackCodingResult] = []
        self._latest_signals: list[SignalControlResult] = []
        self._latest_telegram: TelegramView | None = None
        self._operation_logs: list[OperationLogEntry] = []
        self._network_received = 0
        self._network_sent = 0
        if config.station.station_id == "A" and restored_authority is None:
            self._save_authoritative_direction(recovery=None)
        self.snapshot = self._recalculate_and_publish(
            operation=None, include_state_stage=False
        )

    def add_snapshot_listener(self, listener: Callable[[TccSnapshot], None]) -> None:
        self._snapshot_listeners.append(listener)

    def network_state_payload(self) -> Mapping[str, Any]:
        """返回可在线程间复制的状态字典，不暴露可变运行态对象。"""
        return dict(self._state_payload())

    def now_ms(self) -> int:
        return self._clock_ms()

    @property
    def direction_phase(self) -> DirectionPhase:
        """向界面暴露只读改方阶段，不允许界面接触状态机内部对象。"""
        return self._direction.machine.phase

    def update_network_metrics(self, *, received: int, sent: int) -> None:
        """由主线程网络桥接更新只读统计，不触发新的站间状态同步。"""
        self._ensure_open()
        self._network_received = max(0, received)
        self._network_sent = max(0, sent)
        self._refresh_snapshot_only()

    def raise_external_alarm(
        self,
        code: str,
        level: AlarmLevel,
        message: str,
        source: str,
    ) -> None:
        """网络桥接等外部设施只能通过控制器改变告警和展示快照。"""
        self._ensure_open()
        self.alarms.raise_alarm(
            code, level, message, source, now_ms=self._clock_ms()
        )
        self._refresh_snapshot_only()

    def prestore_temporary_speed(
        self,
        tsr_id: str,
        start_m: float,
        end_m: float,
        speed_kmh: float,
        valid_from_ms: int,
        valid_until_ms: int,
    ) -> OperationResult:
        self._ensure_open()
        now = self._clock_ms()
        try:
            self._temporary_speeds.prestore(
                tsr_id,
                start_m,
                end_m,
                speed_kmh,
                valid_from_ms,
                valid_until_ms,
                now,
            )
        except ValueError as exc:
            result = OperationResult(False, str(exc))
            self._save_operation(f"预存临时限速 {tsr_id}", result, {})
            return result
        self.runtime.state_version += 1
        result = OperationResult(True, "临时限速已预存")
        self._recalculate_and_publish(
            operation=(f"预存临时限速 {tsr_id}", result, {"tsr_id": tsr_id})
        )
        return result

    def activate_temporary_speed(self, tsr_id: str) -> OperationResult:
        return self._change_temporary_speed(tsr_id, activate=True)

    def cancel_temporary_speed(self, tsr_id: str) -> OperationResult:
        return self._change_temporary_speed(tsr_id, activate=False)

    def request_direction_change(self, target: RunningDirection) -> OperationResult:
        self._ensure_open()
        if self._direction_sender is None:
            result = OperationResult(False, "改方网络协调器尚未装配")
            self._save_operation("申请区间改方", result, {"target": target.value})
            return result
        try:
            coordinated = self._direction.start_request(
                target,
                self._direction_guard(),
                now_ms=self._clock_ms(),
            )
        except (OSError, ProtocolError, RuntimeError) as exc:
            return self._direction_transport_failure(
                "申请区间改方", exc, {"target": target.value}
            )
        result = OperationResult(coordinated.outcome.accepted, coordinated.outcome.reason)
        self._recalculate_and_publish(
            operation=("申请区间改方", result, {"target": target.value}),
            publish_peer_state=False,
        )
        return result

    def handle_direction_message(self, message: DirectionWireMessage) -> OperationResult:
        self._ensure_open()
        before_version = self.runtime.state_version
        try:
            coordinated = self._direction.handle(
                message, self._direction_guard(), now_ms=self._clock_ms()
            )
        except (OSError, ProtocolError, RuntimeError) as exc:
            return self._direction_transport_failure(
                "处理对站改方消息", exc, {"kind": message.kind.value}
            )
        result = OperationResult(coordinated.outcome.accepted, coordinated.outcome.reason)
        if self.runtime.state_version != before_version:
            self._deferred_state_sync = True
        if (
            message.kind is DirectionMessageKind.ACK
            and coordinated.outcome.accepted
            and self._direction_confirmation_sender is not None
        ):
            try:
                recovery = self._direction.machine.export_recovery_record()
                if not self._save_authoritative_direction(recovery=recovery):
                    raise RuntimeError("权威方向恢复证据持久化失败")
                self._pending_recovery = recovery
                self._direction_confirmation_sender(recovery)
            except (OSError, ProtocolError, RuntimeError) as exc:
                return self._direction_transport_failure(
                    "发送权威方向确认", exc, {"kind": message.kind.value}
                )
        self._recalculate_and_publish(
            operation=("处理对站改方消息", result, {"kind": message.kind.value}),
            publish_peer_state=False,
        )
        return result

    def handle_direction_confirmation(
        self, record: DirectionRecoveryRecord
    ) -> OperationResult:
        self._ensure_open()
        before_version = self.runtime.state_version
        coordinated = self._direction.confirm_authority_applied(
            record, self._direction_guard()
        )
        result = OperationResult(coordinated.outcome.accepted, coordinated.outcome.reason)
        if self.runtime.state_version != before_version:
            self._deferred_state_sync = True
        self._recalculate_and_publish(
            operation=("确认权威方向投影", result, {"transaction_id": record.transaction_id}),
            publish_peer_state=False,
        )
        return result

    def restore_authoritative_direction(
        self, authoritative_direction: RunningDirection
    ) -> OperationResult:
        self._ensure_open()
        before_version = self.runtime.state_version
        coordinated = self._direction.restore_from_authority(
            authoritative_direction, self._direction_guard()
        )
        result = OperationResult(coordinated.outcome.accepted, coordinated.outcome.reason)
        if self.runtime.state_version != before_version:
            self._deferred_state_sync = True
        if (
            result.success
            and self.config.station.station_id == "A"
            and self._pending_recovery is not None
            and self._direction_confirmation_sender is not None
        ):
            try:
                self._direction_confirmation_sender(self._pending_recovery)
            except (OSError, ProtocolError, RuntimeError) as exc:
                return self._direction_transport_failure(
                    "重发权威方向恢复证据",
                    exc,
                    {"direction": authoritative_direction.value},
                )
        self._recalculate_and_publish(
            operation=("恢复权威方向同步", result, {"direction": authoritative_direction.value}),
            publish_peer_state=False,
        )
        return result

    def expire_direction_change(self) -> OperationResult | None:
        """由主线程定时器驱动事务超时；无活动事务时不产生日志。"""
        self._ensure_open()
        if not self._direction.machine.has_active_transaction:
            return None
        coordinated = self._direction.expire(now_ms=self._clock_ms())
        result = OperationResult(
            coordinated.outcome.accepted, coordinated.outcome.reason
        )
        if result.success:
            return None
        self._recalculate_and_publish(
            operation=("检查区间改方超时", result, {}),
            publish_peer_state=False,
        )
        return result

    def set_track_state(
        self,
        section_id: str,
        source: TrackInputSource,
        state: TrackState,
    ) -> OperationResult:
        self._ensure_open()
        before_version = self.runtime.state_version
        try:
            change = self.runtime.apply_track_input(section_id, source, state)
        except UnknownTrackSectionError as exc:
            result = OperationResult(False, str(exc))
            self._save_operation(f"设置区段 {section_id}", result, {"state": state.value})
            return result
        result = OperationResult(True, "区段状态已更新" if change.changed else "区段状态未变化")
        if self.runtime.state_version != before_version:
            self._recalculate_and_publish(
                operation=(f"设置区段 {section_id}", result, {"state": state.value})
            )
        else:
            self._save_operation(
                f"设置区段 {section_id}", result, {"state": state.value}
            )
        return result

    def establish_route(self, route_id: str) -> OperationResult:
        return self._route_command(route_id, establish=True)

    def cancel_route(self, route_id: str) -> OperationResult:
        return self._route_command(route_id, establish=False)

    def set_red_lamp_failure(self, signal_id: str, failed: bool) -> OperationResult:
        self._ensure_open()
        known = {item.id for item in self.config.topology.signals}
        if signal_id not in known:
            result = OperationResult(False, f"未知信号机 {signal_id}")
            self._save_operation(f"设置灯丝 {signal_id}", result, {"failed": failed})
            return result
        before = signal_id in self.runtime.failed_red_lamp_ids
        if failed:
            self.runtime.failed_red_lamp_ids.add(signal_id)
        else:
            self.runtime.failed_red_lamp_ids.discard(signal_id)
        result = OperationResult(True, "红灯灯丝故障已设置" if failed else "红灯灯丝故障已清除")
        if before != failed:
            self.runtime.state_version += 1
            self._recalculate_and_publish(
                operation=(f"设置灯丝 {signal_id}", result, {"failed": failed})
            )
        else:
            self._save_operation(f"设置灯丝 {signal_id}", result, {"failed": failed})
        return result

    def update_peer_snapshot(self, snapshot: PeerSnapshot) -> None:
        self._ensure_open()
        self.peer_snapshot = snapshot
        self._peer_snapshot_was_fresh = snapshot.is_fresh(
            self._clock_ms(), self._peer_timeout_ms
        )
        self.alarms.clear_alarm(
            "PEER_SNAPSHOT_STALE", "peer", now_ms=self._clock_ms()
        )
        self._recalculate_and_publish(
            operation=None,
            include_state_stage=False,
            publish_peer_state=False,
        )

    def reevaluate_time_dependent_safety(self) -> bool:
        """在快照从新鲜跨越到过期时只重算一次并立即安全锁闭。"""
        self._ensure_open()
        fresh = (
            self.peer_snapshot is not None
            and self.peer_snapshot.is_fresh(
                self._clock_ms(), self._peer_timeout_ms
            )
        )
        if fresh == self._peer_snapshot_was_fresh:
            return False
        self._peer_snapshot_was_fresh = fresh
        if not fresh:
            self._direction.on_connection_state(ConnectionState.DEGRADED)
            self.alarms.raise_alarm(
                "PEER_SNAPSHOT_STALE",
                AlarmLevel.CRITICAL,
                "对站状态快照已过期，相关行车作业安全锁闭",
                "peer",
                now_ms=self._clock_ms(),
            )
        else:
            self.alarms.clear_alarm(
                "PEER_SNAPSHOT_STALE", "peer", now_ms=self._clock_ms()
            )
        self._recalculate_and_publish(
            operation=None,
            include_state_stage=False,
            publish_peer_state=False,
        )
        return True

    def set_connection_state(self, state: ConnectionState) -> None:
        self._ensure_open()
        self.connection_state = state
        self._direction.on_connection_state(state)
        now = self._clock_ms()
        if state is ConnectionState.HEALTHY:
            self.alarms.clear_alarm("NETWORK_UNHEALTHY", "peer", now_ms=now)
        else:
            self.alarms.raise_alarm(
                "NETWORK_UNHEALTHY",
                AlarmLevel.WARNING,
                f"站间通信状态：{state.value}",
                "peer",
                now_ms=now,
            )
        self._recalculate_and_publish(
            operation=None,
            include_state_stage=False,
            publish_peer_state=False,
        )

    def close(self) -> None:
        if self._closed:
            return
        self.persistence.close()
        self._closed = True

    def _route_command(self, route_id: str, *, establish: bool) -> OperationResult:
        self._ensure_open()
        before_version = self.runtime.state_version
        result = (
            self._routes.establish(route_id, self.runtime)
            if establish
            else self._routes.cancel(route_id, self.runtime)
        )
        verb = "建立" if establish else "取消"
        operation = f"{verb}进路 {route_id}"
        if self.runtime.state_version != before_version:
            self._recalculate_and_publish(
                operation=(operation, result, {"route_id": route_id})
            )
        else:
            self._save_operation(operation, result, {"route_id": route_id})
        return result

    def _recalculate_and_publish(
        self,
        *,
        operation: tuple[str, OperationResult, Mapping[str, Any]] | None,
        include_state_stage: bool = True,
        publish_peer_state: bool = True,
    ) -> TccSnapshot:
        now = self._clock_ms()
        if include_state_stage:
            self._stage_listener("state")
        self._latest_codes = self._coding.recalculate_all(
            self.runtime, self.peer_snapshot, now
        )
        self._stage_listener("coding")
        self._latest_signals = self._signals.recalculate(
            self.runtime, self._latest_codes
        )
        self._stage_listener("signals")
        selection = self._select_telegram(now)
        self._latest_telegram = self._telegram_view(selection)
        self._save_telegram(self._latest_telegram, now)
        self._stage_listener("leu")
        self._update_leu_alarm(selection, now)
        self._stage_listener("alarms")
        state_payload = self._state_payload()
        self._cache_state(state_payload)
        if publish_peer_state and self._direction.machine.has_active_transaction:
            self._deferred_state_sync = True
            publish_peer_state = False
        elif (
            not self._direction.machine.has_active_transaction
            and self._deferred_state_sync
        ):
            # 事务期间的多次变化合并为一次最终同步。ACK/确认已先提交到同一
            # FIFO 网络队列，因此最终快照不会抢在改方协议消息之前到达。
            publish_peer_state = True
            self._deferred_state_sync = False
        if publish_peer_state:
            try:
                self._publish_state(state_payload)
            except (OSError, ProtocolError, RuntimeError) as exc:
                # 本地状态已经提交后若发送失败，不能让异常中断快照和审计；
                # 立即锁闭并重算信号，等待重连全量同步恢复。
                self.connection_state = ConnectionState.DEGRADED
                self._direction.on_connection_state(ConnectionState.DEGRADED)
                self.alarms.raise_alarm(
                    "NETWORK_SEND_FAILURE",
                    AlarmLevel.CRITICAL,
                    f"状态同步发送失败：{exc}",
                    "peer",
                    now_ms=now,
                )
                self._latest_codes = self._coding.recalculate_all(
                    self.runtime, self.peer_snapshot, now
                )
                self._latest_signals = self._signals.recalculate(
                    self.runtime, self._latest_codes
                )
                self._cache_state(self._state_payload())
        self._stage_listener("peer_sync")
        snapshot = self._build_snapshot()
        self.snapshot = snapshot
        for listener in tuple(self._snapshot_listeners):
            listener(snapshot)
        self._stage_listener("ui_snapshot")
        if operation is not None:
            name, result, details = operation
            self._save_operation(name, result, details)
            self._stage_listener("operation_log")
        return snapshot

    def _select_telegram(self, now_ms: int) -> TelegramSelectionResult:
        station = self.config.station.station_id
        port_id = f"LEU_{station}_1"
        active_tsr = next(
            (
                item
                for item in self._temporary_speeds.items
                if item.state is TemporarySpeedState.ACTIVE
            ),
            None,
        )
        if active_tsr is not None:
            selected = f"TG_{station}_TSR"
            overrides = {
                "CTCS-2": {
                    "tsr_id": active_tsr.tsr_id,
                    "start_m": active_tsr.start_m,
                    "end_m": active_tsr.end_m,
                    "speed_kmh": active_tsr.speed_kmh,
                }
            }
        else:
            selected = f"TG_{station}_ROUTE" if self.runtime.active_route_ids else None
            overrides = {}
        return self._leu.select_for_port(
            port_id,
            LeuContext(
                connected=self._leu_connected,
                input_updated_ms=now_ms,
                state_version=self.runtime.state_version,
                selected_template_id=selected,
                overrides=overrides,
            ),
            now_ms,
        )

    def _telegram_view(self, selection: TelegramSelectionResult) -> TelegramView:
        telegram = selection.telegram
        envelope = SimulationEnvelopeCodec.encode(telegram)
        logical = json.loads(envelope.canonical_json)
        return TelegramView(
            port_id=f"LEU_{self.config.station.station_id}_1",
            mode=selection.mode,
            reason=selection.reason,
            template_id=telegram.template_id,
            balise_id=telegram.balise_id,
            logical_payload=logical,
            teaching_bit_view=" ".join(
                f"{int(envelope.hex_payload[index:index + 2], 16):08b}"
                for index in range(0, len(envelope.hex_payload), 2)
            ),
            simulation_format=envelope.format,
            simulation_hex=envelope.hex_payload,
            crc32=envelope.crc32,
        )

    def _update_leu_alarm(self, selection: TelegramSelectionResult, now_ms: int) -> None:
        if selection.alarm_level is None:
            self.alarms.clear_alarm("LEU_DEFAULT", selection.telegram.balise_id, now_ms=now_ms)
            return
        level = AlarmLevel(selection.alarm_level)
        self.alarms.raise_alarm(
            "LEU_DEFAULT",
            level,
            selection.reason,
            selection.telegram.balise_id,
            now_ms=now_ms,
        )

    def _build_snapshot(self) -> TccSnapshot:
        if self._latest_telegram is None:
            raise RuntimeError("内部错误：尚未生成 LEU 报文")
        return TccSnapshot(
            station_id=self.config.station.station_id,
            station_name=self.config.station.station_name,
            state_version=self.runtime.state_version,
            running_direction=self.runtime.running_direction.value,
            direction_operation_locked=self.runtime.direction_operation_locked,
            connection_state=self.connection_state,
            tracks={
                item.id: self.runtime.effective_track_state(item.id)
                for item in self.config.topology.sections
            },
            codes={item.section_id: item for item in self._latest_codes},
            signals={item.signal_id: item for item in self._latest_signals},
            active_route_ids=tuple(sorted(self.runtime.active_route_ids)),
            temporary_speeds=self._temporary_speeds.items,
            telegram=self._latest_telegram,
            alarms=self.alarms.active_alarms(),
            operation_logs=tuple(reversed(self._operation_logs[-200:])),
            network_received=self._network_received,
            network_sent=self._network_sent,
        )

    def _state_payload(self) -> Mapping[str, Any]:
        return {
            "state_version": self.runtime.state_version,
            "running_direction": self.runtime.running_direction.value,
            "direction_operation_locked": self.runtime.direction_operation_locked,
            "boundary_states": {
                section.id: self.runtime.effective_track_state(section.id).value
                for section in self.config.topology.sections
                if section.id.startswith("Q")
            },
        }

    def _save_operation(
        self,
        operation: str,
        result: OperationResult,
        details: Mapping[str, Any],
    ) -> None:
        entry = OperationLogEntry(
            self.config.station.station_id,
            self._clock_ms(),
            operation,
            result.success,
            result.reason,
            self.runtime.state_version,
            details,
        )
        self._operation_logs.append(entry)
        self.persistence.save_operation(entry)
        # 规定的业务流水在 operation_log 阶段完成；日志写入后再发一份纯展示
        # 快照，使界面立即看到本次操作，但不重新编码、不发布网络状态。
        if self._latest_telegram is not None and hasattr(self, "snapshot"):
            self._refresh_snapshot_only()

    def _save_telegram(self, view: TelegramView, now_ms: int) -> None:
        self.persistence.save_telegram(
            TelegramHistoryEntry(
                self.config.station.station_id,
                now_ms,
                view.balise_id,
                view.template_id,
                view.mode.value,
                view.logical_payload,
                view.simulation_hex,
                view.crc32,
            )
        )

    def _direction_guard(self):  # type: ignore[no-untyped-def]
        block_states = {
            item.id: self.runtime.effective_track_state(item.id)
            for item in self.config.topology.sections
            if item.id.startswith("Q")
        }
        peer_version = self.peer_snapshot.state_version if self.peer_snapshot else 0
        peer_fresh = (
            self.peer_snapshot is not None
            and self.peer_snapshot.is_fresh(self._clock_ms(), self._peer_timeout_ms)
        )
        return self._direction.build_guard(
            connection_state=self.connection_state,
            peer_snapshot_fresh=peer_fresh,
            required_section_ids=frozenset(block_states),
            section_states=block_states,
            peer_state_version=peer_version,
        )

    def _send_direction(self, message: DirectionWireMessage) -> None:
        if self._direction_sender is None:
            raise RuntimeError("改方网络协调器尚未装配")
        self._direction_sender(message)

    def _persist_authority_before_direction_apply(
        self, target_direction: RunningDirection
    ) -> None:
        """A 在内存 APPLY 和发送 COMMIT 前先落盘目标权威方向。"""
        if (
            self.config.station.station_id == "A"
            and target_direction is not self._persisted_authoritative_direction
            and not self._save_authoritative_direction(
                recovery=None,
                direction=target_direction,
                state_version=self.runtime.state_version + 1,
            )
        ):
            raise RuntimeError("权威方向持久化失败，已禁止发送改方提交")

    def _save_authoritative_direction(
        self,
        *,
        recovery: DirectionRecoveryRecord | None,
        direction: RunningDirection | None = None,
        state_version: int | None = None,
    ) -> bool:
        if self.config.station.station_id != "A":
            return True
        recovery_payload = None
        if recovery is not None:
            recovery_payload = {
                "transaction_id": recovery.transaction_id,
                "requester_station_id": recovery.requester_station_id,
                "responder_station_id": recovery.responder_station_id,
                "original_direction": recovery.original_direction.value,
                "target_direction": recovery.target_direction.value,
                "requester_state_version": recovery.requester_state_version,
                "responder_state_version": recovery.responder_state_version,
                "requester_applied": recovery.requester_applied,
            }
        saved_direction = direction or self.runtime.running_direction
        saved_version = (
            self.runtime.state_version if state_version is None else state_version
        )
        saved = self.persistence.save_direction_authority(
            DirectionAuthorityEntry(
                station_id="A",
                direction=saved_direction,
                updated_at_ms=self._clock_ms(),
                state_version=saved_version,
                recovery=recovery_payload,
            )
        )
        if saved:
            self._persisted_authoritative_direction = saved_direction
        return saved

    @staticmethod
    def _parse_recovery_record(
        payload: Mapping[str, Any]
    ) -> DirectionRecoveryRecord:
        """严格恢复 A 站证据；损坏数据必须阻止启动而不能静默忽略。"""
        try:
            return DirectionRecoveryRecord(
                transaction_id=str(payload["transaction_id"]),
                requester_station_id=str(payload["requester_station_id"]),
                responder_station_id=str(payload["responder_station_id"]),
                original_direction=RunningDirection(payload["original_direction"]),
                target_direction=RunningDirection(payload["target_direction"]),
                requester_state_version=int(payload["requester_state_version"]),
                responder_state_version=(
                    None
                    if payload["responder_state_version"] is None
                    else int(payload["responder_state_version"])
                ),
                requester_applied=payload["requester_applied"] is True,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"权威方向恢复证据损坏：{exc}") from exc

    def _direction_transport_failure(
        self,
        operation: str,
        error: Exception,
        details: Mapping[str, Any],
    ) -> OperationResult:
        """把同步网络提交失败转换成可见拒绝，并立即维持安全锁闭。"""
        self.connection_state = ConnectionState.DEGRADED
        self._direction.on_connection_state(ConnectionState.DEGRADED)
        now = self._clock_ms()
        self.alarms.raise_alarm(
            "DIRECTION_TRANSPORT_FAILURE",
            AlarmLevel.CRITICAL,
            f"改方消息发送失败：{error}",
            "peer",
            now_ms=now,
        )
        result = OperationResult(False, f"改方消息发送失败：{error}")
        self._recalculate_and_publish(
            operation=(operation, result, details),
            publish_peer_state=False,
        )
        return result

    def _refresh_snapshot_only(self) -> None:
        """仅重建不可变展示快照，避免指标/日志刷新形成同步回环。"""
        snapshot = self._build_snapshot()
        self.snapshot = snapshot
        for listener in tuple(self._snapshot_listeners):
            listener(snapshot)

    def _change_temporary_speed(
        self, tsr_id: str, *, activate: bool
    ) -> OperationResult:
        self._ensure_open()
        try:
            if activate:
                self._temporary_speeds.activate(tsr_id, self._clock_ms())
                verb = "执行"
            else:
                self._temporary_speeds.cancel(tsr_id)
                verb = "撤销"
        except ValueError as exc:
            result = OperationResult(False, str(exc))
            self._save_operation(f"变更临时限速 {tsr_id}", result, {})
            return result
        self.runtime.state_version += 1
        result = OperationResult(True, f"临时限速已{verb}")
        self._recalculate_and_publish(
            operation=(f"{verb}临时限速 {tsr_id}", result, {"tsr_id": tsr_id})
        )
        return result

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("TccController 已关闭")
