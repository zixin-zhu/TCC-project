"""区间/站内轨道电路教学编码测试。"""

from pathlib import Path

import pytest

from app.core.enums import RunningDirection, TrackCode, TrackInputSource, TrackState
from app.core.models import PeerSnapshot, StationRuntimeState
from app.domain.route_control import RouteControlService
from app.domain.track_circuit import TrackCircuitCodingService
from app.infrastructure.config_loader import load_coding_rules, load_project_config


ROOT = Path(__file__).resolve().parents[2]


def _setup(direction: RunningDirection = RunningDirection.A_TO_B):
    config = load_project_config(ROOT / "configs", "A")
    runtime = StationRuntimeState.create(
        "A", (section.id for section in config.topology.sections)
    )
    runtime.running_direction = direction
    rules = load_coding_rules(ROOT / "configs" / "coding_rules.json")
    service = TrackCircuitCodingService(config.topology, rules)
    return config, runtime, service


def _fresh_peer(state: TrackState = TrackState.CLEAR) -> PeerSnapshot:
    return PeerSnapshot(
        station_id="B",
        boundary_states={"Q4": state, "Q1": state},
        state_version=1,
        received_at_ms=9_500,
    )


def _codes(results):
    return {item.section_id: item.code for item in results}


@pytest.mark.parametrize(
    "direction, expected",
    [
        (
            RunningDirection.A_TO_B,
            {"Q1": TrackCode.L, "Q2": TrackCode.L2, "Q3": TrackCode.L3, "Q4": TrackCode.L5},
        ),
        (
            RunningDirection.B_TO_A,
            {"Q1": TrackCode.L5, "Q2": TrackCode.L3, "Q3": TrackCode.L2, "Q4": TrackCode.L},
        ),
    ],
)
def test_all_clear_codes_are_directionally_symmetric(direction, expected) -> None:
    """防止反向运行仍沿用正向遍历顺序。"""
    _, runtime, service = _setup(direction)

    results = service.recalculate_all(runtime, _fresh_peer(), now_ms=10_000)

    assert {key: _codes(results)[key] for key in expected} == expected
    assert all(item.reason for item in results)


def test_occupied_section_propagates_restrictive_codes_backwards() -> None:
    """防止占用只改变本区段而不影响后方码序。"""
    _, runtime, service = _setup()
    runtime.apply_track_input("Q3", TrackInputSource.TRAIN, TrackState.OCCUPIED)

    results = service.recalculate_all(runtime, _fresh_peer(), now_ms=10_000)
    codes = _codes(results)

    assert codes["Q3"] is TrackCode.HU
    assert codes["Q2"] is TrackCode.U
    assert codes["Q1"] is TrackCode.LU
    assert next(item for item in results if item.section_id == "Q3").protected is True


@pytest.mark.parametrize("state", [TrackState.FAULT_OCCUPIED, TrackState.SHUNT_BAD])
def test_abnormal_track_state_forces_protection(state: TrackState) -> None:
    """防止故障状态被当作普通空闲编码。"""
    _, runtime, service = _setup()
    runtime.apply_track_input("Q2", TrackInputSource.FAULT, state)

    result = next(
        item
        for item in service.recalculate_all(runtime, _fresh_peer(), now_ms=10_000)
        if item.section_id == "Q2"
    )

    assert result.code is TrackCode.HU
    assert result.protected is True
    assert state.value in result.reason


def test_peer_boundary_occupied_restricts_last_local_sections() -> None:
    """防止把邻站边界占用错误地视为线路终端空闲。"""
    _, runtime, service = _setup()

    codes = _codes(
        service.recalculate_all(
            runtime, _fresh_peer(TrackState.OCCUPIED), now_ms=10_000
        )
    )

    assert codes["Q4"] is TrackCode.U
    assert codes["Q3"] is TrackCode.LU


def test_occupied_boundary_behind_running_direction_does_not_restrict_codes() -> None:
    """防止快照中运行后方的占用错误影响前方码序。"""
    _, runtime, service = _setup(RunningDirection.A_TO_B)
    peer = PeerSnapshot(
        station_id="B",
        boundary_states={"Q4": TrackState.CLEAR, "Q1": TrackState.OCCUPIED},
        state_version=2,
        received_at_ms=9_500,
    )

    codes = _codes(service.recalculate_all(runtime, peer, now_ms=10_000))

    assert codes["Q4"] is TrackCode.L5
    assert codes["Q3"] is TrackCode.L3


def test_stale_peer_snapshot_forces_all_block_sections_to_protection() -> None:
    """防止通信过期后继续沿用旧边界空闲状态。"""
    _, runtime, service = _setup()
    stale = PeerSnapshot(
        station_id="B",
        boundary_states={"Q4": TrackState.CLEAR},
        state_version=1,
        received_at_ms=1_000,
    )

    results = service.recalculate_all(runtime, stale, now_ms=10_000)
    blocks = [item for item in results if item.section_id.startswith("Q")]

    assert {item.code for item in blocks} == {TrackCode.HU}
    assert all(item.protected and "过期" in item.reason for item in blocks)


def test_station_sections_use_detect_without_route_and_departure_code_with_route() -> None:
    """防止站内区段沿用区间数组位置硬编码。"""
    config, runtime, service = _setup()
    peer = _fresh_peer()

    before = _codes(service.recalculate_all(runtime, peer, now_ms=10_000))
    RouteControlService(config.topology).establish("A_DEPART", runtime)
    after = _codes(service.recalculate_all(runtime, peer, now_ms=10_000))

    assert before["A_T1"] is TrackCode.DETECT
    assert before["A_T2"] is TrackCode.DETECT
    assert after["A_T1"] is after["Q1"]
    assert after["A_T2"] is after["Q1"]
