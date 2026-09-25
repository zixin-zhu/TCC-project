"""双站 TCP 连接循环与 Qt worker-object 适配层。

本模块的核心约束是：监听、连接、收发和关闭 socket 的全部动作都发生在
`PeerConnectionRunner.run()` 所在线程。界面/控制器只通过队列、信号和停止
事件交互，绝不直接操作 socket。
"""

from __future__ import annotations

import queue
import socket
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot

from app.core.enums import ConnectionState, NetworkRole
from app.core.exceptions import ConnectionClosedError, FrameError, ProtocolError
from app.core.models import NetworkConfig
from app.network.connection import FramedSocketConnection
from app.network.protocol import (
    MessageType,
    PeerProtocolSession,
    ProtocolCodec,
    ProtocolMessage,
    SessionAction,
)
from app.services.peer_sync_service import PeerSyncService


@dataclass(frozen=True)
class PeerNetworkSettings:
    role: NetworkRole
    host: str
    port: int
    station_id: str
    peer_station_id: str
    heartbeat_interval_ms: int = 1000
    socket_timeout_ms: int = 100
    degraded_after_ms: int = 3500
    disconnect_after_ms: int = 6000
    reconnect_delays_ms: tuple[int, ...] = (1000, 2000, 5000)

    @classmethod
    def from_config(
        cls, *, station_id: str, network: NetworkConfig
    ) -> "PeerNetworkSettings":
        """把阶段 1 强类型配置转换为唯一的网络运行参数。"""
        return cls(
            role=network.role,
            host=network.host,
            port=network.port,
            station_id=station_id,
            peer_station_id=network.peer_station_id,
            heartbeat_interval_ms=network.heartbeat_interval_ms,
            degraded_after_ms=network.degraded_after_ms,
            disconnect_after_ms=network.disconnect_after_ms,
            reconnect_delays_ms=network.reconnect_delays_ms,
        )

    def __post_init__(self) -> None:
        if not 0 < self.port <= 65_535:
            raise ValueError(f"端口超出范围：{self.port}")
        if self.socket_timeout_ms <= 0 or self.heartbeat_interval_ms <= 0:
            raise ValueError("socket 与心跳间隔必须为正数")
        if not 0 < self.degraded_after_ms < self.disconnect_after_ms:
            raise ValueError("超时阈值必须满足 0 < degraded < disconnect")
        if not self.reconnect_delays_ms or any(delay <= 0 for delay in self.reconnect_delays_ms):
            raise ValueError("至少需要一个正数重连间隔")


class ReconnectBackoff:
    """按配置依次退避，耗尽后保持最后一个间隔。"""

    def __init__(self, delays_ms: tuple[int, ...]) -> None:
        if not delays_ms or any(delay <= 0 for delay in delays_ms):
            raise ValueError("重连间隔必须是非空正整数序列")
        self._delays_ms = delays_ms
        self._index = 0

    def next_delay_ms(self) -> int:
        delay = self._delays_ms[min(self._index, len(self._delays_ms) - 1)]
        self._index += 1
        return delay

    def reset(self) -> None:
        self._index = 0


StateProvider = Callable[[], Mapping[str, Any]]
StateCallback = Callable[[ConnectionState], None]
MessageCallback = Callable[[ProtocolMessage], None]
ErrorCallback = Callable[[str], None]
ServerReadyCallback = Callable[[str, int], None]


class PeerConnectionRunner:
    """可在 Python 线程或 Qt 工作线程运行的阻塞式连接循环。"""

    def __init__(
        self,
        settings: PeerNetworkSettings,
        *,
        state_provider: StateProvider,
        stop_event: threading.Event | None = None,
        on_state: StateCallback | None = None,
        on_message: MessageCallback | None = None,
        on_sent: MessageCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_server_ready: ServerReadyCallback | None = None,
    ) -> None:
        self.settings = settings
        self._state_provider = state_provider
        self._stop_event = stop_event or threading.Event()
        self._on_state = on_state or (lambda _state: None)
        self._on_message = on_message or (lambda _message: None)
        self._on_sent = on_sent or (lambda _message: None)
        self._on_error = on_error or (lambda _error: None)
        self._on_server_ready = on_server_ready or (lambda _host, _port: None)
        self._outgoing: queue.Queue[tuple[MessageType, Any, int]] = queue.Queue(
            maxsize=256
        )
        self._last_reported_state: ConnectionState | None = None

    def request_stop(self) -> None:
        """线程安全：只设置标志，不从调用线程触碰 worker 的 socket。"""
        self._stop_event.set()

    def submit(
        self, message_type: MessageType, payload: Any, *, state_version: int = 0
    ) -> None:
        """线程安全地排队一条业务消息，实际 send 在 runner 线程执行。"""
        try:
            self._outgoing.put_nowait((message_type, payload, state_version))
        except queue.Full as exc:
            raise ProtocolError("发送队列已满，拒绝继续积压旧状态") from exc

    def run(self) -> None:
        backoff = ReconnectBackoff(self.settings.reconnect_delays_ms)
        if self.settings.role is NetworkRole.SERVER:
            self._run_server(backoff)
        else:
            self._run_client(backoff)
        self._set_state(ConnectionState.DISCONNECTED)

    def _run_server(self, backoff: ReconnectBackoff) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.settings.host, self.settings.port))
            listener.listen(1)
            listener.settimeout(self.settings.socket_timeout_ms / 1000)
            # 只有本进程真正完成 bind/listen 后才发布就绪凭据。启动器据此
            # 区分“本次 A 已监听”和“端口被其他程序占用”两种情况。
            self._on_server_ready(self.settings.host, self.settings.port)
            self._set_state(ConnectionState.CONNECTING)
            while not self._stop_event.is_set():
                try:
                    transport, _address = listener.accept()
                except socket.timeout:
                    continue
                except OSError as exc:
                    if not self._stop_event.is_set():
                        self._on_error(f"监听失败：{exc}")
                    break
                self._serve_transport(transport)
                if not self._stop_event.is_set():
                    self._set_state(ConnectionState.CONNECTING)

    def _run_client(self, backoff: ReconnectBackoff) -> None:
        while not self._stop_event.is_set():
            self._set_state(ConnectionState.CONNECTING)
            transport = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            transport.settimeout(self.settings.socket_timeout_ms / 1000)
            try:
                transport.connect((self.settings.host, self.settings.port))
            except (ConnectionRefusedError, TimeoutError, socket.timeout, OSError):
                transport.close()
                delay_ms = backoff.next_delay_ms()
                self._stop_event.wait(delay_ms / 1000)
                continue
            reached_healthy = self._serve_transport(transport)
            if reached_healthy:
                # TCP connect 不能代表协议可用；只有完成 HELLO/ACK 才重置退避。
                backoff.reset()
            if not self._stop_event.is_set():
                self._stop_event.wait(backoff.next_delay_ms() / 1000)

    def _serve_transport(self, transport: socket.socket) -> bool:
        # 新会话由全量状态重新建立基线；旧会话或断线期间的增量不得补发。
        self._discard_outgoing()
        transport.settimeout(self.settings.socket_timeout_ms / 1000)
        connection = FramedSocketConnection(
            transport,
            outbound_codec=ProtocolCodec(
                local_station_id=self.settings.station_id,
                peer_station_id=self.settings.peer_station_id,
            ),
            inbound_codec=ProtocolCodec(
                local_station_id=self.settings.peer_station_id,
                peer_station_id=self.settings.station_id,
            ),
        )
        session = PeerProtocolSession(
            local_station_id=self.settings.station_id,
            peer_station_id=self.settings.peer_station_id,
        )
        local_state = self._state_provider()
        boundary_states = local_state.get("boundary_states", {})
        allowed_boundary_ids = (
            tuple(boundary_states) if isinstance(boundary_states, Mapping) else ()
        )
        sync_service = PeerSyncService(
            peer_station_id=self.settings.peer_station_id,
            allowed_boundary_ids=allowed_boundary_ids,
        )
        reached_healthy = False
        try:
            hello = session.on_transport_connected(now_ms=self._now_ms())
            self._set_state(ConnectionState.HANDSHAKING)
            self._send(connection, hello)
            sent_full_sync = False
            last_heartbeat_ms = self._now_ms()

            while not self._stop_event.is_set():
                self._flush_outgoing(connection, session)
                for message in connection.receive_available():
                    now_ms = self._now_ms()
                    decision = session.accept(
                        message,
                        received_at_ms=now_ms,
                        semantic_validator=lambda candidate: sync_service.validate_and_apply(
                            candidate, received_at_ms=now_ms
                        ),
                    )
                    if not decision.accepted:
                        self._on_error(f"拒绝消息 {message.message_id}：{decision.reason}")
                        continue
                    if decision.action is SessionAction.SEND_ACK:
                        self._send(
                            connection,
                            session.make_message(MessageType.ACK, {}, now_ms=now_ms)
                        )
                    self._on_message(message)

                if session.connection_state is ConnectionState.HEALTHY and not sent_full_sync:
                    reached_healthy = True
                    payload = dict(self._state_provider())
                    version = payload.get("state_version", 0)
                    self._send(
                        connection,
                        session.make_message(
                            MessageType.STATE_SYNC,
                            payload,
                            state_version=version if type(version) is int else 0,
                            now_ms=self._now_ms(),
                        )
                    )
                    sent_full_sync = True

                now_ms = self._now_ms()
                if (
                    session.connection_state in {ConnectionState.HEALTHY, ConnectionState.DEGRADED}
                    and now_ms - last_heartbeat_ms >= self.settings.heartbeat_interval_ms
                ):
                    self._send(
                        connection,
                        session.make_message(MessageType.HEARTBEAT, {}, now_ms=now_ms)
                    )
                    last_heartbeat_ms = now_ms

                state = session.evaluate_liveness(
                    now_ms=now_ms,
                    degraded_after_ms=self.settings.degraded_after_ms,
                    disconnect_after_ms=self.settings.disconnect_after_ms,
                )
                self._set_state(state)
                if state is ConnectionState.DISCONNECTED:
                    break
        except (ConnectionClosedError, ConnectionError, OSError):
            pass
        except (FrameError, ProtocolError) as exc:
            self._on_error(f"协议连接关闭：{exc}")
        finally:
            session.on_transport_disconnected()
            connection.close()
            self._set_state(ConnectionState.DISCONNECTED)
        return reached_healthy

    def _flush_outgoing(
        self, connection: FramedSocketConnection, session: PeerProtocolSession
    ) -> None:
        if session.connection_state is not ConnectionState.HEALTHY or session.requires_full_sync:
            return
        while True:
            try:
                message_type, payload, state_version = self._outgoing.get_nowait()
            except queue.Empty:
                return
            self._send(
                connection,
                session.make_message(
                    message_type,
                    payload,
                    state_version=state_version,
                    now_ms=self._now_ms(),
                )
            )

    def _send(
        self, connection: FramedSocketConnection, message: ProtocolMessage
    ) -> None:
        """sendall 返回后报告本地发送事件，仅供日志和事务编排。

        该事件不代表对端已经接收或处理，改方完成仍必须依赖应用层 ACK/
        DIRECTION_CONFIRM 或重连后的权威全量同步。
        """
        connection.send_message(message)
        self._on_sent(message)

    def _discard_outgoing(self) -> None:
        while True:
            try:
                self._outgoing.get_nowait()
            except queue.Empty:
                return

    def _set_state(self, state: ConnectionState) -> None:
        if state is not self._last_reported_state:
            self._last_reported_state = state
            self._on_state(state)

    @staticmethod
    def _now_ms() -> int:
        return int(time.monotonic() * 1000)


class NetworkWorker(QObject):
    """Qt 信号适配器；其 `run` 槽由专用 QThread 调用。"""

    state_changed = pyqtSignal(object)
    message_received = pyqtSignal(object)
    message_sent = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    server_ready = pyqtSignal(str, int)
    finished = pyqtSignal()

    def __init__(
        self,
        settings: PeerNetworkSettings,
        *,
        state_provider: StateProvider,
        on_server_ready: ServerReadyCallback | None = None,
    ) -> None:
        super().__init__()

        def publish_server_ready(host: str, port: int) -> None:
            """同时通知同进程编排器，并保留多进程启动器的文件回调。"""
            self.server_ready.emit(host, port)
            if on_server_ready is not None:
                on_server_ready(host, port)

        self._runner = PeerConnectionRunner(
            settings,
            state_provider=state_provider,
            on_state=self.state_changed.emit,
            on_message=self.message_received.emit,
            on_sent=self.message_sent.emit,
            on_error=self.error_occurred.emit,
            on_server_ready=publish_server_ready,
        )
        self.execution_thread_id: int | None = None

    @pyqtSlot()
    def run(self) -> None:
        self.execution_thread_id = int(QThread.currentThreadId())
        try:
            self._runner.run()
        except Exception as exc:
            # 工作线程是异常边界：bind/listen 等启动错误不能只写入 Qt 的
            # 标准错误后静默退出，编排器需要该信号阻止 B 站继续启动。
            self.error_occurred.emit(f"网络线程启动失败：{exc}")
        finally:
            self.finished.emit()

    def request_stop(self) -> None:
        self._runner.request_stop()

    def submit(
        self, message_type: MessageType, payload: Any, *, state_version: int = 0
    ) -> None:
        self._runner.submit(message_type, payload, state_version=state_version)


class NetworkThreadController(QObject):
    """拥有 worker 与 QThread，并提供有超时的规范关闭。"""

    def __init__(self, worker: NetworkWorker) -> None:
        super().__init__()
        self.worker = worker
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        # `stop()` 会在主线程同步 wait；若使用默认 queued connection，quit
        # 事件会等主线程恢复事件循环才执行，造成假性超时。QThread.quit 本身
        # 是线程安全的，因此这里显式直接调用以完成确定性关闭。
        self.worker.finished.connect(self.thread.quit, Qt.DirectConnection)

    def start(self) -> None:
        self.thread.start()

    def stop(self, *, timeout_ms: int = 3000) -> bool:
        self.worker.request_stop()
        return self.thread.wait(timeout_ms)
