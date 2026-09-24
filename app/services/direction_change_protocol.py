"""改方领域消息与阶段 4 站间协议消息之间的严格适配。"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from app.core.enums import RunningDirection
from app.core.exceptions import ProtocolError
from app.domain.direction_change import (
    DirectionMessageKind,
    DirectionRecoveryRecord,
    DirectionRejectCode,
    DirectionWireMessage,
)
from app.network.protocol import MessageType, PeerProtocolSession, ProtocolMessage


_TO_PROTOCOL = {
    DirectionMessageKind.PREPARE: MessageType.DIRECTION_PREPARE,
    DirectionMessageKind.APPROVE: MessageType.DIRECTION_READY,
    DirectionMessageKind.COMMIT: MessageType.DIRECTION_COMMIT,
    DirectionMessageKind.ACK: MessageType.DIRECTION_COMMITTED,
    DirectionMessageKind.REJECT: MessageType.ERROR,
}
_FROM_PROTOCOL = {value: key for key, value in _TO_PROTOCOL.items()}


class DirectionProtocolAdapter:
    """保持领域状态机纯净，同时复用规范 JSON、CRC 和站点校验。"""

    @staticmethod
    def to_protocol_message(
        message: DirectionWireMessage,
        *,
        session: PeerProtocolSession,
        now_ms: int,
    ) -> ProtocolMessage:
        _validate_uuid(message.transaction_id)
        _validate_roles(message)
        if (
            session.local_station_id != message.source_station_id
            or session.peer_station_id != message.target_station_id
        ):
            raise ProtocolError("改方消息方向与协议会话站点不一致")
        payload = {
            "kind": message.kind.value,
            "transaction_id": message.transaction_id,
            "requester_station_id": message.requester_station_id,
            "responder_station_id": message.responder_station_id,
            "original_direction": message.original_direction.value,
            "target_direction": message.target_direction.value,
            "requester_state_version": message.requester_state_version,
            "expected_responder_state_version": message.expected_responder_state_version,
            "responder_state_version": message.responder_state_version,
            "deadline_ms": message.deadline_ms,
            "reject_code": (
                message.reject_code.value if message.reject_code is not None else None
            ),
            "reason": message.reason,
        }
        sender_version = _sender_state_version(message)
        if sender_version is None:
            raise ProtocolError("响应方消息缺少 responder_state_version")
        return session.make_message(
            _TO_PROTOCOL[message.kind],
            payload,
            state_version=sender_version,
            now_ms=now_ms,
        )

    @staticmethod
    def from_protocol_message(message: ProtocolMessage) -> DirectionWireMessage:
        expected_kind = _FROM_PROTOCOL.get(message.message_type)
        if expected_kind is None:
            raise ProtocolError(f"消息类型不是改方消息：{message.message_type.value}")
        if not isinstance(message.payload, Mapping):
            raise ProtocolError("改方 payload 必须是对象")
        payload = message.payload
        try:
            kind = DirectionMessageKind(payload["kind"])
            reject_raw = payload.get("reject_code")
            reject_code = (
                None if reject_raw is None else DirectionRejectCode(reject_raw)
            )
            wire = DirectionWireMessage(
                kind=kind,
                transaction_id=_text(payload, "transaction_id"),
                requester_station_id=_text(payload, "requester_station_id"),
                responder_station_id=_text(payload, "responder_station_id"),
                source_station_id=message.station_id,
                target_station_id=message.peer_station_id,
                original_direction=RunningDirection(payload["original_direction"]),
                target_direction=RunningDirection(payload["target_direction"]),
                requester_state_version=_non_negative_int(
                    payload, "requester_state_version"
                ),
                expected_responder_state_version=_non_negative_int(
                    payload, "expected_responder_state_version"
                ),
                responder_state_version=_optional_non_negative_int(
                    payload, "responder_state_version"
                ),
                deadline_ms=_non_negative_int(payload, "deadline_ms"),
                reject_code=reject_code,
                reason=str(payload.get("reason", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError(f"改方 payload 字段非法：{exc}") from exc
        if kind is not expected_kind:
            raise ProtocolError(
                f"外层消息类型与改方 kind 不一致：{message.message_type.value}/{kind.value}"
            )
        _validate_uuid(wire.transaction_id)
        _validate_roles(wire)
        if {
            message.station_id,
            message.peer_station_id,
        } != {wire.requester_station_id, wire.responder_station_id}:
            raise ProtocolError("改方事务站点与协议包络站点不一致")
        expected_sender_version = _sender_state_version(wire)
        if expected_sender_version != message.state_version:
            raise ProtocolError("改方发送方状态版本与协议包络不一致")
        return wire

    @staticmethod
    def to_recovery_protocol_message(
        record: DirectionRecoveryRecord,
        *,
        session: PeerProtocolSession,
        now_ms: int,
    ) -> ProtocolMessage:
        """发送“申请方状态机已处理 ACK 并 APPLY”的应用层确认。"""
        _validate_uuid(record.transaction_id)
        if not record.requester_applied:
            raise ProtocolError("申请方尚未 APPLY，不能生成改方确认")
        if (
            session.local_station_id != record.requester_station_id
            or session.peer_station_id != record.responder_station_id
        ):
            raise ProtocolError("改方确认必须由申请站发往响应站")
        payload = {
            "transaction_id": record.transaction_id,
            "requester_station_id": record.requester_station_id,
            "responder_station_id": record.responder_station_id,
            "original_direction": record.original_direction.value,
            "target_direction": record.target_direction.value,
            "requester_state_version": record.requester_state_version,
            "responder_state_version": record.responder_state_version,
            "requester_applied": True,
        }
        return session.make_message(
            MessageType.DIRECTION_CONFIRM,
            payload,
            state_version=record.requester_state_version,
            now_ms=now_ms,
        )

    @staticmethod
    def from_recovery_protocol_message(
        message: ProtocolMessage,
    ) -> DirectionRecoveryRecord:
        if message.message_type is not MessageType.DIRECTION_CONFIRM:
            raise ProtocolError("消息类型不是改方应用确认")
        if not isinstance(message.payload, Mapping):
            raise ProtocolError("改方确认 payload 必须是对象")
        payload = message.payload
        try:
            record = DirectionRecoveryRecord(
                transaction_id=_text(payload, "transaction_id"),
                requester_station_id=_text(payload, "requester_station_id"),
                responder_station_id=_text(payload, "responder_station_id"),
                original_direction=RunningDirection(payload["original_direction"]),
                target_direction=RunningDirection(payload["target_direction"]),
                requester_state_version=_non_negative_int(
                    payload, "requester_state_version"
                ),
                responder_state_version=_optional_non_negative_int(
                    payload, "responder_state_version"
                ),
                requester_applied=payload["requester_applied"] is True,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError(f"改方确认字段非法：{exc}") from exc
        _validate_uuid(record.transaction_id)
        if not record.requester_applied:
            raise ProtocolError("改方确认缺少 requester_applied=true")
        if (
            message.station_id != record.requester_station_id
            or message.peer_station_id != record.responder_station_id
        ):
            raise ProtocolError("改方确认包络站点与事务角色不一致")
        if message.state_version != record.requester_state_version:
            raise ProtocolError("改方确认状态版本与包络不一致")
        return record


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{key} 必须是非空字符串")
    return value


def _non_negative_int(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if type(value) is not int or value < 0:
        raise ProtocolError(f"{key} 必须是非负整数")
    return value


def _optional_non_negative_int(
    payload: Mapping[str, object], key: str
) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ProtocolError(f"{key} 必须是非负整数或 null")
    return value


def _validate_uuid(value: str) -> None:
    try:
        UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProtocolError("transaction_id 必须是 UUID") from exc


def _validate_roles(message: DirectionWireMessage) -> None:
    if (
        not message.requester_station_id
        or not message.responder_station_id
        or message.requester_station_id == message.responder_station_id
    ):
        raise ProtocolError("改方申请站与响应站必须是两个不同站点")
    if message.kind in {DirectionMessageKind.PREPARE, DirectionMessageKind.COMMIT}:
        expected_source = message.requester_station_id
        expected_target = message.responder_station_id
    elif message.kind in {DirectionMessageKind.APPROVE, DirectionMessageKind.ACK}:
        expected_source = message.responder_station_id
        expected_target = message.requester_station_id
    else:
        if {
            message.source_station_id,
            message.target_station_id,
        } != {message.requester_station_id, message.responder_station_id}:
            raise ProtocolError("REJECT 发送角色不属于当前改方事务")
        return
    if (
        message.source_station_id != expected_source
        or message.target_station_id != expected_target
    ):
        raise ProtocolError(f"{message.kind.value} 的发送角色不合法")


def _sender_state_version(message: DirectionWireMessage) -> int | None:
    if message.source_station_id == message.requester_station_id:
        return message.requester_state_version
    if message.responder_state_version is not None:
        return message.responder_state_version
    if message.kind is DirectionMessageKind.REJECT:
        # PREPARE 守卫校验前的拒绝尚未建立响应方预留，只能回显事务中
        # 声明的预期响应方版本；接收方仍会用自己的事务上下文复核。
        return message.expected_responder_state_version
    return None
