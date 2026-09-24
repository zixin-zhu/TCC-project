"""站间仿真协议的规范字段、CRC 与输入校验测试。"""

import json

import pytest
from hypothesis import given, settings, strategies as st

from app.core.exceptions import ProtocolError
from app.network.protocol import MessageType, ProtocolCodec, ProtocolMessage


def _codec() -> ProtocolCodec:
    return ProtocolCodec(local_station_id="A", peer_station_id="B")


def _message(**overrides: object) -> ProtocolMessage:
    values: dict[str, object] = {
        "magic": "TCCSIM",
        "version": 1,
        "message_type": MessageType.HEARTBEAT,
        "message_id": "msg-001",
        "sequence": 7,
        "station_id": "A",
        "peer_station_id": "B",
        "timestamp_ms": 1_700_000_000_000,
        "state_version": 3,
        "payload": {"connection_state": "HEALTHY"},
    }
    values.update(overrides)
    return ProtocolMessage(**values)  # type: ignore[arg-type]


json_scalars = st.one_of(
    st.none(), st.booleans(), st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.text(max_size=40),
)
json_values = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=8),
        st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=8),
    ),
    max_leaves=20,
)


@given(json_values)
@settings(max_examples=100)
def test_protocol_roundtrip_preserves_json_payload(payload: object) -> None:
    """合法 JSON 载荷应在规范编码、CRC 校验和解码后保持等价。"""
    codec = _codec()
    message = _message(payload=payload)

    assert codec.decode(codec.encode(message)) == message


def test_encoded_protocol_contains_all_required_fields_and_crc() -> None:
    encoded = _codec().encode(_message())
    document = json.loads(encoded.decode("utf-8"))

    assert set(document) == {
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
        "crc32",
    }
    assert isinstance(document["crc32"], str)
    assert len(document["crc32"]) == 8


@pytest.mark.parametrize("raw", [b"\xff", b"{broken", b"[]", b"{}"])
def test_decode_rejects_bad_utf8_json_or_missing_fields(raw: bytes) -> None:
    with pytest.raises(ProtocolError):
        _codec().decode(raw)


def test_decode_rejects_crc_tampering() -> None:
    document = json.loads(_codec().encode(_message()).decode("utf-8"))
    document["payload"]["connection_state"] = "DISCONNECTED"
    tampered = json.dumps(document, ensure_ascii=False).encode("utf-8")

    with pytest.raises(ProtocolError, match="CRC"):
        _codec().decode(tampered)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("magic", "OTHER", "magic"),
        ("version", 2, "版本"),
        ("station_id", "C", "发送站"),
        ("peer_station_id", "C", "接收站"),
        ("sequence", -1, "sequence"),
        ("timestamp_ms", -1, "时间戳"),
        ("state_version", -1, "状态版本"),
    ],
)
def test_encode_rejects_invalid_header_fields(
    field: str, value: object, reason: str
) -> None:
    with pytest.raises(ProtocolError, match=reason):
        _codec().encode(_message(**{field: value}))


def test_decode_rejects_unknown_message_type_even_with_recomputed_crc() -> None:
    codec = _codec()
    valid = json.loads(codec.encode(_message()).decode("utf-8"))
    valid["message_type"] = "UNKNOWN"

    with pytest.raises(ProtocolError, match="消息类型"):
        codec.encode_document(valid)

