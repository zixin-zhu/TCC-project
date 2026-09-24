"""配置驱动的区间/站内轨道电路教学编码。"""

from typing import Dict, List, Optional, Sequence, Tuple

from app.core.enums import RouteType, RunningDirection, SectionKind, TrackCode, TrackState
from app.core.models import (
    CodingRules,
    PeerSnapshot,
    StationRuntimeState,
    TopologyConfig,
    TrackCodingResult,
)


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
    ) -> List[TrackCodingResult]:
        """重新计算全部区段；邻站信息不可用时对区间统一保护。"""
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
                direction_order, runtime, peer_snapshot
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
    ) -> Dict[str, TrackCodingResult]:
        states = [runtime.effective_track_state(section_id) for section_id in ordered_ids]
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
            if state is not TrackState.CLEAR:
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
