"""阶段 2：附录 1 轨道状态、防护顺序和编码故障测试。"""

from pathlib import Path

from app.core.enums import RunningDirection, TrackCode, TrackInputSource, TrackState
from app.core.models import PeerSnapshot, StationRuntimeState, TrackCodingResult
from app.domain.signal_control import SignalControlService
from app.domain.track_circuit import TrackCircuitCodingService, TrackProtectionService
from app.infrastructure.config_loader import load_coding_rules, load_project_config


ROOT = Path(__file__).resolve().parents[2]


def _setup() -> tuple[object, StationRuntimeState, TrackCircuitCodingService]:
    config = load_project_config(ROOT / "configs", "A")
    runtime = StationRuntimeState.create(
        "A", (section.id for section in config.topology.sections)
    )
    return (
        config,
        runtime,
        TrackCircuitCodingService(
            config.topology,
            load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        ),
    )


def _peer() -> PeerSnapshot:
    return PeerSnapshot(
        "B",
        {f"Q{index}": TrackState.CLEAR for index in range(1, 5)},
        1,
        9_500,
    )


def test_fault_occupancy_cannot_release_protection_before_rear_section_clears() -> None:
    protection = TrackProtectionService(("Q1", "Q2", "Q3", "Q4"))

    protection.observe("Q2", TrackState.FAULT_OCCUPIED)
    protection.observe("Q2", TrackState.CLEAR)
    assert protection.snapshot.active is True

    protection.observe("Q1", TrackState.CLEAR)
    protection.observe("Q2", TrackState.CLEAR)
    assert protection.snapshot.active is False


def test_two_adjacent_shunt_bad_sections_protect_the_forward_section_with_hu() -> None:
    config, runtime, service = _setup()
    runtime.apply_track_input("Q2", TrackInputSource.SHUNT, TrackState.SHUNT_BAD)
    runtime.apply_track_input("Q3", TrackInputSource.SHUNT, TrackState.SHUNT_BAD)

    results = service.recalculate_all(runtime, _peer(), now_ms=10_000)
    result_q1 = next(item for item in results if item.section_id == "Q1")

    assert result_q1.code is TrackCode.HU
    assert result_q1.protected is True
    assert "分路不良" in result_q1.reason


def test_coding_service_failure_returns_offline_and_signal_stays_red() -> None:
    config, runtime, service = _setup()
    results = service.recalculate_all(
        runtime, _peer(), now_ms=10_000, coding_available=False
    )
    codes = {item.section_id: item for item in results}

    assert codes["Q1"].code is TrackCode.OFFLINE
    assert codes["Q1"].protected is True

    signal = next(
        item
        for item in SignalControlService(config.topology).recalculate(runtime, results)
        if item.signal_id == "SA"
    )
    assert signal.aspect.value == "RED"
    assert signal.protected is True
    assert "离线" in signal.reason
