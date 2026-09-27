"""把列车领域状态投影为可绘制的 2D 线路坐标。

该模块只做几何映射，不推进列车、不写轨道状态，也不读取 Qt 控件。线路长度
和区段顺序完全来自拓扑配置，避免把 G01~G08 或固定像素坐标写死在界面中。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import RunningDirection
from app.core.models import TopologyConfig
from app.services.dual_train_coordinator import DualTrainState, DualTrainStatus


@dataclass(frozen=True)
class SectionProjection:
    """一个物理区段在场景中的水平投影。"""

    section_id: str
    name: str
    length_m: float
    x_start: float
    x_end: float


@dataclass(frozen=True)
class TrainProjection:
    """列车图元需要的只读绘制数据。"""

    train_id: str
    section_id: str | None
    x_center: float
    y_center: float
    direction: RunningDirection
    status: DualTrainStatus
    safety_state: str
    current_speed_kmh: float
    lifecycle_version: int


class TrainProjectionMapper:
    """根据拓扑长度计算区段和列车的场景坐标。"""

    def __init__(self, topology: TopologyConfig, *, scene_width: float = 1100.0) -> None:
        if scene_width <= 0:
            raise ValueError("列车场景宽度必须为正数")
        if not topology.sections:
            raise ValueError("列车场景至少需要一个线路区段")
        total_length = sum(item.length_m for item in topology.sections)
        if total_length <= 0:
            raise ValueError("线路总长度必须为正数")
        scale = scene_width / total_length
        cursor = 0.0
        projections: list[SectionProjection] = []
        for item in topology.sections:
            width = item.length_m * scale
            projections.append(
                SectionProjection(
                    item.id,
                    item.name,
                    item.length_m,
                    cursor,
                    cursor + width,
                )
            )
            cursor += width
        self.sections = tuple(projections)
        self.scene_width = scene_width
        self._by_id = {item.section_id: item for item in self.sections}

    def project(self, train: DualTrainState, *, y_center: float = 88.0) -> TrainProjection:
        """将一个列车状态映射到场景；位置超出区段时安全钳位。"""
        section = self._by_id.get(train.section_id or "")
        if section is None:
            # 待发/到达列车没有当前区段，仍保留在对应线路端点附近，便于用户看到状态。
            x_center = 8.0 if train.direction is RunningDirection.A_TO_B else self.scene_width - 8.0
        else:
            position = min(max(train.position_m, 0.0), section.length_m)
            offset = position / section.length_m * (section.x_end - section.x_start)
            x_center = (
                section.x_start + offset
                if train.direction is RunningDirection.A_TO_B
                else section.x_end - offset
            )
        return TrainProjection(
            train.train_id,
            train.section_id,
            x_center,
            y_center,
            train.direction,
            train.status,
            train.safety_state,
            train.current_speed_kmh,
            train.lifecycle_version,
        )
