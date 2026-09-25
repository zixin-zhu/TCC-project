"""共享轨道输入适配器的安全双写测试。"""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.core.enums import SectionKind, TrackInputSource, TrackState
from app.core.models import OperationResult
from app.services.alarm_service import AlarmLevel
from app.services.shared_track_input import SharedTrackInputAdapter


@dataclass(frozen=True)
class _Station:
    station_id: str


class _FakeController:
    """只记录公共命令调用，不向测试暴露控制器内部运行态。"""

    def __init__(self, station_id: str) -> None:
        sections = tuple(
            SimpleNamespace(
                id=section_id,
                kind=(SectionKind.BLOCK if section_id.startswith("Q") else SectionKind.STATION),
            )
            for section_id in ("A_T1", "A_T2", "Q1", "Q2", "Q3", "Q4", "B_T2", "B_T1")
        )
        self.config = SimpleNamespace(
            station=_Station(station_id),
            topology=SimpleNamespace(sections=sections),
        )
        self.track_calls: list[tuple[str, TrackInputSource, TrackState]] = []
        self.alarm_calls: list[tuple[str, AlarmLevel, str, str]] = []
        self.fail_sections: set[str] = set()

    def set_track_state(
        self,
        section_id: str,
        source: TrackInputSource,
        state: TrackState,
    ) -> OperationResult:
        self.track_calls.append((section_id, source, state))
        if section_id in self.fail_sections:
            return OperationResult(False, f"{self.config.station.station_id}站写入失败")
        return OperationResult(True, "区段状态已更新")

    def raise_external_alarm(
        self,
        code: str,
        level: AlarmLevel,
        message: str,
        source: str,
    ) -> None:
        self.alarm_calls.append((code, level, message, source))


@pytest.fixture
def controllers() -> tuple[_FakeController, _FakeController]:
    return _FakeController("A"), _FakeController("B")


def test_station_section_is_only_written_to_its_owner(controllers) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = controllers
    adapter = SharedTrackInputAdapter(station_a, station_b)

    result_a = adapter.set_state("A_T1", TrackInputSource.TRAIN, TrackState.OCCUPIED)
    result_b = adapter.set_state("B_T2", TrackInputSource.TRAIN, TrackState.OCCUPIED)

    assert result_a.success and result_a.station_a is not None
    assert result_a.station_b is None
    assert result_b.success and result_b.station_b is not None
    assert result_b.station_a is None
    assert [call[0] for call in station_a.track_calls] == ["A_T1"]
    assert [call[0] for call in station_b.track_calls] == ["B_T2"]


def test_shared_section_is_written_to_a_then_b(controllers) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = controllers
    call_order: list[str] = []
    original_a = station_a.set_track_state
    original_b = station_b.set_track_state

    def write_a(*args):  # type: ignore[no-untyped-def]
        call_order.append("A")
        return original_a(*args)

    def write_b(*args):  # type: ignore[no-untyped-def]
        call_order.append("B")
        return original_b(*args)

    station_a.set_track_state = write_a  # type: ignore[method-assign]
    station_b.set_track_state = write_b  # type: ignore[method-assign]
    adapter = SharedTrackInputAdapter(station_a, station_b)

    result = adapter.set_state("Q2", TrackInputSource.TRAIN, TrackState.OCCUPIED)

    assert result.success
    assert result.station_a is not None and result.station_a.success
    assert result.station_b is not None and result.station_b.success
    assert call_order == ["A", "B"]


def test_unknown_section_is_rejected_without_writing(controllers) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = controllers
    adapter = SharedTrackInputAdapter(station_a, station_b)

    result = adapter.set_state("X9", TrackInputSource.TRAIN, TrackState.OCCUPIED)

    assert not result.success
    assert result.station_a is None and result.station_b is None
    assert station_a.track_calls == [] and station_b.track_calls == []


def test_non_train_source_is_rejected_before_writing(controllers) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = controllers
    adapter = SharedTrackInputAdapter(station_a, station_b)

    with pytest.raises(ValueError, match="TRAIN"):
        adapter.set_state("Q1", TrackInputSource.OPERATOR, TrackState.OCCUPIED)

    assert station_a.track_calls == [] and station_b.track_calls == []


def test_partial_shared_write_keeps_a_result_and_raises_critical_alarm(controllers) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = controllers
    station_b.fail_sections.add("Q3")
    adapter = SharedTrackInputAdapter(station_a, station_b)

    result = adapter.set_state("Q3", TrackInputSource.TRAIN, TrackState.OCCUPIED)

    assert not result.success
    assert result.station_a is not None and result.station_a.success
    assert result.station_b is not None and not result.station_b.success
    # A 站只有一次占用写入；适配器不得通过清空操作掩盖部分失败。
    assert station_a.track_calls == [
        ("Q3", TrackInputSource.TRAIN, TrackState.OCCUPIED)
    ]
    for controller in (station_a, station_b):
        assert controller.alarm_calls
        code, level, message, source = controller.alarm_calls[-1]
        assert code == "SHARED_INPUT_PARTIAL_FAILURE"
        assert level is AlarmLevel.CRITICAL
        assert "Q3" in message and "B站写入失败" in message
        assert source == "SHARED_TRACK_INPUT"


def test_a_failure_stops_shared_write_before_b(controllers) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = controllers
    station_a.fail_sections.add("Q4")
    adapter = SharedTrackInputAdapter(station_a, station_b)

    result = adapter.set_state("Q4", TrackInputSource.TRAIN, TrackState.OCCUPIED)

    assert not result.success
    assert result.station_a is not None and not result.station_a.success
    assert result.station_b is None
    assert station_b.track_calls == []


def test_partial_shared_clear_reasserts_a_occupancy_conservatively(controllers) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = controllers
    adapter = SharedTrackInputAdapter(station_a, station_b)
    assert adapter.set_state("Q1", TrackInputSource.TRAIN, TrackState.OCCUPIED).success
    station_a.track_calls.clear()
    station_b.track_calls.clear()
    station_b.fail_sections.add("Q1")

    result = adapter.set_state("Q1", TrackInputSource.TRAIN, TrackState.CLEAR)

    assert not result.success
    assert station_a.track_calls == [
        ("Q1", TrackInputSource.TRAIN, TrackState.CLEAR),
        ("Q1", TrackInputSource.TRAIN, TrackState.OCCUPIED),
    ]
    assert station_b.track_calls == [
        ("Q1", TrackInputSource.TRAIN, TrackState.CLEAR)
    ]
    assert "重新置为占用" in result.reason
