"""TCC 双站课程仿真的规范 JSON 协议。

CRC32 只用于发现传输或演示中的意外损坏，不具备认证和抗攻击能力，不能
称为铁路安全通信机制。安全相关状态必须由后续业务状态机再次保护。
"""

from __future__ import annotations

import json
import time
import zlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from app.core.enums import ConnectionState
from app.core.exceptions import ProtocolError

PROTOCOL_MAGIC = "TCCSIM"
PROTOCOL_VERSION = 1


class MessageType(str, Enum):
    HELLO = "HELLO"
    ACK = "ACK"
    HEARTBEAT = "HEARTBEAT"
    STATE_SYNC = "STATE_SYNC"
    TRACK_BOUNDARY = "TRACK_BOUNDARY"
    SIGNAL_STATUS = "SIGNAL_STATUS"
    DIRECTION_PREPARE = "DIRECTION_PREPARE"
    DIRECTION_READY = "DIRECTION_READY"
    DIRECTION_COMMIT = "DIRECTION_COMMIT"
    DIRECTION_COMMITTED = "DIRECTION_COMMITTED"
    ALARM_SUMMARY = "ALARM_SUMMARY"
    ERROR = "ERROR"


class SessionAction(str, Enum):
    """接收一条消息后，连接层需要执行的附加动作。"""

    NONE = "NONE"
    SEND_ACK = "SEND_ACK"


@dataclass(frozen=True)
class ProtocolMessage:
    """一条已通过结构校验的站间消息。"""

    magic: str
    version: int
    message_type: MessageType
    message_id: str
    sequence: int
    station_id: str
    peer_station_id: str
    timestamp_ms: int
    state_version: int
    payload: Any


@dataclass(frozen=True)
class SessionDecision:
    accepted: bool
    reason: str
    action: SessionAction = SessionAction.NONE


_BODY_FIELDS = (
    "magic",
    "version",
    "message_type",
    "message_id",
    "sequence",
    "station_id",
    "peer_station_id",
    "timestamp_ms",
    "state_version",
    "payload",
)
_ALL_FIELDS = frozenset((*_BODY_FIELDS, "crc32"))


def _canonical_json(document: Mapping[str, Any]) -> bytes:
    try:
        rendered = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"载荷不是合法 JSON 数据：{exc}") from exc
    return rendered.encode("utf-8")


def _crc32_hex(body: Mapping[str, Any]) -> str:
    return f"{zlib.crc32(_canonical_json(body)) & 0xFFFFFFFF:08X}"


class ProtocolCodec:
    """编码并校验一个固定发送站到固定接收站方向的消息。"""

    def __init__(
        self,
        *,
        local_station_id: str,
        peer_station_id: str,
        version: int = PROTOCOL_VERSION,
    ) -> None:
        self.local_station_id = local_station_id
        self.peer_station_id = peer_station_id
        self.version = version

    def encode(self, message: ProtocolMessage) -> bytes:
        body = self._message_to_body(message)
        return self._encode_body(body)

    def encode_document(self, document: Mapping[str, Any]) -> bytes:
        """校验结构化文档并编码，主要供协议网关和诊断工具使用。"""
        body = {field: document.get(field) for field in _BODY_FIELDS}
        message = self._body_to_message(body)
        return self.encode(message)

    def decode(self, encoded: bytes) -> ProtocolMessage:
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("协议正文不是 UTF-8") from exc
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProtocolError("协议正文不是合法 JSON") from exc
        if not isinstance(document, dict):
            raise ProtocolError("协议正文必须是 JSON 对象")
        if set(document) != _ALL_FIELDS:
            missing = sorted(_ALL_FIELDS - set(document))
            unknown = sorted(set(document) - _ALL_FIELDS)
            raise ProtocolError(f"协议字段不完整或未知：missing={missing}, unknown={unknown}")

        body = {field: document[field] for field in _BODY_FIELDS}
        crc32 = document["crc32"]
        if not isinstance(crc32, str) or crc32.upper() != _crc32_hex(body):
            raise ProtocolError("CRC32 校验失败")
        return self._body_to_message(body)

    def _encode_body(self, body: Mapping[str, Any]) -> bytes:
        document = dict(body)
        document["crc32"] = _crc32_hex(body)
        return _canonical_json(document)

    def _message_to_body(self, message: ProtocolMessage) -> dict[str, Any]:
        raw_type: object = message.message_type
        try:
            message_type = MessageType(raw_type)
        except (ValueError, TypeError) as exc:
            raise ProtocolError(f"未知消息类型：{raw_type}") from exc
        body: dict[str, Any] = {
            "magic": message.magic,
            "version": message.version,
            "message_type": message_type.value,
            "message_id": message.message_id,
            "sequence": message.sequence,
            "station_id": message.station_id,
            "peer_station_id": message.peer_station_id,
            "timestamp_ms": message.timestamp_ms,
            "state_version": message.state_version,
            "payload": message.payload,
        }
        self._validate_body(body)
        _canonical_json(body)
        return body

    def _body_to_message(self, body: Mapping[str, Any]) -> ProtocolMessage:
        self._validate_body(body)
        try:
            message_type = MessageType(body["message_type"])
        except (ValueError, TypeError) as exc:
            raise ProtocolError(f"未知消息类型：{body.get('message_type')}") from exc
        return ProtocolMessage(
            magic=body["magic"],
            version=body["version"],
            message_type=message_type,
            message_id=body["message_id"],
            sequence=body["sequence"],
            station_id=body["station_id"],
            peer_station_id=body["peer_station_id"],
            timestamp_ms=body["timestamp_ms"],
            state_version=body["state_version"],
            payload=body["payload"],
        )

    def _validate_body(self, body: Mapping[str, Any]) -> None:
        if any(field not in body for field in _BODY_FIELDS):
            raise ProtocolError("协议字段不完整")
        if body["magic"] != PROTOCOL_MAGIC:
            raise ProtocolError("magic 不匹配")
        if body["version"] != self.version:
            raise ProtocolError(f"协议版本不匹配：{body['version']}")
        if body["station_id"] != self.local_station_id:
            raise ProtocolError(f"发送站不匹配：{body['station_id']}")
        if body["peer_station_id"] != self.peer_station_id:
            raise ProtocolError(f"接收站不匹配：{body['peer_station_id']}")
        if not isinstance(body["message_id"], str) or not body["message_id"]:
            raise ProtocolError("message_id 必须为非空字符串")
        self._validate_non_negative_int("sequence", body["sequence"], "sequence")
        self._validate_non_negative_int("timestamp_ms", body["timestamp_ms"], "时间戳")
        self._validate_non_negative_int("state_version", body["state_version"], "状态版本")
        try:
            MessageType(body["message_type"])
        except (ValueError, TypeError) as exc:
            raise ProtocolError(f"未知消息类型：{body['message_type']}") from exc

    @staticmethod
    def _validate_non_negative_int(name: str, value: object, label: str) -> None:
        if type(value) is not int or value < 0:
            raise ProtocolError(f"{label}必须是非负整数（{name}={value!r}）")


_HANDSHAKE_TYPES = frozenset({MessageType.HELLO, MessageType.ACK, MessageType.ERROR})
_PRE_BASELINE_TYPES = frozenset(
    {
        MessageType.HELLO,
        MessageType.ACK,
        MessageType.HEARTBEAT,
        MessageType.STATE_SYNC,
        MessageType.ERROR,
    }
)


class PeerProtocolSession:
    """管理单次 TCP 会话的协议门禁与活性状态。

    会话对象不持有 socket。连接层负责传输，本类只决定消息能否进入业务层，
    因而握手、重放保护和重连基线可以进行确定性单元测试。
    """

    def __init__(self, *, local_station_id: str, peer_station_id: str) -> None:
        self.local_station_id = local_station_id
        self.peer_station_id = peer_station_id
        self.connection_state = ConnectionState.DISCONNECTED
        self.requires_full_sync = True
        self._outgoing_sequence = 0
        self._last_peer_sequence = -1
        self._seen_message_ids: set[str] = set()
        self._received_peer_hello = False
        self._received_peer_ack = False
        self._last_peer_message_at_ms: int | None = None

    def on_transport_connected(self, *, now_ms: int | None = None) -> ProtocolMessage:
        """开始一次全新会话，并生成必须首先发送的 HELLO。"""
        self.connection_state = ConnectionState.HANDSHAKING
        self.requires_full_sync = True
        self._outgoing_sequence = 0
        self._last_peer_sequence = -1
        self._seen_message_ids.clear()
        self._received_peer_hello = False
        self._received_peer_ack = False
        self._last_peer_message_at_ms = now_ms
        return self.make_message(MessageType.HELLO, {}, now_ms=now_ms)

    def on_transport_disconnected(self) -> None:
        self.connection_state = ConnectionState.DISCONNECTED
        self.requires_full_sync = True

    def make_message(
        self,
        message_type: MessageType,
        payload: Any,
        *,
        state_version: int = 0,
        now_ms: int | None = None,
    ) -> ProtocolMessage:
        """生成本站到对站的严格递增序号消息。"""
        self._outgoing_sequence += 1
        timestamp_ms = int(time.time() * 1000) if now_ms is None else now_ms
        return ProtocolMessage(
            magic=PROTOCOL_MAGIC,
            version=PROTOCOL_VERSION,
            message_type=message_type,
            message_id=f"{self.local_station_id}-{timestamp_ms}-{self._outgoing_sequence}",
            sequence=self._outgoing_sequence,
            station_id=self.local_station_id,
            peer_station_id=self.peer_station_id,
            timestamp_ms=timestamp_ms,
            state_version=state_version,
            payload=payload,
        )

    def accept(
        self,
        message: ProtocolMessage,
        *,
        received_at_ms: int | None = None,
        semantic_validator: Callable[[ProtocolMessage], None] | None = None,
    ) -> SessionDecision:
        """验证重放/时序和会话阶段；拒绝结果不得送入业务控制器。"""
        header_error = self._validate_peer_header(message)
        if header_error:
            return SessionDecision(False, header_error)
        if message.message_id in self._seen_message_ids:
            return SessionDecision(False, f"重复消息 ID：{message.message_id}")
        if message.sequence <= self._last_peer_sequence:
            return SessionDecision(False, f"消息序号未递增：{message.sequence}")

        if self.connection_state is ConnectionState.HANDSHAKING:
            if message.message_type not in _HANDSHAKE_TYPES:
                return SessionDecision(False, "握手完成前拒绝业务消息")
        elif self.connection_state not in {
            ConnectionState.HEALTHY,
            ConnectionState.DEGRADED,
        }:
            return SessionDecision(False, "连接尚未建立")
        elif self.requires_full_sync and message.message_type not in _PRE_BASELINE_TYPES:
            return SessionDecision(False, "重连后尚未收到全量同步基线")

        if semantic_validator is not None:
            try:
                semantic_validator(message)
            except ProtocolError as exc:
                return SessionDecision(False, f"业务语义校验失败：{exc}")

        # 只有完整通过会话阶段与业务语义校验的消息，才可刷新重放和活性状态。
        self._seen_message_ids.add(message.message_id)
        self._last_peer_sequence = message.sequence
        self._last_peer_message_at_ms = (
            message.timestamp_ms if received_at_ms is None else received_at_ms
        )

        if self.connection_state is ConnectionState.HANDSHAKING:
            if message.message_type is MessageType.HELLO:
                self._received_peer_hello = True
                return SessionDecision(True, "收到对站 HELLO", SessionAction.SEND_ACK)
            if message.message_type is MessageType.ACK:
                self._received_peer_ack = True
                if self._received_peer_hello:
                    self.connection_state = ConnectionState.HEALTHY
                return SessionDecision(True, "收到对站 ACK")
            return SessionDecision(True, "收到握手错误消息")

        if message.message_type is MessageType.STATE_SYNC:
            self.requires_full_sync = False
        if self.connection_state is ConnectionState.DEGRADED:
            self.connection_state = ConnectionState.HEALTHY
        return SessionDecision(True, "消息通过会话校验")

    def evaluate_liveness(
        self,
        *,
        now_ms: int,
        degraded_after_ms: int,
        disconnect_after_ms: int,
    ) -> ConnectionState:
        """根据最后一次有效对站消息时间执行可配置的保护降级。"""
        if degraded_after_ms <= 0 or disconnect_after_ms <= degraded_after_ms:
            raise ValueError("超时阈值必须满足 0 < degraded < disconnect")
        if self._last_peer_message_at_ms is None:
            return self.connection_state
        silence_ms = now_ms - self._last_peer_message_at_ms
        if silence_ms >= disconnect_after_ms:
            self.connection_state = ConnectionState.DISCONNECTED
            self.requires_full_sync = True
        elif silence_ms >= degraded_after_ms and self.connection_state is ConnectionState.HEALTHY:
            self.connection_state = ConnectionState.DEGRADED
        return self.connection_state

    def _validate_peer_header(self, message: ProtocolMessage) -> str | None:
        if message.magic != PROTOCOL_MAGIC or message.version != PROTOCOL_VERSION:
            return "对站协议标识或版本不匹配"
        if message.station_id != self.peer_station_id:
            return f"对站标识不匹配：{message.station_id}"
        if message.peer_station_id != self.local_station_id:
            return f"消息目标站不匹配：{message.peer_station_id}"
        return None
