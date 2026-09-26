"""双站快照聚合规则测试：A 方向权威，不一致必须显式锁闭。"""

from dataclasses import dataclass

from PyQt5.QtTest import QSignalSpy

from app.core.enums import ConnectionState, RunningDirection, TrackState
from app.services.alarm_service import AlarmLevel, AlarmRecord
from app.ui.dual_snapshot import DualStationSnapshotAggregator


@dataclass(frozen=True)
class SnapshotStub:
    station_id: str
    state_version: int
    running_direction: str
    direction_operation_locked: bool
    connection_state: ConnectionState
    tracks: dict[str, TrackState]
    alarms: tuple[AlarmRecord, ...] = ()


def _snapshot(
    station_id: str,
    *,
    state_version: int = 0,
    direction: RunningDirection = RunningDirection.A_TO_B,
    connection: ConnectionState = ConnectionState.HEALTHY,
    locked: bool = False,
    q1: TrackState = TrackState.CLEAR,
    alarms: tuple[AlarmRecord, ...] = (),
) -> SnapshotStub:
    return SnapshotStub(
        station_id=station_id,
        state_version=state_version,
        running_direction=direction.value,
        direction_operation_locked=locked,
        connection_state=connection,
        tracks={
            "A_T1": TrackState.OCCUPIED if station_id == "A" else TrackState.CLEAR,
            "Q1": q1,
            "B_T1": TrackState.OCCUPIED if station_id == "B" else TrackState.CLEAR,
        },
        alarms=alarms,
    )


def test_aggregator_waits_for_both_stations_and_ignores_duplicate(qtbot) -> None:  # type: ignore[no-untyped-def]
    aggregator = DualStationSnapshotAggregator()
    spy = QSignalSpy(aggregator.snapshot_changed)
    station_b = _snapshot("B")
    station_a = _snapshot("A")

    aggregator.update_b(station_b)
    assert len(spy) == 0
    aggregator.update_a(station_a)
    assert len(spy) == 1
    aggregator.update_a(station_a)

    assert len(spy) == 1
    model = aggregator.snapshot
    assert model is not None
    assert model.station_a is station_a
    assert model.station_b is station_b
    assert model.authoritative_direction is RunningDirection.A_TO_B
    assert model.communication_healthy is True
    assert model.operation_locked is False


def test_station_owned_sections_use_owner_and_shared_mismatch_locks() -> None:
    aggregator = DualStationSnapshotAggregator()
    aggregator.update_a(_snapshot("A", q1=TrackState.CLEAR))
    aggregator.update_b(_snapshot("B", q1=TrackState.OCCUPIED))

    model = aggregator.snapshot
    assert model is not None
    by_id = {item.section_id: item for item in model.sections}
    assert by_id["A_T1"].display_state is TrackState.OCCUPIED
    assert by_id["A_T1"].consistent is True
    assert by_id["B_T1"].display_state is TrackState.OCCUPIED
    assert by_id["B_T1"].consistent is True
    assert by_id["Q1"].display_state is None
    assert by_id["Q1"].consistent is False
    assert "不一致" in by_id["Q1"].reason
    assert model.operation_locked is True


def test_direction_communication_and_station_lock_are_combined() -> None:
    aggregator = DualStationSnapshotAggregator()
    aggregator.update_a(_snapshot("A", locked=True))
    aggregator.update_b(
        _snapshot(
            "B",
            direction=RunningDirection.B_TO_A,
            connection=ConnectionState.DEGRADED,
        )
    )

    model = aggregator.snapshot
    assert model is not None
    assert model.authoritative_direction is RunningDirection.A_TO_B
    assert model.direction_consistent is False
    assert model.communication_healthy is False
    assert model.operation_locked is True


def test_alarm_counts_sum_both_stations_and_keep_station_sources() -> None:
    critical = AlarmRecord("A-C", AlarmLevel.CRITICAL, "严重", "A:signal", 1)
    warning = AlarmRecord("B-W", AlarmLevel.WARNING, "警告", "B:network", 2)
    aggregator = DualStationSnapshotAggregator()
    aggregator.update_a(_snapshot("A", alarms=(critical,)))
    aggregator.update_b(_snapshot("B", alarms=(warning, critical)))

    model = aggregator.snapshot
    assert model is not None
    assert model.active_alarm_count == 3
    assert model.critical_alarm_count == 2


def test_older_station_snapshot_cannot_replace_newer_safety_state() -> None:
    aggregator = DualStationSnapshotAggregator()
    aggregator.update_b(_snapshot("B", state_version=2))
    aggregator.update_a(
        _snapshot(
            "A",
            state_version=2,
            connection=ConnectionState.DEGRADED,
            locked=True,
        )
    )
    assert aggregator.snapshot is not None
    assert aggregator.snapshot.operation_locked is True

    aggregator.update_a(
        _snapshot(
            "A",
            state_version=1,
            connection=ConnectionState.HEALTHY,
            locked=False,
        )
    )

    assert aggregator.snapshot.station_a.state_version == 2
    assert aggregator.snapshot.station_a.connection_state is ConnectionState.DEGRADED
    assert aggregator.snapshot.operation_locked is True


def test_lock_reason_reports_shared_section_inconsistency() -> None:
    """问题 3：共享区段不一致导致锁闭时，lock_reason 必须明确指出原因。"""
    aggregator = DualStationSnapshotAggregator()
    aggregator.update_a(_snapshot("A", q1=TrackState.CLEAR))
    aggregator.update_b(_snapshot("B", q1=TrackState.OCCUPIED))

    model = aggregator.snapshot
    assert model is not None
    assert model.operation_locked is True
    assert "共享区段" in model.lock_reason


def test_lock_reason_reports_communication_and_direction() -> None:
    """问题 3：通信异常/方向不一致时，lock_reason 应分别列出。"""
    aggregator = DualStationSnapshotAggregator()
    aggregator.update_a(
        _snapshot(
            "A",
            locked=True,
            connection=ConnectionState.DEGRADED,
        )
    )
    aggregator.update_b(_snapshot("B", direction=RunningDirection.B_TO_A))

    model = aggregator.snapshot
    assert model is not None
    assert model.operation_locked is True
    assert "通信" in model.lock_reason
    assert "方向" in model.lock_reason


def test_lock_reason_empty_when_unlocked() -> None:
    """问题 3：作业允许时 lock_reason 为空字符串。"""
    aggregator = DualStationSnapshotAggregator()
    aggregator.update_a(_snapshot("A"))
    aggregator.update_b(_snapshot("B"))

    model = aggregator.snapshot
    assert model is not None
    assert model.operation_locked is False
    assert model.lock_reason == ""
