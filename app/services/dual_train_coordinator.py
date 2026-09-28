"""单进程双站界面的唯一列车演示协调器。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from app.core.enums import ConnectionState, RunningDirection, TrackInputSource, TrackState
from app.core.models import OperationResult
from app.services.shared_track_input import SharedTrackInputAdapter
from app.services.tcc_controller import TccController


class DualTrainStatus(str, Enum):
    """联合列车演示状态，不代表真实车载设备状态。"""

    WAITING = "WAITING"
    READY = "READY"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ARRIVED = "ARRIVED"
    # 旧页面曾把复位态命名为 RESET；现在复位成功后必须可再次发车，
    # 因此保留为 WAITING 的兼容别名，避免旧调用方失效但不再制造死状态。
    RESET = "WAITING"


@dataclass
class DualTrainState:
    """供界面展示的一份跨站列车状态。"""

    train_id: str
    direction: RunningDirection
    section_id: str | None = None
    position_m: float = 0.0
    current_speed_kmh: float = 0.0
    target_speed_kmh: float = 120.0
    distance_ahead_m: float = 0.0
    last_balise_id: str | None = None
    safety_state: str = "待发"
    status: DualTrainStatus = DualTrainStatus.WAITING
    lifecycle_version: int = 0


class DualTrainCoordinator(QObject):
    """管理唯一时钟下的跨 A/B 列车移动与保守轨道输入。"""

    trains_changed = pyqtSignal(object)
    operation_failed = pyqtSignal(str)

    def __init__(
        self,
        station_a: TccController,
        station_b: TccController,
        *,
        track_input: SharedTrackInputAdapter | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._station_a = station_a
        self._station_b = station_b
        self._track_input = track_input or SharedTrackInputAdapter(station_a, station_b)
        self.trains: dict[str, DualTrainState] = {}
        self._next_number = 1
        self._manually_paused = False
        self._speed_multiplier = 1.0
        self._sections = tuple(item.id for item in station_a.config.topology.sections)
        self._lengths = {
            item.id: item.length_m for item in station_a.config.topology.sections
        }
        self._balises_by_section = self._build_balise_index()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(
            lambda: self.tick(self.timer.interval() / 1000.0)
        )

    @property
    def speed_multiplier(self) -> float:
        """返回课程仿真的时间倍速，不改变列车的物理速度字段。"""
        return self._speed_multiplier

    def set_speed_multiplier(self, multiplier: float) -> OperationResult:
        """设置仿真时间倍速；倍速只作用于 ``tick`` 的时间推进。"""
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
            return self._failure("仿真倍速必须是数字")
        if not math.isfinite(float(multiplier)) or not 0.1 <= float(multiplier) <= 20.0:
            return self._failure("仿真倍速必须在 0.1×～20× 范围内")
        self._speed_multiplier = float(multiplier)
        return OperationResult(True, f"仿真倍速已设置为 {self._speed_multiplier:g}×")

    def create_train(self) -> DualTrainState:
        """按当前方向创建待发列车；允许同时维护多列待发演示列车。"""
        direction = RunningDirection(self._station_a.snapshot.running_direction)
        train = DualTrainState(
            train_id=f"T{self._next_number:03d}",
            direction=direction,
        )
        self._next_number += 1
        self.trains[train.train_id] = train
        self._emit_changed()
        return train

    def dispatch(self, train_id: str) -> OperationResult:
        """校验双站安全条件和发车进路后，占用发车股道。"""
        train = self.trains.get(train_id)
        if train is None:
            return self._failure(f"未知演示列车 {train_id}")
        if train.status is not DualTrainStatus.WAITING:
            return self._failure("列车不在待发状态")
        unsafe = self._unsafe_reason(train.direction)
        if unsafe:
            return self._failure(unsafe)

        origin = "A" if train.direction is RunningDirection.A_TO_B else "B"
        origin_controller = self._station_a if origin == "A" else self._station_b
        required_route = f"{origin}_DEPART"
        if required_route not in origin_controller.snapshot.active_route_ids:
            return self._failure(f"发车进路 {required_route} 尚未建立")

        entrance = self.ordered_sections(train.direction)[0]
        if not self._section_is_clear(entrance):
            return self._failure(f"入口区段 {entrance} 非空闲")
        written = self._track_input.set_state(
            entrance, TrackInputSource.TRAIN, TrackState.OCCUPIED
        )
        if not written.success:
            return self._failure(written.reason)

        train.section_id = entrance
        train.position_m = 0.0
        train.distance_ahead_m = self._lengths[entrance]
        train.current_speed_kmh = 0.0
        train.target_speed_kmh = 120.0
        train.safety_state = "发车条件满足"
        train.status = DualTrainStatus.READY
        self._emit_changed()
        return OperationResult(True, "列车已进入待启动状态")

    def start(self, train_id: str | None = None) -> OperationResult:
        """启动唯一 500 ms 时钟；可只启动指定列车，兼容无参数批量启动。"""
        if train_id is not None:
            train = self.trains.get(train_id)
            if train is None:
                return self._failure(f"未知演示列车 {train_id}")
            candidates = [train]
        else:
            candidates = [
                item
                for item in self.trains.values()
                if item.status in {DualTrainStatus.READY, DualTrainStatus.STOPPED}
            ]
        if not candidates:
            return self._failure("没有可启动的演示列车")
        self._manually_paused = False
        for train in candidates:
            unsafe = self._unsafe_reason(train.direction)
            if unsafe:
                return self._failure(unsafe)
            train.status = DualTrainStatus.RUNNING
            train.target_speed_kmh = 120.0
            train.current_speed_kmh = 120.0
            train.safety_state = "正常运行"
        self.timer.start()
        self._emit_changed()
        return OperationResult(True, "列车演示已启动")

    def reset_train(self, train_id: str) -> OperationResult:
        """只复位一列车，成功后回到 WAITING，允许再次派发。"""
        train = self.trains.get(train_id)
        if train is None:
            return self._failure(f"未知演示列车 {train_id}")
        self._manually_paused = False
        if train.section_id is not None:
            cleared = self._track_input.set_state(
                train.section_id, TrackInputSource.TRAIN, TrackState.CLEAR
            )
            if not cleared.success:
                train.current_speed_kmh = 0.0
                train.target_speed_kmh = 0.0
                train.status = DualTrainStatus.STOPPED
                train.safety_state = f"复位失败，保留占用：{cleared.reason}"
                self._emit_changed()
                return self._failure(cleared.reason)
        train.section_id = None
        train.position_m = 0.0
        train.current_speed_kmh = 0.0
        train.target_speed_kmh = 0.0
        train.distance_ahead_m = 0.0
        train.last_balise_id = None
        train.safety_state = "复位完成，可再次发车"
        train.status = DualTrainStatus.WAITING
        train.lifecycle_version += 1
        if not any(item.status is DualTrainStatus.RUNNING for item in self.trains.values()):
            self.timer.stop()
        self._emit_changed()
        return OperationResult(True, f"列车 {train_id} 已复位，可再次发车")

    def pause(self, reason: str = "人工暂停") -> None:
        """暂停时钟并把活动列车置为停车，不改变任何轨道占用。"""
        self._manually_paused = True
        self.timer.stop()
        for train in self.trains.values():
            if train.status in {DualTrainStatus.READY, DualTrainStatus.RUNNING}:
                self._stop_train(train, reason)
        self._emit_changed()

    def reset(self) -> OperationResult:
        """只清除 TRAIN 来源，人工、故障与分路不良输入保持不变。"""
        self.timer.stop()
        self._manually_paused = False
        failures: list[str] = []
        for section_id in self._sections:
            result = self._track_input.set_state(
                section_id, TrackInputSource.TRAIN, TrackState.CLEAR
            )
            if not result.success:
                failures.append(f"{section_id}：{result.reason}")
        for train in self.trains.values():
            train.current_speed_kmh = 0.0
            train.target_speed_kmh = 0.0
            if failures:
                # 复位不是原子事务。任一区段失败时，不得把列车位置从界面抹掉；
                # 对当前区段重新施加占用，抵消此前可能成功的清除操作。
                if train.section_id is not None:
                    restored = self._track_input.set_state(
                        train.section_id,
                        TrackInputSource.TRAIN,
                        TrackState.OCCUPIED,
                    )
                    if not restored.success:
                        failures.append(
                            f"{train.section_id} 保守占用恢复失败：{restored.reason}"
                        )
                train.safety_state = "复位不完整，保留列车占用"
                train.status = DualTrainStatus.STOPPED
                continue
            train.section_id = None
            train.position_m = 0.0
            train.distance_ahead_m = 0.0
            train.safety_state = "复位完成"
            train.status = DualTrainStatus.RESET
        self._emit_changed()
        if failures:
            return self._failure("；".join(failures))
        return OperationResult(True, "列车演示已复位")

    def shutdown(self) -> None:
        """窗口关闭前停止唯一时钟，不隐式清除轨道状态。"""
        self.timer.stop()

    def tick(self, elapsed_s: float) -> None:
        if elapsed_s <= 0:
            raise ValueError("列车演示步长必须为正数")
        simulated_elapsed_s = elapsed_s * self._speed_multiplier
        changed = False
        for train in self.trains.values():
            if train.status not in {DualTrainStatus.RUNNING, DualTrainStatus.STOPPED}:
                continue
            if self._manually_paused:
                continue
            unsafe = self._unsafe_reason(train.direction)
            if unsafe:
                self._stop_train(train, unsafe)
                changed = True
                continue
            if train.section_id is None:
                continue
            train.status = DualTrainStatus.RUNNING
            train.target_speed_kmh = 120.0
            train.current_speed_kmh = train.target_speed_kmh
            train.safety_state = "正常运行"
            train.position_m += train.current_speed_kmh / 3.6 * simulated_elapsed_s
            self._advance(train)
            changed = True
        if changed:
            self._emit_changed()

    def ordered_sections(self, direction: RunningDirection) -> tuple[str, ...]:
        """返回配置线路的物理顺序；反向运行时严格逆序。"""
        return (
            self._sections
            if direction is RunningDirection.A_TO_B
            else tuple(reversed(self._sections))
        )

    def _advance(self, train: DualTrainState) -> None:
        if train.section_id is None:
            return
        order = self.ordered_sections(train.direction)
        while train.section_id is not None:
            current = train.section_id
            length = self._lengths[current]
            self._update_last_balise(train)
            train.distance_ahead_m = max(0.0, length - train.position_m)
            if train.position_m < length:
                return
            next_index = order.index(current) + 1
            if next_index >= len(order):
                cleared = self._track_input.set_state(
                    current, TrackInputSource.TRAIN, TrackState.CLEAR
                )
                if not cleared.success:
                    train.position_m = length
                    self._stop_train(train, f"到达后区段出清失败：{cleared.reason}")
                    return
                train.section_id = None
                train.position_m = 0.0
                train.current_speed_kmh = 0.0
                train.target_speed_kmh = 0.0
                train.distance_ahead_m = 0.0
                train.safety_state = "安全到达"
                train.status = DualTrainStatus.ARRIVED
                self.timer.stop()
                return

            next_section = order[next_index]
            if not self._section_is_clear(next_section):
                train.position_m = length
                train.distance_ahead_m = 0.0
                self._stop_train(train, f"前方区段 {next_section} 非空闲")
                return

            arrival_route = self._arrival_route_for(train.direction, next_section)
            if arrival_route is not None:
                destination_controller, route_id = arrival_route
                if route_id not in destination_controller.snapshot.active_route_ids:
                    train.position_m = length
                    train.distance_ahead_m = 0.0
                    self._stop_train(
                        train,
                        f"目的站接车进路 {route_id} 未建立，列车安全停车",
                    )
                    return

            # 安全关键顺序：先确认下一段占用成功，再尝试清除当前段。
            occupied = self._track_input.set_state(
                next_section, TrackInputSource.TRAIN, TrackState.OCCUPIED
            )
            if not occupied.success:
                train.position_m = length
                self._stop_train(train, f"下一段占用失败：{occupied.reason}")
                return
            cleared = self._track_input.set_state(
                current, TrackInputSource.TRAIN, TrackState.CLEAR
            )
            if not cleared.success:
                train.position_m = length
                self._stop_train(train, f"上一段出清失败：{cleared.reason}")
                return

            train.position_m -= length
            train.section_id = next_section
            train.distance_ahead_m = max(
                0.0, self._lengths[next_section] - train.position_m
            )

    def _unsafe_reason(self, direction: RunningDirection) -> str | None:
        snapshots = (self._station_a.snapshot, self._station_b.snapshot)
        if any(item.connection_state is not ConnectionState.HEALTHY for item in snapshots):
            return "站间通信异常，列车安全停车"
        if any(item.direction_operation_locked for item in snapshots):
            return "区间方向锁闭，列车安全停车"
        if any(item.running_direction != direction.value for item in snapshots):
            return "A/B 方向不一致，列车安全停车"
        for section_id in self._sections:
            if section_id.startswith(("A_", "B_")):
                continue
            if (
                self._station_a.snapshot.tracks[section_id]
                is not self._station_b.snapshot.tracks[section_id]
            ):
                return f"共享区段 {section_id} 双站状态不一致，列车安全停车"
        return None

    def _section_is_clear(self, section_id: str) -> bool:
        if section_id.startswith("A_"):
            return self._station_a.snapshot.tracks[section_id] is TrackState.CLEAR
        if section_id.startswith("B_"):
            return self._station_b.snapshot.tracks[section_id] is TrackState.CLEAR
        return (
            self._station_a.snapshot.tracks[section_id] is TrackState.CLEAR
            and self._station_b.snapshot.tracks[section_id] is TrackState.CLEAR
        )

    def _arrival_route_for(
        self,
        direction: RunningDirection,
        next_section: str,
    ) -> tuple[TccController, str] | None:
        """在列车进入目的站接近区段前检查对应的接车进路。"""
        if direction is RunningDirection.A_TO_B and next_section == "B_T2":
            return self._station_b, "B_ARRIVE"
        if direction is RunningDirection.B_TO_A and next_section == "A_T2":
            return self._station_a, "A_ARRIVE"
        return None

    def _build_balise_index(self) -> dict[tuple[RunningDirection, str], tuple[object, ...]]:
        result: dict[tuple[RunningDirection, str], tuple[object, ...]] = {}
        for group in self._station_a.config.balise_groups.groups:
            direction = RunningDirection(group.direction.value)
            result[(direction, group.section_id)] = tuple(
                sorted(group.balises, key=lambda item: item.position_m)
            )
        return result

    def _update_last_balise(self, train: DualTrainState) -> None:
        if train.section_id is None:
            return
        balises = self._balises_by_section.get((train.direction, train.section_id), ())
        for balise in balises:
            if train.position_m >= balise.position_m:
                train.last_balise_id = balise.id

    @staticmethod
    def _stop_train(train: DualTrainState, reason: str) -> None:
        train.current_speed_kmh = 0.0
        train.target_speed_kmh = 0.0
        train.safety_state = reason
        train.status = DualTrainStatus.STOPPED

    def _failure(self, reason: str) -> OperationResult:
        self.operation_failed.emit(reason)
        return OperationResult(False, reason)

    def _emit_changed(self) -> None:
        self.trains_changed.emit(tuple(self.trains.values()))
