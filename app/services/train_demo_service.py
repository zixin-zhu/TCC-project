"""只通过 TccController 写入轨道状态的配置驱动列车教学演示。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.enums import RunningDirection, SectionKind, TrackInputSource, TrackState
from app.core.models import OperationResult
from app.services.tcc_controller import TccController


class TrainDemoStatus(str, Enum):
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ARRIVED = "ARRIVED"
    RESET = "RESET"


@dataclass
class TrainDemoState:
    train_id: str
    direction: RunningDirection
    section_id: str | None = None
    position_m: float = 0.0
    speed_kmh: float = 120.0
    status: TrainDemoStatus = TrainDemoStatus.WAITING


class TrainDemoService:
    """维护演示位置；占用与出清必须经过控制器的 TRAIN 来源。

    本服务不是车载 ATP 或运动学模型，只用于课堂上观察列车跨闭塞分区时
    TCC 编码、信号和报文的联动。人工和故障来源由运行态独立保存，列车
    出清绝不会删除这些来源。
    """

    def __init__(self, controller: TccController) -> None:
        self.controller = controller
        self.trains: dict[str, TrainDemoState] = {}
        self._next_number = 1
        self._lengths = {
            item.id: item.length_m
            for item in controller.config.topology.sections
            if item.kind is SectionKind.BLOCK
        }

    def create_train(self) -> TrainDemoState:
        train = TrainDemoState(
            train_id=f"T{self._next_number:03d}",
            direction=self.controller.runtime.running_direction,
        )
        self._next_number += 1
        self.trains[train.train_id] = train
        return train

    def dispatch(self, train_id: str) -> OperationResult:
        train = self.trains.get(train_id)
        if train is None:
            return OperationResult(False, f"未知演示列车 {train_id}")
        if train.status is not TrainDemoStatus.WAITING:
            return OperationResult(False, "列车不在待发状态")
        if self.controller.snapshot.direction_operation_locked:
            return OperationResult(False, "区间方向尚未确认，禁止发车")
        expected_station = "A" if train.direction is RunningDirection.A_TO_B else "B"
        if self.controller.config.station.station_id != expected_station:
            return OperationResult(False, "本站不是当前方向的发车站")
        required_route = f"{expected_station}_DEPART"
        if required_route not in self.controller.snapshot.active_route_ids:
            return OperationResult(False, f"发车进路 {required_route} 尚未建立")
        entrance = self._ordered_blocks(train.direction)[0]
        if self.controller.snapshot.tracks[entrance] is not TrackState.CLEAR:
            return OperationResult(False, f"入口区段 {entrance} 非空闲")
        result = self.controller.set_track_state(
            entrance, TrackInputSource.TRAIN, TrackState.OCCUPIED
        )
        if result.success:
            train.section_id = entrance
            train.position_m = 0.0
            train.status = TrainDemoStatus.RUNNING
        return result

    def tick(self, delta_seconds: float) -> None:
        if delta_seconds <= 0:
            raise ValueError("列车演示步长必须为正数")
        for train in self.trains.values():
            if train.status not in {TrainDemoStatus.RUNNING, TrainDemoStatus.STOPPED}:
                continue
            if (
                self.controller.snapshot.direction_operation_locked
                or self.controller.runtime.running_direction is not train.direction
            ):
                train.status = TrainDemoStatus.STOPPED
                continue
            train.status = TrainDemoStatus.RUNNING
            train.position_m += train.speed_kmh / 3.6 * delta_seconds
            self._advance(train)

    def reset(self) -> None:
        """只撤销 TRAIN 来源，不触碰人工占用、故障占用或分路不良。"""
        for section_id in self._lengths:
            self.controller.set_track_state(
                section_id, TrackInputSource.TRAIN, TrackState.CLEAR
            )
        for train in self.trains.values():
            train.section_id = None
            train.position_m = 0.0
            train.status = TrainDemoStatus.RESET

    def _advance(self, train: TrainDemoState) -> None:
        if train.section_id is None:
            return
        order = self._ordered_blocks(train.direction)
        while train.position_m >= self._lengths[train.section_id]:
            current = train.section_id
            next_index = order.index(current) + 1
            if next_index >= len(order):
                self.controller.set_track_state(
                    current, TrackInputSource.TRAIN, TrackState.CLEAR
                )
                train.section_id = None
                train.position_m = 0.0
                train.status = TrainDemoStatus.ARRIVED
                return
            next_section = order[next_index]
            if self.controller.snapshot.tracks[next_section] is not TrackState.CLEAR:
                train.position_m = self._lengths[current]
                train.status = TrainDemoStatus.STOPPED
                return
            # 先占用前方、再出清后方，避免转换瞬间把列车从检测状态中抹掉。
            occupied = self.controller.set_track_state(
                next_section, TrackInputSource.TRAIN, TrackState.OCCUPIED
            )
            if not occupied.success:
                train.status = TrainDemoStatus.STOPPED
                return
            self.controller.set_track_state(
                current, TrackInputSource.TRAIN, TrackState.CLEAR
            )
            train.position_m -= self._lengths[current]
            train.section_id = next_section
            train.status = TrainDemoStatus.RUNNING

    def _ordered_blocks(self, direction: RunningDirection) -> tuple[str, ...]:
        configured = tuple(self._lengths)
        return (
            configured
            if direction is RunningDirection.A_TO_B
            else tuple(reversed(configured))
        )
