"""单连接收发、协议错误隔离和线程归属测试。"""

import json
import socket
import threading

import pytest

from app.core.exceptions import ProtocolError
from app.network.connection import FramedSocketConnection
from app.network.frame_codec import encode_frame
from app.network.protocol import MessageType, PeerProtocolSession, ProtocolCodec


def _pair() -> tuple[FramedSocketConnection, socket.socket]:
    local_socket, peer_socket = socket.socketpair()
    local_socket.settimeout(0.2)
    connection = FramedSocketConnection(
        local_socket,
        outbound_codec=ProtocolCodec(local_station_id="A", peer_station_id="B"),
        inbound_codec=ProtocolCodec(local_station_id="B", peer_station_id="A"),
    )
    return connection, peer_socket


def _peer_message() -> bytes:
    session = PeerProtocolSession(local_station_id="B", peer_station_id="A")
    return ProtocolCodec(local_station_id="B", peer_station_id="A").encode(
        session.make_message(MessageType.HEARTBEAT, {}, now_ms=100)
    )


def test_connection_reassembles_fragmented_message() -> None:
    connection, peer_socket = _pair()
    frame = encode_frame(_peer_message())
    try:
        peer_socket.sendall(frame[:3])
        assert connection.receive_available() == []
        peer_socket.sendall(frame[3:])
        messages = connection.receive_available()
        assert [message.message_type for message in messages] == [MessageType.HEARTBEAT]
    finally:
        connection.close()
        peer_socket.close()


def test_bad_crc_is_raised_and_never_returned_as_message() -> None:
    connection, peer_socket = _pair()
    document = json.loads(_peer_message().decode("utf-8"))
    document["payload"] = {"tampered": True}
    peer_socket.sendall(encode_frame(json.dumps(document).encode("utf-8")))
    try:
        with pytest.raises(ProtocolError, match="CRC"):
            connection.receive_available()
    finally:
        connection.close()
        peer_socket.close()


def test_connection_rejects_cross_thread_socket_use() -> None:
    connection, peer_socket = _pair()
    connection.bind_to_current_thread()
    captured: list[Exception] = []

    def use_from_other_thread() -> None:
        try:
            connection.receive_available()
        except Exception as exc:  # noqa: BLE001 - 断言边界捕获异常类型
            captured.append(exc)

    thread = threading.Thread(target=use_from_other_thread)
    thread.start()
    thread.join(timeout=1)
    try:
        assert captured
        assert "线程" in str(captured[0])
    finally:
        connection.close(force=True)
        peer_socket.close()

