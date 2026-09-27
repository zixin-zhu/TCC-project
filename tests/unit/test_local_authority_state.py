"""阶段 1：本站权威状态模型的可验证行为。"""

from dataclasses import FrozenInstanceError

import pytest

from app.core.enums import RunningDirection, SignalAspect, TrackInputSource, TrackState
from app.core.models import (
    LocalAuthorityState,
    SignalControlResult,
    StationRuntimeState,
)


def test_local_authority_state_can_be_built_from_runtime_without_peer_projection() -> None:
    runtime = StationRuntimeState.create("B", ("Q1", "Q2"))
    runtime.running_direction = RunningDirection.B_TO_A
    runtime.active_route_ids.add("B_DEPART")
    runtime.apply_track_input("Q1", TrackInputSource.OPERATOR, TrackState.OCCUPIED)
    signal = SignalControlResult(
        signal_id="S1",
        aspect=SignalAspect.RED,
        relay_hj=True,
        relay_uj=False,
        relay_lj=False,
        reason="测试",
        protected_section="Q1",
        protected=True,
        state_version=runtime.state_version,
    )

    authority = LocalAuthorityState.from_runtime(
        runtime,
        signals={"S1": signal},
        telegram_version=3,
    )

    assert authority.station_id == "B"
    assert authority.tracks == {"Q1": TrackState.OCCUPIED, "Q2": TrackState.CLEAR}
    assert authority.active_route_ids == ("B_DEPART",)
    assert authority.telegram_version == 3
    assert authority.state_version == runtime.state_version
    with pytest.raises(FrozenInstanceError):
        authority.state_version = 99  # type: ignore[misc]


def test_shunt_is_an_independent_track_input_source() -> None:
    runtime = StationRuntimeState.create("A", ("Q1",))
    runtime.apply_track_input("Q1", TrackInputSource.SHUNT, TrackState.SHUNT_BAD)

    assert runtime.effective_track_state("Q1") is TrackState.SHUNT_BAD
