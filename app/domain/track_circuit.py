"""配置驱动的区间/站内轨道电路教学编码。"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.core.enums import RouteType, RunningDirection, SectionKind, TrackCode, TrackState
from app.core.models import (
    CodingRules,
    PeerSnapshot,
    StationRuntimeState,
    TopologyConfig,
    TrackCodingResult,
)


@dataclass(frozen=True)
class TrackProtectionSnapshot:
    """附录 1 占用/出清顺序检查结果。"""

    active: bool
    protected_sections: Tuple[str, ...]
    reason: str


class TrackProtectionService:
    """按“故障区段占用→后方出清→故障区段出清”维护安全防护。

    服务只保存事件顺序，不直接修改 TCC 运行态；编码层消费
    ``snapshot.protected_sections`` 并输出 HU，便于单元测试和审计。
    """

    def __init__(self, ordered_sections: Iterable[str]) -> None:
        self._ordered_sections = tuple(ordered_sections)
        if not self._ordered_sections or len(set(self._ordered_sections)) != len(
            self._ordered_sections
        ):
            raise ValueError("防护区段顺序必须非空且不重复")
        self._fault_sections: Set[str] = set()
        self._rear_clear_sections: Dict[str, Set[str]] = {}

    @property
    def snapshot(self) -> TrackProtectionSnapshot:
        protected: Set[str] = set()
        for fault_section in self._fault_sections:
            index = self._ordered_sections.index(fault_section)
            protected.update(self._ordered_sections[: index + 1])
        if not protected:
            return TrackProtectionSnapshot(False, (), "无顺序异常防护")
        return TrackProtectionSnapshot(
            True,
            tuple(section for section in self._ordered_sections if section in protected),
            "故障占用未按规定完成后方区段出清，保持 HU 防护",
        )

    def observe(self, section_id: str, state: TrackState) -> TrackProtectionSnapshot:
        """记录一个有效区段状态，并返回更新后的防护快照。"""
        if section_id not in self._ordered_sections:
            raise ValueError(f"未知防护区段：{section_id}")
        if state is TrackState.FAULT_OCCUPIED:
            self._fault_sections.add(section_id)
            self._rear_clear_sections[section_id] = set()
            return self.snapshot
        if state is TrackState.CLEAR:
            section_index = self._ordered_sections.index(section_id)
            for fault_section in tuple(self._fault_sections):
                fault_index = self._ordered_sections.index(fault_section)
                rear = self._rear_clear_sections.setdefault(fault_section, set())
                if section_index < fault_index:
                    rear.add(section_id)
                elif section_id == fault_section:
                    required = set(self._ordered_sections[:fault_index])
                    if required.issubset(rear):
                        self._fault_sections.remove(fault_section)
                        self._rear_clear_sections.pop(fault_section, None)
            return self.snapshot
        # 故障区段后的再次占用使此前的“已出清”证据失效。
        for fault_section in self._fault_sections:
            if self._ordered_sections.index(section_id) < self._ordered_sections.index(
                fault_section
            ):
                self._rear_clear_sections.setdefault(fault_section, set()).discard(
                    section_id
                )
        return self.snapshot


class TrackCircuitCodingService:
    """根据方向、占用、进路和邻站边界生成可解释码序。"""

    def __init__(self, topology: TopologyConfig, rules: CodingRules):
        self.topology = topology
        self.rules = rules

    def recalculate_all(
        self,
        runtime: StationRuntimeState,
        peer_snapshot: Optional[PeerSnapshot],
        now_ms: int,
        *,
        coding_available: bool = True,
        protection_sections: Iterable[str] = (),
    ) -> List[TrackCodingResult]:
        """重新计算全部区段；邻站信息不可用时对区间统一保护。"""
        if not coding_available:
            return [
                TrackCodingResult(
                    section_id=section.id,
                    direction=runtime.running_direction,
                    code=TrackCode.OFFLINE,
                    reason="轨道编码服务离线，停止编码输出并保持安全防护",
                    looked_ahead_sections=(),
                    protected=True,
                    state_version=runtime.state_version,
                )
                for section in self.topology.sections
            ]
        block_ids = [
            section.id
            for section in self.topology.sections
            if section.kind is SectionKind.BLOCK
        ]
        direction_order = (
            block_ids
            if runtime.running_direction is RunningDirection.A_TO_B
            else list(reversed(block_ids))
        )
        if peer_snapshot is None or not peer_snapshot.is_fresh(
            now_ms, self.rules.peer_timeout_ms
        ):
            block_results = {
                section_id: TrackCodingResult(
                    section_id=section_id,
                    direction=runtime.running_direction,
                    code=TrackCode.HU,
                    reason="邻站边界快照缺失或过期，采用保护码",
                    looked_ahead_sections=(),
                    protected=True,
                    state_version=runtime.state_version,
                )
                for section_id in block_ids
            }
        else:
            block_results = self._calculate_blocks(
                direction_order,
                runtime,
                peer_snapshot,
                protection_sections=frozenset(protection_sections),
            )

        results: List[TrackCodingResult] = []
        for section in self.topology.sections:
            if section.kind is SectionKind.BLOCK:
                results.append(block_results[section.id])
            else:
                results.append(self._calculate_station(section.id, runtime, block_results))
        return results

    def _calculate_blocks(
        self,
        ordered_ids: Sequence[str],
        runtime: StationRuntimeState,
        peer_snapshot: PeerSnapshot,
        *,
        protection_sections: Set[str] | frozenset[str] = frozenset(),
    ) -> Dict[str, TrackCodingResult]:
        states = [runtime.effective_track_state(section_id) for section_id in ordered_ids]
        shunt_protection = set(protection_sections)
        run_start = 0
        while run_start < len(states):
            if states[run_start] is not TrackState.SHUNT_BAD:
                run_start += 1
                continue
            run_end = run_start
            while run_end < len(states) and states[run_end] is TrackState.SHUNT_BAD:
                run_end += 1
            if run_end - run_start >= 2:
                shunt_protection.update(ordered_ids[:run_end])
            run_start = run_end
        # 只读取当前运行方向最前端对应的邻站边界。快照可以同时携带两端
        # 状态，若使用“任一占用”会让运行后方的无关边界错误降低全线码序。
        forward_boundary_id = ordered_ids[-1]
        peer_hazard = (
            peer_snapshot.boundary_states.get(
                forward_boundary_id, TrackState.FAULT_OCCUPIED
            )
            is not TrackState.CLEAR
        )
        results: Dict[str, TrackCodingResult] = {}
        for index, section_id in enumerate(ordered_ids):
            state = states[index]
            looked = tuple(ordered_ids[index + 1 :])
            if section_id in shunt_protection:
                code = TrackCode.HU
                reason = "连续分路不良或顺序防护未解除，向前设置 HU 防护码"
                protected = True
            elif state is not TrackState.CLEAR:
                code = TrackCode.HU
                reason = f"本区段状态为 {state.value}，采用保护码"
                protected = True
            else:
                hazard_index = next(
                    (
                        candidate
                        for candidate in range(index + 1, len(states))
                        if states[candidate] is not TrackState.CLEAR
                    ),
                    None,
                )
                if hazard_index is None and peer_hazard:
                    hazard_index = len(states)
                if hazard_index is not None:
                    distance = hazard_index - index
                    rule_index = min(distance - 1, len(self.rules.restrictive_codes) - 1)
                    code = self.rules.restrictive_codes[rule_index]
                    reason = f"运行前方第 {distance} 个位置存在限制，发送 {code.value}"
                    protected = False
                else:
                    ahead_count = len(states) - index - 1
                    rule_index = min(ahead_count, len(self.rules.all_clear_codes) - 1)
                    code = self.rules.all_clear_codes[rule_index]
                    reason = f"前方连续空闲 {ahead_count} 个本地区段，发送 {code.value}"
                    protected = False
            results[section_id] = TrackCodingResult(
                section_id=section_id,
                direction=runtime.running_direction,
                code=code,
                reason=reason,
                looked_ahead_sections=looked,
                protected=protected,
                state_version=runtime.state_version,
            )
        return results

    def _calculate_station(
        self,
        section_id: str,
        runtime: StationRuntimeState,
        block_results: Dict[str, TrackCodingResult],
    ) -> TrackCodingResult:
        state = runtime.effective_track_state(section_id)
        if state is not TrackState.CLEAR:
            code = TrackCode.HU
            reason = f"站内区段状态为 {state.value}，采用保护码"
            protected = True
        else:
            matching_route = next(
                (
                    route
                    for route in self.topology.routes
                    if route.id in runtime.active_route_ids
                    and route.direction is runtime.running_direction
                    and section_id in route.sections
                ),
                None,
            )
            if matching_route is None:
                code = TrackCode.DETECT
                reason = "站内无活动进路，发送检测码"
                protected = False
            else:
                route_blocks = [
                    item for item in matching_route.sections if item in block_results
                ]
                if matching_route.type is RouteType.DEPARTURE and route_blocks:
                    code = block_results[route_blocks[0]].code
                    reason = f"发车进路 {matching_route.id} 跟随首个区间码 {code.value}"
                else:
                    code = TrackCode.DETECT
                    reason = f"接车进路 {matching_route.id} 使用站内检测码"
                protected = code is TrackCode.HU
        return TrackCodingResult(
            section_id=section_id,
            direction=runtime.running_direction,
            code=code,
            reason=reason,
            looked_ahead_sections=(),
            protected=protected,
            state_version=runtime.state_version,
        )
