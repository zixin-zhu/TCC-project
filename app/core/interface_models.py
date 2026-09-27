"""CTCS-2 P/Q/R/S/T/U/V/W 接口与启动诊断数据模型。"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class InterfaceId(str, Enum):
    P = "P"  # CTC/临时限速输入
    Q = "Q"  # 联锁与区间闭塞
    R = "R"  # 监测系统
    S = "S"  # LEU
    T = "T"  # 轨道电路
    U = "U"  # 相邻 TCC
    V = "V"  # 信号机
    W = "W"  # 在线测试


class InterfaceHealth(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    INITIALIZING = "INITIALIZING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class StartupStep(str, Enum):
    """规范要求的启动自检顺序。"""

    LOGIC_UNIT = "LOGIC_UNIT"
    SAFETY_IO = "SAFETY_IO"
    DATA_STORE = "DATA_STORE"
    TRACK_CIRCUIT = "TRACK_CIRCUIT"
    INTERLOCKING_CTC = "INTERLOCKING_CTC"
    PEER_TCC = "PEER_TCC"
    LEU = "LEU"

    @property
    def interface_id(self) -> InterfaceId:
        return {
            StartupStep.LOGIC_UNIT: InterfaceId.R,
            StartupStep.SAFETY_IO: InterfaceId.T,
            StartupStep.DATA_STORE: InterfaceId.R,
            StartupStep.TRACK_CIRCUIT: InterfaceId.T,
            StartupStep.INTERLOCKING_CTC: InterfaceId.Q,
            StartupStep.PEER_TCC: InterfaceId.U,
            StartupStep.LEU: InterfaceId.S,
        }[self]


@dataclass(frozen=True)
class InterfaceStatus:
    interface_id: InterfaceId
    health: InterfaceHealth
    changed_at_ms: int
    message: str
    tx_count: int = 0
    rx_count: int = 0
    latency_ms: int | None = None


@dataclass(frozen=True)
class StartupCheckResult:
    step: StartupStep
    success: bool
    message: str
    completed_at_ms: int


@dataclass(frozen=True)
class DualComputeDiagnostic:
    """主备计算结果比较；仅用于教学诊断展示。"""

    consistent: bool
    degraded: bool
    reason: str
    differences: tuple[str, ...] = ()

    @classmethod
    def compare(
        cls, primary_result: Mapping[str, Any], standby_result: Mapping[str, Any]
    ) -> "DualComputeDiagnostic":
        keys = sorted(set(primary_result) | set(standby_result))
        differences = tuple(
            key
            for key in keys
            if primary_result.get(key) != standby_result.get(key)
        )
        if differences:
            return cls(
                consistent=False,
                degraded=True,
                reason=f"主备计算结果不一致：{', '.join(differences)}",
                differences=differences,
            )
        return cls(True, False, "主备计算结果一致")
