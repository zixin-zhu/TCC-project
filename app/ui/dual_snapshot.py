"""A/B 双站快照的只读聚合模型。"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QObject, pyqtSignal

from app.core.enums import ConnectionState, RunningDirection, TrackState
from app.services.alarm_service import AlarmLevel
from app.services.tcc_controller import TccSnapshot


@dataclass(frozen=True)
class SectionConsistency:
    """一个线路区段在双站视角下的显示来源与一致性。"""

    section_id: str
    station_a_state: TrackState
    station_b_state: TrackState
    consistent: bool
    display_state: TrackState | None
    reason: str


@dataclass(frozen=True)
class DualStationSnapshot:
    """供总览组件消费的不可变双站视图模型。"""

    station_a: TccSnapshot
    station_b: TccSnapshot
    authoritative_direction: RunningDirection
    direction_consistent: bool
    communication_healthy: bool
    operation_locked: bool
    sections: tuple[SectionConsistency, ...]
    active_alarm_count: int
    critical_alarm_count: int


class DualStationSnapshotAggregator(QObject):
    """组合两站快照；只读计算，不修改控制器或生成业务版本。"""

    snapshot_changed = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._station_a: TccSnapshot | None = None
        self._station_b: TccSnapshot | None = None
        self._snapshot: DualStationSnapshot | None = None

    @property
    def snapshot(self) -> DualStationSnapshot | None:
        return self._snapshot

    def update_a(self, snapshot: TccSnapshot) -> None:
        """接收 A 站快照；相同快照不制造无意义界面刷新。"""
        if snapshot.station_id != "A":
            raise ValueError("update_a 只接受 A 站快照")
        if (
            self._station_a is not None
            and snapshot.state_version < self._station_a.state_version
        ):
            # 连接与告警可在同一业务版本内更新，所以只拒绝严格回退版本。
            return
        if snapshot == self._station_a:
            return
        self._station_a = snapshot
        self._rebuild()

    def update_b(self, snapshot: TccSnapshot) -> None:
        """接收 B 站快照；两站到齐前不发布残缺模型。"""
        if snapshot.station_id != "B":
            raise ValueError("update_b 只接受 B 站快照")
        if (
            self._station_b is not None
            and snapshot.state_version < self._station_b.state_version
        ):
            return
        if snapshot == self._station_b:
            return
        self._station_b = snapshot
        self._rebuild()

    def _rebuild(self) -> None:
        station_a = self._station_a
        station_b = self._station_b
        if station_a is None or station_b is None:
            return

        direction = RunningDirection(station_a.running_direction)
        direction_consistent = (
            station_a.running_direction == station_b.running_direction
        )
        communication_healthy = (
            station_a.connection_state is ConnectionState.HEALTHY
            and station_b.connection_state is ConnectionState.HEALTHY
        )
        sections = self._aggregate_sections(station_a, station_b)
        shared_inconsistent = any(
            not item.consistent
            for item in sections
            if not item.section_id.startswith(("A_", "B_"))
        )
        alarms = tuple(station_a.alarms) + tuple(station_b.alarms)
        active_alarms = tuple(item for item in alarms if item.active)
        model = DualStationSnapshot(
            station_a=station_a,
            station_b=station_b,
            authoritative_direction=direction,
            direction_consistent=direction_consistent,
            communication_healthy=communication_healthy,
            operation_locked=(
                not communication_healthy
                or not direction_consistent
                or station_a.direction_operation_locked
                or station_b.direction_operation_locked
                or shared_inconsistent
            ),
            sections=sections,
            active_alarm_count=len(active_alarms),
            critical_alarm_count=sum(
                item.level is AlarmLevel.CRITICAL for item in active_alarms
            ),
        )
        if model == self._snapshot:
            return
        self._snapshot = model
        self.snapshot_changed.emit(model)

    @staticmethod
    def _aggregate_sections(
        station_a: TccSnapshot, station_b: TccSnapshot
    ) -> tuple[SectionConsistency, ...]:
        section_ids = tuple(station_a.tracks)
        if set(section_ids) != set(station_b.tracks):
            raise ValueError("A/B 快照的线路区段集合不一致")

        result: list[SectionConsistency] = []
        for section_id in section_ids:
            state_a = station_a.tracks[section_id]
            state_b = station_b.tracks[section_id]
            if section_id.startswith("A_"):
                result.append(
                    SectionConsistency(
                        section_id,
                        state_a,
                        state_b,
                        True,
                        state_a,
                        "A站管辖区段，显示 A 站状态",
                    )
                )
                continue
            if section_id.startswith("B_"):
                result.append(
                    SectionConsistency(
                        section_id,
                        state_a,
                        state_b,
                        True,
                        state_b,
                        "B站管辖区段，显示 B 站状态",
                    )
                )
                continue
            consistent = state_a is state_b
            result.append(
                SectionConsistency(
                    section_id,
                    state_a,
                    state_b,
                    consistent,
                    state_a if consistent else None,
                    "双站状态一致"
                    if consistent
                    else f"双站不一致：A={state_a.value}，B={state_b.value}",
                )
            )
        return tuple(result)
