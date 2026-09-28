"""跨 A/B 唯一列车协调器测试。"""

from pathlib import Path

from PyQt5.QtCore import QObject

from app.core.enums import (
    ConnectionState,
    RunningDirection,
    TrackInputSource,
    TrackState,
)
from app.core.models import OperationResult, PeerSnapshot
from app.infrastructure.config_loader import (
    load_coding_rules,
    load_project_config,
    load_telegram_catalog,
)
from app.services.alarm_service import AlarmService
from app.services.dual_train_coordinator import (
    DualTrainCoordinator,
    DualTrainStatus,
)
from app.services.shared_track_input import DualWriteResult, SharedTrackInputAdapter
from app.services.tcc_controller import TccController


ROOT = Path(__file__).resolve().parents[2]


class _MemoryPersistence:
    def save_operation(self, _entry):  # type: ignore[no-untyped-def]
        return True

    def save_telegram(self, _entry):  # type: ignore[no-untyped-def]
        return True

    def save_direction_authority(self, _entry):  # type: ignore[no-untyped-def]
        return True

    def load_direction_authority(self, _station_id, *, now_ms):  # type: ignore[no-untyped-def]
        return None

    def close(self) -> None:
        pass


def _controller(station_id: str, direction: RunningDirection) -> TccController:
    controller = TccController(
        load_project_config(ROOT / "configs", station_id),
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=_MemoryPersistence(),
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
        send_direction=lambda _message: None,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot(
            "B" if station_id == "A" else "A",
            {f"Q{index}": TrackState.CLEAR for index in range(1, 5)},
            0,
            10_000,
        )
    )
    controller.restore_authoritative_direction(direction)
    return controller


def _pair(
    direction: RunningDirection = RunningDirection.A_TO_B,
) -> tuple[TccController, TccController]:
    return _controller("A", direction), _controller("B", direction)


def _dispatched(
    direction: RunningDirection = RunningDirection.A_TO_B,
) -> tuple[DualTrainCoordinator, TccController, TccController]:
    station_a, station_b = _pair(direction)
    origin = station_a if direction is RunningDirection.A_TO_B else station_b
    destination = station_b if direction is RunningDirection.A_TO_B else station_a
    assert origin.establish_route(
        "A_DEPART" if direction is RunningDirection.A_TO_B else "B_DEPART"
    ).success
    assert destination.establish_route(
        "B_ARRIVE" if direction is RunningDirection.A_TO_B else "A_ARRIVE"
    ).success
    coordinator = DualTrainCoordinator(station_a, station_b)
    train = coordinator.create_train()
    assert coordinator.dispatch(train.train_id).success
    assert coordinator.start().success
    return coordinator, station_a, station_b


def test_has_one_parented_100_ms_timer(qapp) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = _pair()
    coordinator = DualTrainCoordinator(station_a, station_b)

    assert coordinator.timer.interval() == 100
    assert coordinator.timer.parent() is coordinator
    assert len(coordinator.findChildren(type(coordinator.timer))) == 1


def test_forward_and_reverse_use_full_physical_section_order(qapp) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = _pair()
    coordinator = DualTrainCoordinator(station_a, station_b)

    assert coordinator.ordered_sections(RunningDirection.A_TO_B) == (
        "A_T1", "A_T2", "Q1", "Q2", "Q3", "Q4", "B_T2", "B_T1"
    )
    assert coordinator.ordered_sections(RunningDirection.B_TO_A) == (
        "B_T1", "B_T2", "Q4", "Q3", "Q2", "Q1", "A_T2", "A_T1"
    )


def test_dispatch_requires_origin_departure_route(qapp) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = _pair()
    coordinator = DualTrainCoordinator(station_a, station_b)
    train = coordinator.create_train()

    refused = coordinator.dispatch(train.train_id)
    assert not refused.success
    assert "A_DEPART" in refused.reason

    assert station_a.establish_route("A_DEPART").success
    accepted = coordinator.dispatch(train.train_id)
    assert accepted.success
    assert train.section_id == "A_T1"
    assert train.status is DualTrainStatus.READY
    assert station_a.snapshot.tracks["A_T1"] is TrackState.OCCUPIED


def test_transition_occupies_next_before_clearing_previous(qapp) -> None:  # type: ignore[no-untyped-def]
    coordinator, station_a, _station_b = _dispatched()
    train = coordinator.trains["T001"]

    coordinator.tick(30.0)

    assert train.section_id == "A_T2"
    assert station_a.snapshot.tracks["A_T1"] is TrackState.CLEAR
    assert station_a.snapshot.tracks["A_T2"] is TrackState.OCCUPIED
    assert train.current_speed_kmh == 120.0
    assert train.target_speed_kmh == 120.0


def test_occupied_next_section_stops_train_without_losing_current_occupancy(qapp) -> None:  # type: ignore[no-untyped-def]
    coordinator, station_a, _station_b = _dispatched()
    train = coordinator.trains["T001"]
    station_a.set_track_state("A_T2", TrackInputSource.OPERATOR, TrackState.OCCUPIED)

    coordinator.tick(30.0)

    assert train.section_id == "A_T1"
    assert train.status is DualTrainStatus.STOPPED
    assert train.current_speed_kmh == 0.0
    assert train.target_speed_kmh == 0.0
    assert station_a.snapshot.tracks["A_T1"] is TrackState.OCCUPIED
    assert "A_T2" in train.safety_state


def test_disconnect_or_direction_lock_stops_train(qapp) -> None:  # type: ignore[no-untyped-def]
    coordinator, station_a, _station_b = _dispatched()
    train = coordinator.trains["T001"]
    station_a.set_connection_state(ConnectionState.DEGRADED)

    coordinator.tick(1.0)

    assert train.status is DualTrainStatus.STOPPED
    assert train.position_m == 0.0
    assert train.current_speed_kmh == 0.0
    assert "通信" in train.safety_state


def test_train_reaches_other_station_and_reports_last_balise(qapp) -> None:  # type: ignore[no-untyped-def]
    coordinator, station_a, station_b = _dispatched()
    train = coordinator.trains["T001"]

    coordinator.tick(300.0)

    assert train.status is DualTrainStatus.ARRIVED
    assert train.section_id is None
    assert train.last_balise_id == "B_A_CTL"
    assert all(
        station_a.snapshot.tracks[f"Q{index}"] is TrackState.CLEAR
        and station_b.snapshot.tracks[f"Q{index}"] is TrackState.CLEAR
        for index in range(1, 5)
    )


def test_route_creation_combinations_do_not_lock_direction(qapp) -> None:  # type: ignore[no-untyped-def]
    """出发/到达进路可分别或同时建立，建立动作本身不触发安全联锁。"""
    for direction, departure_station, departure_route, arrival_station, arrival_route in (
        (
            RunningDirection.A_TO_B,
            "A",
            "A_DEPART",
            "B",
            "B_ARRIVE",
        ),
        (
            RunningDirection.B_TO_A,
            "B",
            "B_DEPART",
            "A",
            "A_ARRIVE",
        ),
    ):
        for create_departure, create_arrival in (
            (True, False),
            (False, True),
            (True, True),
        ):
            station_a, station_b = _pair(direction)
            stations = {"A": station_a, "B": station_b}
            if create_departure:
                assert stations[departure_station].establish_route(departure_route).success
            if create_arrival:
                assert stations[arrival_station].establish_route(arrival_route).success
            assert station_a.snapshot.direction_operation_locked is False
            assert station_b.snapshot.direction_operation_locked is False


def test_train_triggers_bilateral_safety_lock_without_arrival_route(qapp) -> None:  # type: ignore[no-untyped-def]
    """列车将进入 B_T2 但无 B_ARRIVE 时，必须触发双站安全联锁。"""
    station_a, station_b = _pair()
    assert station_a.establish_route("A_DEPART").success
    coordinator = DualTrainCoordinator(station_a, station_b)
    train = coordinator.create_train()
    assert coordinator.dispatch(train.train_id).success
    assert coordinator.start(train.train_id).success

    coordinator.tick(300.0)

    assert train.status is DualTrainStatus.STOPPED
    assert train.section_id == "Q4"
    assert "B_ARRIVE 未建立" in train.safety_state
    assert station_a.snapshot.direction_operation_locked is True
    assert station_b.snapshot.direction_operation_locked is True
    assert "B站接车进路 B_ARRIVE 未建立" in station_a.snapshot.safety_lock_reason
    assert "B_T2" in station_b.snapshot.safety_lock_reason


class _FailCurrentClearAdapter(SharedTrackInputAdapter):
    def set_state(self, section_id, source, state):  # type: ignore[no-untyped-def]
        if section_id == "A_T1" and state is TrackState.CLEAR:
            return DualWriteResult(
                False,
                "模拟上一段出清失败",
                OperationResult(False, "模拟上一段出清失败"),
                None,
            )
        return super().set_state(section_id, source, state)


def test_clear_failure_keeps_both_sections_occupied_and_stops(qapp) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = _pair()
    assert station_a.establish_route("A_DEPART").success
    adapter = _FailCurrentClearAdapter(station_a, station_b)
    coordinator = DualTrainCoordinator(station_a, station_b, track_input=adapter)
    train = coordinator.create_train()
    assert coordinator.dispatch(train.train_id).success
    assert coordinator.start().success

    coordinator.tick(30.0)

    assert train.status is DualTrainStatus.STOPPED
    assert train.section_id == "A_T1"
    assert station_a.snapshot.tracks["A_T1"] is TrackState.OCCUPIED
    assert station_a.snapshot.tracks["A_T2"] is TrackState.OCCUPIED
    assert "出清失败" in train.safety_state


def test_reset_only_clears_train_source(qapp) -> None:  # type: ignore[no-untyped-def]
    coordinator, station_a, _station_b = _dispatched()
    train = coordinator.trains["T001"]
    station_a.set_track_state("A_T1", TrackInputSource.FAULT, TrackState.SHUNT_BAD)

    result = coordinator.reset()

    assert result.success
    assert train.status is DualTrainStatus.RESET
    assert station_a.snapshot.tracks["A_T1"] is TrackState.SHUNT_BAD
    assert TrackInputSource.TRAIN not in station_a.runtime.track_inputs["A_T1"]


def test_failed_reset_keeps_train_position_and_conservative_occupancy(qapp) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = _pair()
    assert station_a.establish_route("A_DEPART").success
    coordinator = DualTrainCoordinator(
        station_a,
        station_b,
        track_input=_FailCurrentClearAdapter(station_a, station_b),
    )
    train = coordinator.create_train()
    assert coordinator.dispatch(train.train_id).success

    result = coordinator.reset()

    assert not result.success
    assert train.status is DualTrainStatus.STOPPED
    assert train.section_id == "A_T1"
    assert station_a.snapshot.tracks["A_T1"] is TrackState.OCCUPIED


def test_multiple_waiting_trains_and_selected_reset_can_dispatch_again(qapp) -> None:  # type: ignore[no-untyped-def]
    """阶段 5：复位指定列车后必须回到 WAITING，并可再次派发。"""
    station_a, station_b = _pair()
    assert station_a.establish_route("A_DEPART").success
    coordinator = DualTrainCoordinator(station_a, station_b)

    first = coordinator.create_train()
    second = coordinator.create_train()
    assert first.train_id != second.train_id
    assert first.status is DualTrainStatus.WAITING
    assert second.status is DualTrainStatus.WAITING

    assert coordinator.dispatch(first.train_id).success
    assert coordinator.reset_train(first.train_id).success
    assert first.status is DualTrainStatus.WAITING
    assert first.lifecycle_version == 1
    assert first.section_id is None
    assert coordinator.dispatch(first.train_id).success
    assert first.status is DualTrainStatus.READY


def test_start_accepts_a_specific_train_id(qapp) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = _pair()
    assert station_a.establish_route("A_DEPART").success
    coordinator = DualTrainCoordinator(station_a, station_b)
    train = coordinator.create_train()
    assert coordinator.dispatch(train.train_id).success

    result = coordinator.start(train.train_id)

    assert result.success
    assert train.status is DualTrainStatus.RUNNING


def test_speed_multiplier_scales_simulation_time_without_changing_physical_speed(
    qapp,
) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = _pair()
    assert station_a.establish_route("A_DEPART").success
    coordinator = DualTrainCoordinator(station_a, station_b)
    train = coordinator.create_train()
    assert coordinator.dispatch(train.train_id).success
    assert coordinator.start(train.train_id).success

    assert coordinator.set_speed_multiplier(5.0).success
    coordinator.tick(1.0)

    assert train.current_speed_kmh == 120.0
    assert train.position_m == 120.0 / 3.6 * 5.0


def test_speed_multiplier_rejects_invalid_values_without_changing_setting(qapp) -> None:  # type: ignore[no-untyped-def]
    station_a, station_b = _pair()
    coordinator = DualTrainCoordinator(station_a, station_b)

    result = coordinator.set_speed_multiplier(0.0)

    assert result.success is False
    assert coordinator.speed_multiplier == 1.0
