"""统一运行状态的行为测试。"""

import pytest

from app.core.enums import TrackInputSource, TrackState
from app.core.exceptions import UnknownTrackSectionError
from app.core.models import StationRuntimeState


def test_fault_input_has_priority_and_is_not_cleared_by_train_release() -> None:
    """防止列车出清错误地覆盖仍然存在的轨道故障。"""
    state = StationRuntimeState.create("A", ["Q1"])

    first = state.apply_track_input(
        "Q1", TrackInputSource.TRAIN, TrackState.OCCUPIED
    )
    fault = state.apply_track_input(
        "Q1", TrackInputSource.FAULT, TrackState.FAULT_OCCUPIED
    )
    release = state.apply_track_input(
        "Q1", TrackInputSource.TRAIN, TrackState.CLEAR
    )

    assert first.changed is True
    assert fault.changed is True
    assert release.changed is False
    assert state.effective_track_state("Q1") is TrackState.FAULT_OCCUPIED
    assert state.state_version == 2


def test_same_effective_value_does_not_increment_version() -> None:
    """防止重复输入制造虚假的状态版本。"""
    state = StationRuntimeState.create("A", ["Q1"])

    state.apply_track_input("Q1", TrackInputSource.OPERATOR, TrackState.OCCUPIED)
    duplicate = state.apply_track_input(
        "Q1", TrackInputSource.OPERATOR, TrackState.OCCUPIED
    )

    assert duplicate.changed is False
    assert state.state_version == 1


def test_unknown_section_is_rejected_without_mutating_state() -> None:
    """防止拼写错误悄悄创建新的轨道区段。"""
    state = StationRuntimeState.create("A", ["Q1"])

    with pytest.raises(UnknownTrackSectionError, match="Q404"):
        state.apply_track_input(
            "Q404", TrackInputSource.OPERATOR, TrackState.OCCUPIED
        )

    assert state.state_version == 0
    assert tuple(state.track_inputs) == ("Q1",)
