"""不依赖联锁设备的轻量教学进路控制。"""

from typing import Dict

from app.core.enums import TrackState
from app.core.models import OperationResult, RouteConfig, StationRuntimeState, TopologyConfig


class RouteControlService:
    """负责进路建立条件和活动进路集合，不负责轨道编码。"""

    def __init__(self, topology: TopologyConfig):
        self.topology = topology
        self._routes: Dict[str, RouteConfig] = {
            route.id: route for route in topology.routes
        }

    def establish(
        self, route_id: str, runtime: StationRuntimeState
    ) -> OperationResult:
        """检查方向、区段和冲突后建立进路。"""
        route = self._routes.get(route_id)
        if route is None:
            return OperationResult(False, f"未知进路 {route_id}")
        if route_id in runtime.active_route_ids:
            return OperationResult(True, "进路已建立")
        if route.direction is not runtime.running_direction:
            return OperationResult(
                False,
                f"进路方向不符：当前 {runtime.running_direction.value}，"
                f"进路要求 {route.direction.value}",
            )
        for section_id in route.sections:
            state = runtime.effective_track_state(section_id)
            if state is not TrackState.CLEAR:
                return OperationResult(
                    False, f"区段 {section_id} 状态为 {state.value}"
                )
        new_sections = set(route.sections)
        for active_id in runtime.active_route_ids:
            active = self._routes[active_id]
            if new_sections.intersection(active.sections):
                return OperationResult(False, f"与活动进路 {active_id} 冲突")
        runtime.active_route_ids.add(route_id)
        runtime.state_version += 1
        return OperationResult(True, "进路建立成功")

    def cancel(self, route_id: str, runtime: StationRuntimeState) -> OperationResult:
        """取消活动进路；重复取消保持幂等。"""
        if route_id not in self._routes:
            return OperationResult(False, f"未知进路 {route_id}")
        if route_id not in runtime.active_route_ids:
            return OperationResult(True, "进路未建立")
        runtime.active_route_ids.remove(route_id)
        runtime.state_version += 1
        return OperationResult(True, "进路取消成功")
