"""单个已连接 socket 的分帧和协议编解码边界。"""

from __future__ import annotations

import socket
import threading

from app.core.exceptions import ConnectionClosedError
from app.network.frame_codec import FrameDecoder, encode_frame
from app.network.protocol import ProtocolCodec, ProtocolMessage


class FramedSocketConnection:
    """确保一个 socket 始终只由首次使用它的线程访问。"""

    def __init__(
        self,
        transport: socket.socket,
        *,
        outbound_codec: ProtocolCodec,
        inbound_codec: ProtocolCodec,
    ) -> None:
        self._socket = transport
        self._outbound_codec = outbound_codec
        self._inbound_codec = inbound_codec
        self._decoder = FrameDecoder()
        self._owner_thread_id: int | None = None
        self._closed = False

    @property
    def owner_thread_id(self) -> int | None:
        return self._owner_thread_id

    def bind_to_current_thread(self) -> None:
        current = threading.get_ident()
        if self._owner_thread_id is None:
            self._owner_thread_id = current
        elif self._owner_thread_id != current:
            raise RuntimeError(
                f"socket 只能在线程 {self._owner_thread_id} 使用，当前线程为 {current}"
            )

    def send_message(self, message: ProtocolMessage) -> None:
        self.bind_to_current_thread()
        if self._closed:
            raise ConnectionClosedError("连接已关闭")
        self._socket.sendall(encode_frame(self._outbound_codec.encode(message)))

    def receive_available(self) -> list[ProtocolMessage]:
        """执行一次有界 recv；超时表示当前没有新消息。"""
        self.bind_to_current_thread()
        if self._closed:
            raise ConnectionClosedError("连接已关闭")
        try:
            chunk = self._socket.recv(16_384)
        except socket.timeout:
            return []
        if not chunk:
            raise ConnectionClosedError("对端已关闭连接")
        return [self._inbound_codec.decode(frame) for frame in self._decoder.feed(chunk)]

    def close(self, *, force: bool = False) -> None:
        if self._closed:
            return
        if not force:
            self.bind_to_current_thread()
        self._closed = True
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._socket.close()

