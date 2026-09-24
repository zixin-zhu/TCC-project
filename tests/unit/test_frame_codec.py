"""TCP 长度帧的单元测试与属性测试。"""

import struct

import pytest
from hypothesis import example, given, settings, strategies as st

from app.core.exceptions import FrameError
from app.network.frame_codec import MAX_FRAME_SIZE, FrameDecoder, encode_frame


@given(st.binary(min_size=1, max_size=2048))
@example(b"x")
@example(b"\x00\xff\x01")
@settings(max_examples=100)
def test_frame_roundtrip_for_arbitrary_binary_payload(payload: bytes) -> None:
    """任意允许的二进制正文经封装和解析后必须原样还原。"""
    decoder = FrameDecoder()

    assert decoder.feed(encode_frame(payload)) == [payload]
    assert decoder.buffered_bytes == 0


@given(
    st.lists(st.binary(min_size=1, max_size=128), min_size=1, max_size=20),
    st.lists(st.integers(min_value=1, max_value=31), min_size=1, max_size=30),
)
@settings(max_examples=80)
def test_decoder_preserves_messages_across_arbitrary_chunks(
    payloads: list[bytes], chunk_sizes: list[int]
) -> None:
    """拆包和粘包只能影响到达方式，不能改变消息边界与顺序。"""
    stream = b"".join(encode_frame(payload) for payload in payloads)
    decoder = FrameDecoder()
    decoded: list[bytes] = []
    cursor = 0
    size_index = 0
    while cursor < len(stream):
        size = chunk_sizes[size_index % len(chunk_sizes)]
        decoded.extend(decoder.feed(stream[cursor : cursor + size]))
        cursor += size
        size_index += 1

    assert decoded == payloads
    assert decoder.buffered_bytes == 0


@pytest.mark.parametrize("payload", [b"", b"x" * (MAX_FRAME_SIZE + 1)])
def test_encoder_rejects_zero_or_oversized_payload(payload: bytes) -> None:
    with pytest.raises(FrameError):
        encode_frame(payload)


@pytest.mark.parametrize("declared_length", [0, MAX_FRAME_SIZE + 1])
def test_decoder_rejects_invalid_declared_length(declared_length: int) -> None:
    decoder = FrameDecoder()

    with pytest.raises(FrameError):
        decoder.feed(struct.pack(">I", declared_length))


def test_decoder_waits_for_complete_header_and_body() -> None:
    frame = encode_frame(b"abcdef")
    decoder = FrameDecoder()

    assert decoder.feed(frame[:2]) == []
    assert decoder.feed(frame[2:7]) == []
    assert decoder.feed(frame[7:]) == [b"abcdef"]

