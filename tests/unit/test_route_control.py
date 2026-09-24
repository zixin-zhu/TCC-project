"""轻量进路控制测试。"""

from pathlib import Path

from app.core.enums import RunningDirection, TrackInputSource, TrackState
from app.core.models import StationRuntimeState
from app.domain.route_control import RouteControlService
from app.infrastructure.config_loader import load_project_config


ROOT = Path(__file__).resolve().parents[2]


def _runtime() -> StationRuntimeState:
    config = load_project_config(ROOT / "configs", "A")
    return StationRuntimeState.create(
        "A", (section.id for section in config.topology.sections)
    )


def test_departure_route_establishes_when_direction_and_sections_are_safe() -> None:
    """防止合法发车进路被无条件拒绝。"""
    config = load_project_config(ROOT / "configs", "A")
    runtime = _runtime()
    service = RouteControlService(config.topology)

    result = service.establish("A_DEPART", runtime)

    assert result.success is True
    assert result.reason == "进路建立成功"
    assert runtime.active_route_ids == {"A_DEPART"}
    assert runtime.state_version == 1


def test_route_with_opposite_direction_is_rejected_without_state_change() -> None:
    """防止建立与当前区间方向相反的发车进路。"""
    config = load_project_config(ROOT / "configs", "A")
    runtime = _runtime()
    runtime.running_direction = RunningDirection.A_TO_B

    result = RouteControlService(config.topology).establish("B_DEPART", runtime)

    assert result.success is False
    assert "方向不符" in result.reason
    assert runtime.active_route_ids == set()
    assert runtime.state_version == 0


def test_occupied_section_rejects_route_with_exact_reason() -> None:
    """防止占用区段仍能建立进路。"""
    config = load_project_config(ROOT / "configs", "A")
    runtime = _runtime()
    runtime.apply_track_input(
        "A_T2", TrackInputSource.OPERATOR, TrackState.OCCUPIED
    )
    before = runtime.state_version

    result = RouteControlService(config.topology).establish("A_DEPART", runtime)

    assert result.success is False
    assert result.reason == "区段 A_T2 状态为 OCCUPIED"
    assert runtime.state_version == before


def test_direction_safety_lock_rejects_route_without_state_change() -> None:
    """通信或方向投影未确认时，禁止任何新进路进入不一致区间。"""
    config = load_project_config(ROOT / "configs", "A")
    runtime = _runtime()
    runtime.direction_operation_locked = True
    before = runtime.state_version

    result = RouteControlService(config.topology).establish("A_DEPART", runtime)

    assert result.success is False
    assert result.reason == "区间方向未确认，进路已安全锁闭"
    assert runtime.active_route_ids == set()
    assert runtime.state_version == before
