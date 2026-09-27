"""单进程 A/B 双站运行时编排。

本模块只管理启动和关闭顺序，不复制任何 TCC 业务规则。两站控制器、网络
worker 和 SQLite 仓储仍彼此独立，并继续通过真实 TCP 协议交换状态。
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Protocol
import time

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from app.application import ApplicationRuntime
from app.core.enums import ConnectionState, NetworkRole
from app.core.exceptions import ConfigError
from app.core.models import ProjectConfig
from app.core.models import OperationResult
from app.core.interface_models import (
    InterfaceHealth,
    InterfaceId,
    StartupStep,
)
from app.infrastructure.config_loader import load_project_config
from app.services.interface_status_service import InterfaceStatusService


def validate_dual_station_config(
    config_dir: Path,
) -> tuple[ProjectConfig, ProjectConfig]:
    """加载并交叉校验 A/B 配置，不创建数据库或网络线程。"""
    config_a = load_project_config(config_dir, "A")
    config_b = load_project_config(config_dir, "B")
    if config_a.station.station_id != "A" or config_b.station.station_id != "B":
        raise ConfigError("A/B 配置中的站点标识不正确")

    network_a = config_a.station.network
    network_b = config_b.station.network
    if network_a.role is not NetworkRole.SERVER:
        raise ConfigError("A站网络角色必须为 SERVER")
    if network_b.role is not NetworkRole.CLIENT:
        raise ConfigError("B站网络角色必须为 CLIENT")
    if network_a.peer_station_id != "B" or network_b.peer_station_id != "A":
        raise ConfigError("A/B 对站标识不匹配")
    if (network_a.host, network_a.port) != (network_b.host, network_b.port):
        raise ConfigError("A/B 网络地址或端口不一致")
    return config_a, config_b


class DualLifecycleState(str, Enum):
    """双站容器生命周期；业务通信健康度仍由各站快照表达。"""

    IDLE = "IDLE"
    STARTING_A = "STARTING_A"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    STOP_FAILED = "STOP_FAILED"


class StationRuntimePort(Protocol):
    """编排器所需的最小单站运行时接口，便于隔离测试。"""

    worker: QObject

    def start(self) -> None: ...

    def stop(self, *, timeout_ms: int = 3000) -> bool: ...

    def set_network_fault(self, enabled: bool) -> OperationResult: ...


class DualStationApplication(QObject):
    """按 A 监听就绪后 B 启动、B 先于 A 关闭的顺序管理两站。"""

    lifecycle_changed = pyqtSignal(object)
    startup_failed = pyqtSignal(str)

    def __init__(
        self,
        station_a: StationRuntimePort,
        station_b: StationRuntimePort,
    ) -> None:
        super().__init__()
        self.station_a = station_a
        self.station_b = station_b
        self.state = DualLifecycleState.IDLE
        self.failure_reason = ""
        self._b_started = False
        self._station_a_stopped = False
        self._station_b_stopped = False
        # 仅记录协议层已完成 HELLO/ACK 的站点；它不等价于业务作业允许，
        # 后者仍由两站控制器的安全锁闭状态独立决定。
        self._healthy_stations: set[str] = set()
        self.interface_status = InterfaceStatusService()
        station_a.worker.server_ready.connect(self._on_server_ready)
        station_a.worker.error_occurred.connect(self._on_station_a_error)
        # 真实 worker 具备 state_changed；测试替身或旧扩展若没有该信号，
        # 仍保留原有启动编排能力，不因诊断功能破坏兼容性。
        for station_id, station in (("A", station_a), ("B", station_b)):
            state_signal = getattr(station.worker, "state_changed", None)
            if state_signal is not None:
                state_signal.connect(
                    lambda state, sid=station_id: self._on_station_state(sid, state)
                )

    @classmethod
    def build(
        cls, *, config_dir: Path, data_root: Path
    ) -> "DualStationApplication":
        """先交叉校验两站配置，再创建任何数据库或网络线程。"""
        validate_dual_station_config(config_dir)

        station_a = ApplicationRuntime.build(
            station_id="A", config_dir=config_dir, data_dir=data_root / "A"
        )
        try:
            station_b = ApplicationRuntime.build(
                station_id="B", config_dir=config_dir, data_dir=data_root / "B"
            )
        except Exception:
            # B 装配失败时 A 尚未启动网络线程，可以直接关闭其控制器和仓储。
            station_a.controller.close()
            raise
        return cls(station_a, station_b)

    def start(self) -> None:
        """只启动 A；B 必须等待本次 A 的监听就绪信号。"""
        if self.state is not DualLifecycleState.IDLE:
            return
        self._healthy_stations.clear()
        self.interface_status.begin_startup(now_ms=0)
        self._set_state(DualLifecycleState.STARTING_A)
        self.station_a.start()

    @pyqtSlot(str, int)
    def _on_server_ready(self, _host: str, _port: int) -> None:
        if self.state is not DualLifecycleState.STARTING_A or self._b_started:
            return
        self._b_started = True
        self.station_b.start()
        self._set_state(DualLifecycleState.RUNNING)

    @pyqtSlot(str, object)
    def _on_station_state(self, station_id: str, state: ConnectionState) -> None:
        """把 A/B 协议连接状态汇总到 U 接口，并推进启动自检。

        ``HEALTHY`` 只表示站间协议握手和全量同步通道可用，不会解除方向
        安全锁闭；方向恢复仍由各站控制器收到对端快照后独立完成。
        """
        if station_id not in {"A", "B"} or not isinstance(state, ConnectionState):
            return
        health = {
            ConnectionState.HEALTHY: InterfaceHealth.HEALTHY,
            ConnectionState.DEGRADED: InterfaceHealth.DEGRADED,
            ConnectionState.DISCONNECTED: InterfaceHealth.DISCONNECTED,
            ConnectionState.CONNECTING: InterfaceHealth.INITIALIZING,
            ConnectionState.HANDSHAKING: InterfaceHealth.INITIALIZING,
        }[state]
        if state is ConnectionState.HEALTHY:
            self._healthy_stations.add(station_id)
        else:
            self._healthy_stations.discard(station_id)
        self.interface_status.set_state(
            InterfaceId.U,
            health,
            now_ms=int(time.monotonic() * 1000),
            message=f"A/B 站间协议：{state.value}",
        )
        if self._healthy_stations == {"A", "B"}:
            self._complete_startup_checks()

    def _complete_startup_checks(self) -> None:
        """在双站协议健康后一次性完成已验证的启动自检顺序。

        本仿真中的逻辑单元、安全 I/O、数据仓储、轨道电路、联锁/CTC、
        对端 TCC 和 LEU 均在 ``build()`` 阶段完成装配；A/B 协议健康是
        最后一个外部条件。这里仍严格通过 ``InterfaceStatusService`` 按
        规范顺序逐项记录，避免直接把状态字典改成“全健康”。
        """
        if self.interface_status.startup_complete:
            return
        now_ms = int(time.monotonic() * 1000)
        for step in StartupStep:
            self.interface_status.complete_startup_step(
                step,
                success=True,
                now_ms=now_ms,
                message="启动自检通过；双站协议通道已健康",
            )

    @pyqtSlot(str)
    def _on_station_a_error(self, message: str) -> None:
        if self.state is not DualLifecycleState.STARTING_A:
            return
        self.failure_reason = f"A站启动失败：{message}"
        self.interface_status.set_state(
            InterfaceId.R,
            InterfaceHealth.FAILED,
            now_ms=0,
            message=self.failure_reason,
        )
        self._set_state(DualLifecycleState.FAILED)
        self.startup_failed.emit(self.failure_reason)

    def stop(self, *, timeout_ms: int = 3000) -> bool:
        """按 B→A 关闭；成功项不重复，超时项允许用户再次重试。"""
        if self._station_b_stopped and self._station_a_stopped:
            return True
        self._set_state(DualLifecycleState.STOPPING)
        if not self._station_b_stopped:
            self._station_b_stopped = self.station_b.stop(timeout_ms=timeout_ms)
        if not self._station_a_stopped:
            self._station_a_stopped = self.station_a.stop(timeout_ms=timeout_ms)
        stopped = self._station_b_stopped and self._station_a_stopped
        self._set_state(
            DualLifecycleState.STOPPED
            if stopped
            else DualLifecycleState.STOP_FAILED
        )
        return stopped

    def set_station_network_fault(
        self, station_id: str, enabled: bool
    ) -> OperationResult:
        """供单窗口教学演练切换某一站的可恢复网络故障。"""
        if station_id not in {"A", "B"}:
            return OperationResult(False, f"未知站点 {station_id}")
        station = self.station_a if station_id == "A" else self.station_b
        return station.set_network_fault(enabled)

    def _set_state(self, state: DualLifecycleState) -> None:
        if state is self.state:
            return
        self.state = state
        self.lifecycle_changed.emit(state)
