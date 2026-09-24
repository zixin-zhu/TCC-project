"""阶段 1 的领域与配置数据模型。"""

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Tuple

from app.core.enums import (
    BaliseDirection,
    BaliseKind,
    NetworkRole,
    RouteType,
    RunningDirection,
    SectionKind,
    TrackInputSource,
    TrackState,
)
from app.core.exceptions import UnknownTrackSectionError


@dataclass(frozen=True)
class NetworkConfig:
    role: NetworkRole
    host: str
    port: int
    peer_station_id: str


@dataclass(frozen=True)
class StationConfig:
    station_id: str
    station_name: str
    network: NetworkConfig


@dataclass(frozen=True)
class TrackSectionConfig:
    id: str
    name: str
    kind: SectionKind
    length_m: float


@dataclass(frozen=True)
class SignalConfig:
    id: str
    protects_section: str


@dataclass(frozen=True)
class RouteConfig:
    id: str
    type: RouteType
    direction: RunningDirection
    sections: Tuple[str, ...]


@dataclass(frozen=True)
class BoundaryConfig:
    id: str
    local_section: str
    peer_section: str


@dataclass(frozen=True)
class TopologyConfig:
    sections: Tuple[TrackSectionConfig, ...]
    signals: Tuple[SignalConfig, ...]
    routes: Tuple[RouteConfig, ...]
    boundaries: Tuple[BoundaryConfig, ...]


@dataclass(frozen=True)
class LeuPortConfig:
    id: str


@dataclass(frozen=True)
class BaliseConfig:
    id: str
    kind: BaliseKind
    order: int
    position_m: float
    fixed_telegram_id: Optional[str] = None
    leu_port_id: Optional[str] = None
    default_telegram_id: Optional[str] = None


@dataclass(frozen=True)
class BaliseGroupConfig:
    id: str
    direction: BaliseDirection
    section_id: str
    balises: Tuple[BaliseConfig, ...]


@dataclass(frozen=True)
class BaliseGroupsConfig:
    telegram_templates: Tuple[str, ...]
    leu_ports: Tuple[LeuPortConfig, ...]
    groups: Tuple[BaliseGroupConfig, ...]


@dataclass(frozen=True)
class ProjectConfig:
    station: StationConfig
    topology: TopologyConfig
    balise_groups: BaliseGroupsConfig


@dataclass(frozen=True)
class StateChange:
    """一次输入操作引起的有效状态变化。"""

    section_id: str
    source: TrackInputSource
    previous: TrackState
    current: TrackState
    changed: bool
    state_version: int


_STATE_PRIORITY: Mapping[TrackState, int] = {
    TrackState.CLEAR: 0,
    TrackState.OCCUPIED: 1,
    TrackState.SHUNT_BAD: 2,
    TrackState.FAULT_OCCUPIED: 3,
}


@dataclass
class StationRuntimeState:
    """单站运行状态。

    同一区段可能同时收到列车、人工和故障输入。分别保存来源，才能保证
    列车出清不会误删仍然生效的人工故障。
    """

    station_id: str
    track_inputs: Dict[str, Dict[TrackInputSource, TrackState]]
    state_version: int = 0

    @classmethod
    def create(
        cls, station_id: str, section_ids: Iterable[str]
    ) -> "StationRuntimeState":
        return cls(
            station_id=station_id,
            track_inputs={section_id: {} for section_id in section_ids},
        )

    def effective_track_state(self, section_id: str) -> TrackState:
        """按保护优先级合成区段的有效状态。"""
        if section_id not in self.track_inputs:
            raise UnknownTrackSectionError(f"未知轨道区段：{section_id}")
        states = self.track_inputs[section_id].values()
        return max(states, key=_STATE_PRIORITY.__getitem__, default=TrackState.CLEAR)

    def apply_track_input(
        self,
        section_id: str,
        source: TrackInputSource,
        state: TrackState,
    ) -> StateChange:
        """写入一个来源，并仅在有效状态改变时增加状态版本。"""
        if section_id not in self.track_inputs:
            raise UnknownTrackSectionError(f"未知轨道区段：{section_id}")
        previous = self.effective_track_state(section_id)
        source_inputs = self.track_inputs[section_id]
        if state is TrackState.CLEAR:
            source_inputs.pop(source, None)
        else:
            source_inputs[source] = state
        current = self.effective_track_state(section_id)
        changed = current is not previous
        if changed:
            self.state_version += 1
        return StateChange(
            section_id=section_id,
            source=source,
            previous=previous,
            current=current,
            changed=changed,
            state_version=self.state_version,
        )
