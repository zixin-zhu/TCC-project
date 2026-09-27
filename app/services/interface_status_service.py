"""统一接口健康状态、启动自检和教学诊断服务。"""

from __future__ import annotations

from dataclasses import replace
from app.core.interface_models import (
    DualComputeDiagnostic,
    InterfaceHealth,
    InterfaceId,
    InterfaceStatus,
    StartupCheckResult,
    StartupStep,
)


class InterfaceStatusService:
    """维护 P/Q/R/S/T/U/V/W 状态，不直接操作 socket 或 Qt。"""

    def __init__(self) -> None:
        self._statuses = {
            interface_id: InterfaceStatus(
                interface_id, InterfaceHealth.DISCONNECTED, 0, "尚未启动"
            )
            for interface_id in InterfaceId
        }
        self._startup_started = False
        self._startup_index = 0
        self._startup_complete = False
        self._failed_step: StartupStep | None = None
        self._startup_results: list[StartupCheckResult] = []

    @property
    def startup_complete(self) -> bool:
        return self._startup_complete

    @property
    def failed_step(self) -> StartupStep | None:
        return self._failed_step

    @property
    def startup_results(self) -> tuple[StartupCheckResult, ...]:
        return tuple(self._startup_results)

    def snapshot(self) -> tuple[InterfaceStatus, ...]:
        return tuple(self._statuses[interface_id] for interface_id in InterfaceId)

    def get(self, interface_id: InterfaceId) -> InterfaceStatus:
        return self._statuses[interface_id]

    def set_state(
        self,
        interface_id: InterfaceId,
        health: InterfaceHealth,
        *,
        now_ms: int,
        message: str,
    ) -> InterfaceStatus:
        if not isinstance(interface_id, InterfaceId):
            raise ValueError("未知接口编号")
        if not isinstance(health, InterfaceHealth):
            raise ValueError("未知接口健康状态")
        current = self._statuses[interface_id]
        updated = replace(current, health=health, changed_at_ms=now_ms, message=message)
        self._statuses[interface_id] = updated
        return updated

    def record_traffic(
        self,
        interface_id: InterfaceId,
        *,
        tx_delta: int = 0,
        rx_delta: int = 0,
        latency_ms: int | None = None,
    ) -> InterfaceStatus:
        current = self._statuses[interface_id]
        if tx_delta < 0 or rx_delta < 0:
            raise ValueError("接口计数增量不能为负数")
        updated = replace(
            current,
            tx_count=current.tx_count + tx_delta,
            rx_count=current.rx_count + rx_delta,
            latency_ms=latency_ms if latency_ms is not None else current.latency_ms,
        )
        self._statuses[interface_id] = updated
        return updated

    def begin_startup(self, *, now_ms: int) -> None:
        self._startup_started = True
        self._startup_index = 0
        self._startup_complete = False
        self._failed_step = None
        self._startup_results.clear()
        for interface_id in InterfaceId:
            self.set_state(
                interface_id,
                InterfaceHealth.INITIALIZING,
                now_ms=now_ms,
                message="启动自检中",
            )

    def complete_startup_step(
        self,
        step: StartupStep,
        *,
        success: bool,
        now_ms: int,
        message: str = "",
    ) -> StartupCheckResult:
        if not self._startup_started:
            raise ValueError("启动自检尚未开始")
        if self._failed_step is not None:
            raise ValueError("启动自检已失败，不能继续执行")
        expected = tuple(StartupStep)[self._startup_index]
        if step is not expected:
            raise ValueError(f"启动自检顺序错误：期待 {expected.value}，收到 {step.value}")
        text = message or ("自检通过" if success else "自检失败")
        health = InterfaceHealth.HEALTHY if success else InterfaceHealth.FAILED
        self.set_state(step.interface_id, health, now_ms=now_ms, message=text)
        result = StartupCheckResult(step, success, text, now_ms)
        self._startup_results.append(result)
        if not success:
            self._failed_step = step
            return result
        self._startup_index += 1
        if self._startup_index == len(tuple(StartupStep)):
            self._startup_complete = True
            # P/V/W 没有独立阻塞步骤，随完整启动自检进入可用状态；后续
            # 具体业务接口仍可通过 set_state() 单独降级或故障。
            covered = {item.interface_id for item in StartupStep}
            for interface_id in InterfaceId:
                if interface_id not in covered:
                    self.set_state(
                        interface_id,
                        InterfaceHealth.HEALTHY,
                        now_ms=now_ms,
                        message="启动自检通过，等待业务数据",
                    )
        return result
