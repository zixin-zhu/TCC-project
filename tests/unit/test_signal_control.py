"""区间信号点灯和继电器结果测试。"""

from pathlib import Path

import pytest

from app.core.enums import RunningDirection, SignalAspect, TrackCode
from app.core.models import StationRuntimeState, TrackCodingResult
from app.domain.signal_control import SignalControlService
from app.infrastructure.config_loader import load_project_config


ROOT = Path(__file__).resolve().parents[2]


def _coding(section_id: str, code: TrackCode) -> TrackCodingResult:
    return TrackCodingResult(
        section_id=section_id,
        direction=RunningDirection.A_TO_B,
        code=code,
        reason="测试码序",
        looked_ahead_sections=(),
        protected=code is TrackCode.HU,
        state_version=0,
    )


@pytest.mark.parametrize(
    "code, aspect, relays",
    [
        (TrackCode.HU, SignalAspect.RED, (True, False, False)),
        (TrackCode.U, SignalAspect.YELLOW, (False, True, False)),
        (TrackCode.LU, SignalAspect.DOUBLE_YELLOW, (False, True, True)),
        (TrackCode.L5, SignalAspect.GREEN, (False, False, True)),
    ],
)
def test_code_maps_to_unique_aspect_and_relays(code, aspect, relays) -> None:
    """防止灯色和 HJ/UJ/LJ 出现互相矛盾的组合。"""
    config = load_project_config(ROOT / "configs", "A")
    runtime = StationRuntimeState.create(
        "A", (section.id for section in config.topology.sections)
    )
    results = SignalControlService(config.topology).recalculate(
        runtime, [_coding("Q1", code)]
    )
    result = next(item for item in results if item.signal_id == "SA")

    assert result.aspect is aspect
    assert (result.relay_hj, result.relay_uj, result.relay_lj) == relays
    assert result.reason


def test_signal_for_non_running_direction_stays_red() -> None:
    """防止反方向信号跟随当前方向码序错误开放。"""
    config = load_project_config(ROOT / "configs", "A")
    runtime = StationRuntimeState.create(
        "A", (section.id for section in config.topology.sections)
    )
    runtime.running_direction = RunningDirection.A_TO_B

    results = SignalControlService(config.topology).recalculate(
        runtime, [_coding("Q4", TrackCode.L5)]
    )
    result = next(item for item in results if item.signal_id == "SB")

    assert result.aspect is SignalAspect.RED
    assert "非运行方向" in result.reason


def test_red_lamp_failure_produces_critical_protection_result() -> None:
    """防止要求显示红灯时的红灯断丝被当作普通红灯。"""
    config = load_project_config(ROOT / "configs", "A")
    runtime = StationRuntimeState.create(
        "A", (section.id for section in config.topology.sections)
    )
    runtime.failed_red_lamp_ids.add("SA")

    results = SignalControlService(config.topology).recalculate(
        runtime, [_coding("Q1", TrackCode.HU)]
    )
    result = next(item for item in results if item.signal_id == "SA")

    assert result.aspect is SignalAspect.RED_LAMP_FAILURE
    assert result.protected is True
    assert result.alarm_level == "CRITICAL"
    assert (result.relay_hj, result.relay_uj, result.relay_lj) == (False, False, False)


def test_direction_safety_lock_forces_all_signals_to_red() -> None:
    """方向事务或失联期间，即使码序允许也不得开放信号。"""
    config = load_project_config(ROOT / "configs", "A")
    runtime = StationRuntimeState.create(
        "A", (section.id for section in config.topology.sections)
    )
    runtime.direction_operation_locked = True

    results = SignalControlService(config.topology).recalculate(
        runtime, [_coding("Q1", TrackCode.L5), _coding("Q4", TrackCode.L5)]
    )

    assert all(result.aspect is SignalAspect.RED for result in results)
    assert all(result.protected for result in results)
    assert all("方向安全锁闭" in result.reason for result in results)
