"""基于 4 字节大端长度的 TCP 消息分帧。

TCP 只提供字节流，不保留发送时的消息边界。本模块把分帧写成无 I/O 的
纯逻辑，使拆包、粘包和异常长度可以独立测试。该封装仅用于课程仿真，
不代表铁路信号安全通信协议。
"""

from __future__ import annotations

import struct

from app.core.exceptions import FrameError

HEADER_SIZE = 4
MAX_FRAME_SIZE = 65_536


def encode_frame(payload: bytes, *, max_frame_size: int = MAX_FRAME_SIZE) -> bytes:
    """给非空正文增加长度头；拒绝可能耗尽内存的异常长度。"""
    length = len(payload)
    if not 0 < length <= max_frame_size:
        raise FrameError(f"帧正文长度必须在 1..{max_frame_size} 字节之间：{length}")
    return struct.pack(">I", length) + payload


class FrameDecoder:
    """可增量喂入字节的长度帧解析器。

    每个连接独占一个实例。遇到非法长度后应由连接层关闭连接，不继续尝试
    在不可信字节流中重新同步。
    """

    def __init__(self, *, max_frame_size: int = MAX_FRAME_SIZE) -> None:
        if max_frame_size <= 0:
            raise ValueError("max_frame_size 必须为正数")
        self._max_frame_size = max_frame_size
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, chunk: bytes) -> list[bytes]:
        """追加一次接收数据，并返回其中所有完整正文。"""
        self._buffer.extend(chunk)
        frames: list[bytes] = []
        while len(self._buffer) >= HEADER_SIZE:
            declared_length = struct.unpack(">I", self._buffer[:HEADER_SIZE])[0]
            if not 0 < declared_length <= self._max_frame_size:
                self._buffer.clear()
                raise FrameError(
                    "帧声明长度必须在 "
                    f"1..{self._max_frame_size} 字节之间：{declared_length}"
                )
            frame_end = HEADER_SIZE + declared_length
            if len(self._buffer) < frame_end:
                break
            frames.append(bytes(self._buffer[HEADER_SIZE:frame_end]))
            del self._buffer[:frame_end]
        return frames

    def reset(self) -> None:
        """连接重建时清除上一个字节流留下的不完整数据。"""
        self._buffer.clear()

