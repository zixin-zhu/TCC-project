"""正式应用装配：主线程控制器、网络线程桥接与 SQLite 生命周期。"""

from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from PyQt5.QtCore import QObject, QTimer, pyqtSlot

from app.core.enums import ConnectionState, RunningDirection
from app.core.exceptions import ProtocolError
from app.core.models import OperationResult
from app.infrastructure.config_loader import (
    load_coding_rules,
    load_project_config,
    load_telegram_catalog,
)
from app.infrastructure.sqlite_repository import SQLiteRepository
from app.network.network_worker import (
    NetworkThreadController,
    NetworkWorker,
    PeerNetworkSettings,
)
from app.network.protocol import MessageType, ProtocolMessage
from app.services.alarm_service import AlarmLevel, AlarmService
from app.services.direction_change_protocol import DirectionProtocolAdapter
from app.services.peer_sync_service import PeerSyncService
from app.services.persistence_service import PersistenceService
from app.services.tcc_controller import TccController


class ThreadSafeStateProvider:
    """网络线程只读取深复制字典，不接触主线程运行态对象。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payload: dict[str, Any] = {
            "state_version": 0,
            "boundary_states": {},
        }

    def update(self, payload: Mapping[str, Any]) -> None:
        with self._lock:
            self._payload = copy.deepcopy(dict(payload))

    def __call__(self) -> Mapping[str, Any]:
        with self._lock:
            return copy.deepcopy(self._payload)


class ApplicationRuntime(QObject):
    """QObject 位于 GUI 主线程，承接 worker 的 queued signal。"""

    def __init__(
        self,
        controller: TccController,
        worker: QObject,
        network_thread,
        peer_sync: PeerSyncService,
        state_provider: ThreadSafeStateProvider,
    ) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.controller = controller
        self.worker = worker
        self.network_thread = network_thread
        self.peer_sync = peer_sync
        self.state_provider = state_provider
        self._received_count = 0
        self._sent_count = 0
        # Qt queued signal 可能在线程 wait() 成功后才交付；关闭边界先关闭此门，
        # 避免迟到的网络/定时器回调写入已经关闭的控制器和数据库。
        self._accept_async_events = True
        self._direction_timer = QTimer(self)
        self._direction_timer.setInterval(250)
        self._direction_timer.timeout.connect(self._on_direction_timeout)
        worker.state_changed.connect(self._on_network_state)
        worker.message_received.connect(self._on_message)
        worker.error_occurred.connect(self._on_network_error)
        if hasattr(worker, "message_sent"):
            worker.message_sent.connect(self._on_message_sent)

    @classmethod
    def build(
        cls,
        *,
        station_id: str,
        config_dir: Path,
        data_dir: Path,
        worker=None,
        network_thread=None,
        server_ready_callback: Callable[[str, int], None] | None = None,
    ) -> "ApplicationRuntime":  # type: ignore[no-untyped-def]
        config = load_project_config(config_dir, station_id)
        alarms = AlarmService()
        persistence = PersistenceService(
            SQLiteRepository(Path(data_dir) / f"tcc_{station_id.lower()}.db"),
            alarms,
        )
        provider = ThreadSafeStateProvider()
        worker_holder: dict[str, Any] = {"worker": worker}

        def publish(payload: Mapping[str, Any]) -> None:
            active_worker = worker_holder["worker"]
            if active_worker is not None:
                active_worker.submit(
                    MessageType.STATE_SYNC,
                    dict(payload),
                    state_version=int(payload["state_version"]),
                )

        def submit_direction(message) -> None:  # type: ignore[no-untyped-def]
            active_worker = worker_holder["worker"]
            if active_worker is None:
                raise RuntimeError("网络 worker 尚未创建")
            message_type, payload, version = DirectionProtocolAdapter.to_network_command(
                message
            )
            active_worker.submit(message_type, dict(payload), state_version=version)

        def submit_confirmation(record) -> None:  # type: ignore[no-untyped-def]
            active_worker = worker_holder["worker"]
            if active_worker is None:
                raise RuntimeError("网络 worker 尚未创建")
            message_type, payload, version = (
                DirectionProtocolAdapter.recovery_network_command(record)
            )
            active_worker.submit(message_type, dict(payload), state_version=version)

        controller = TccController(
            config,
            load_coding_rules(config_dir / "coding_rules.json"),
            load_telegram_catalog(config_dir / "telegram_packets.json"),
            alarms=alarms,
            persistence=persistence,
            publish_state=publish,
            cache_state=provider.update,
            snapshot_listener=lambda _snapshot: None,
            clock_ms=lambda: int(time.monotonic() * 1000),
            send_direction=submit_direction,
            send_direction_confirmation=submit_confirmation,
        )
        provider.update(controller.network_state_payload())
        if worker is None:
            worker = NetworkWorker(
                PeerNetworkSettings.from_config(
                    station_id=config.station.station_id,
                    network=config.station.network,
                ),
                state_provider=provider,
                on_server_ready=server_ready_callback,
            )
            worker_holder["worker"] = worker
        if network_thread is None:
            network_thread = NetworkThreadController(worker)
        block_ids = [
            item.id for item in config.topology.sections if item.id.startswith("Q")
        ]
        peer_sync = PeerSyncService(
            peer_station_id=config.station.network.peer_station_id,
            allowed_boundary_ids=block_ids,
        )
        return cls(controller, worker, network_thread, peer_sync, provider)

    def start(self) -> None:
        self._accept_async_events = True
        self._direction_timer.start()
        self.network_thread.start()

    def set_network_fault(self, enabled: bool) -> OperationResult:
        """切换可恢复的教学网络故障，不停止线程或关闭控制器。"""
        setter = getattr(self.worker, "set_fault_injected", None)
        if setter is None:
            return OperationResult(False, "当前网络 worker 不支持故障注入")
        setter(enabled)
        return OperationResult(
            True,
            "教学网络故障已注入" if enabled else "教学网络故障已解除，正在自动重连",
        )

    def stop(self, *, timeout_ms: int = 3000) -> bool:
        self._accept_async_events = False
        self._direction_timer.stop()
        stopped = self.network_thread.stop(timeout_ms=timeout_ms)
        if stopped:
            self.controller.close()
        else:
            # 关闭被拒绝时应用仍在运行，超时保护不能悄悄停用。
            self._accept_async_events = True
            self._direction_timer.start()
        return stopped

    @pyqtSlot(object)
    def _on_network_state(self, state: ConnectionState) -> None:
        if not self._accept_async_events:
            return
        if state is ConnectionState.DISCONNECTED:
            self.peer_sync.reset()
        self.controller.set_connection_state(state)

    @pyqtSlot(object)
    def _on_message(self, message: ProtocolMessage) -> None:
        if not self._accept_async_events:
            return
        self._received_count += 1
        self._publish_network_metrics()
        if message.message_type is MessageType.ERROR and (
            not isinstance(message.payload, Mapping)
            or message.payload.get("kind") != "REJECT"
        ):
            reason = (
                message.payload.get("reason", "对站报告未说明原因")
                if isinstance(message.payload, Mapping)
                else "对站错误载荷格式非法"
            )
            self.controller.raise_external_alarm(
                "PEER_PROTOCOL_ERROR",
                AlarmLevel.WARNING,
                str(reason),
                "peer",
            )
            return
        if message.message_type in {
            MessageType.DIRECTION_PREPARE,
            MessageType.DIRECTION_READY,
            MessageType.DIRECTION_COMMIT,
            MessageType.DIRECTION_COMMITTED,
            MessageType.ERROR,
        }:
            try:
                direction_message = DirectionProtocolAdapter.from_protocol_message(message)
                self.controller.handle_direction_message(direction_message)
            except ProtocolError as exc:
                self._report_protocol_error(exc)
            return
        if message.message_type is MessageType.DIRECTION_CONFIRM:
            try:
                record = DirectionProtocolAdapter.from_recovery_protocol_message(message)
                self.controller.handle_direction_confirmation(record)
            except ProtocolError as exc:
                self._report_protocol_error(exc)
            return
        if message.message_type not in {
            MessageType.STATE_SYNC,
            MessageType.TRACK_BOUNDARY,
        }:
            return
        peer_direction: RunningDirection | None = None
        if message.message_type is MessageType.STATE_SYNC:
            raw_direction = (
                message.payload.get("running_direction")
                if isinstance(message.payload, Mapping)
                else None
            )
            try:
                peer_direction = RunningDirection(raw_direction)
            except (TypeError, ValueError):
                self._report_protocol_error(
                    ProtocolError(f"全量同步方向非法：{raw_direction}")
                )
                return
        now = int(time.monotonic() * 1000)
        try:
            self.peer_sync.validate_and_apply(message, received_at_ms=now)
        except ProtocolError as exc:
            self.controller.raise_external_alarm(
                "PEER_SYNC_REJECTED",
                AlarmLevel.CRITICAL,
                str(exc),
                "peer",
            )
            self.controller.set_connection_state(ConnectionState.DEGRADED)
            return
        if self.peer_sync.snapshot is not None:
            if (
                message.message_type is MessageType.STATE_SYNC
                and self.controller.snapshot.connection_state
                is not ConnectionState.HEALTHY
            ):
                # worker 只会在协议握手完成后交付业务全量同步。Qt 的
                # state_changed(HEALTHY) 与 message_received 是两个排队信号；
                # 重连时后者可能先到。先恢复连接门禁，避免随后的方向恢复
                # 因“仍是 DEGRADED”被永久留在 FAULT_LOCKED。
                self.controller.set_connection_state(ConnectionState.HEALTHY)
            self.controller.update_peer_snapshot(self.peer_sync.snapshot)
            if message.message_type is not MessageType.STATE_SYNC:
                return
            if peer_direction is None:
                return
            authoritative = (
                self.controller.runtime.running_direction
                if self.controller.config.station.station_id == "A"
                else peer_direction
            )
            self.controller.restore_authoritative_direction(authoritative)

    @pyqtSlot(object)
    def _on_message_sent(self, _message: object) -> None:
        if not self._accept_async_events:
            return
        self._sent_count += 1
        self._publish_network_metrics()

    def _publish_network_metrics(self) -> None:
        self.controller.update_network_metrics(
            received=self._received_count,
            sent=self._sent_count,
        )

    @pyqtSlot()
    def _on_direction_timeout(self) -> None:
        if not self._accept_async_events:
            return
        self.controller.expire_direction_change()
        self.controller.reevaluate_time_dependent_safety()

    @pyqtSlot(str)
    def _on_network_error(self, message: str) -> None:
        if not self._accept_async_events:
            return
        self.controller.raise_external_alarm(
            "NETWORK_ERROR",
            AlarmLevel.WARNING,
            message,
            "peer",
        )
        self.controller.set_connection_state(ConnectionState.DEGRADED)

    def _report_protocol_error(self, error: ProtocolError) -> None:
        self.controller.raise_external_alarm(
            "PROTOCOL_REJECTED",
            AlarmLevel.CRITICAL,
            str(error),
            "peer",
        )
        self.controller.set_connection_state(ConnectionState.DEGRADED)
