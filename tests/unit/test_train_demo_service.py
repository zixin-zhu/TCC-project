"""配置驱动列车演示不得绕过控制器或清除其他输入来源。"""

from pathlib import Path

from app.core.enums import (
    ConnectionState,
    RunningDirection,
    TrackInputSource,
    TrackState,
)
from app.core.models import PeerSnapshot
from app.infrastructure.config_loader import (
    load_coding_rules,
    load_project_config,
    load_telegram_catalog,
)
from app.services.alarm_service import AlarmService
from app.services.tcc_controller import TccController
from app.services.train_demo_service import TrainDemoService, TrainDemoStatus


ROOT = Path(__file__).resolve().parents[2]


class MemoryPersistence:
    def __init__(self) -> None:
        self.direction = None

    def save_operation(self, _entry):  # type: ignore[no-untyped-def]
        return True

    def save_telegram(self, _entry):  # type: ignore[no-untyped-def]
        return True

    def save_direction_authority(self, entry):  # type: ignore[no-untyped-def]
        self.direction = entry
        return True

    def load_direction_authority(self, _station_id, *, now_ms):  # type: ignore[no-untyped-def]
        return self.direction

    def close(self) -> None:
        pass


def _ready_controller(station_id: str, direction: RunningDirection) -> TccController:
    controller = TccController(
        load_project_config(ROOT / "configs", station_id),
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=MemoryPersistence(),
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
        send_direction=lambda _message: None,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot(
            "B" if station_id == "A" else "A",
            {"Q1": TrackState.CLEAR, "Q2": TrackState.CLEAR,
             "Q3": TrackState.CLEAR, "Q4": TrackState.CLEAR},
            0,
            10_000,
        )
    )
    controller.restore_authoritative_direction(direction)
    return controller


def test_train_uses_topology_order_and_controller_train_source() -> None:
    controller = _ready_controller("A", RunningDirection.A_TO_B)
    assert controller.establish_route("A_DEPART").success
    service = TrainDemoService(controller)
    train = service.create_train()

    result = service.dispatch(train.train_id)

    assert result.success
    assert train.section_id == "Q1"
    assert controller.snapshot.tracks["Q1"] is TrackState.OCCUPIED
    assert (
        controller.runtime.track_inputs["Q1"][TrackInputSource.TRAIN]
        is TrackState.OCCUPIED
    )


def test_train_transition_does_not_clear_manual_or_fault_source() -> None:
    controller = _ready_controller("A", RunningDirection.A_TO_B)
    assert controller.establish_route("A_DEPART").success
    service = TrainDemoService(controller)
    train = service.create_train()
    assert service.dispatch(train.train_id).success
    controller.set_track_state("Q1", TrackInputSource.FAULT, TrackState.SHUNT_BAD)

    service.tick(40.0)

    assert train.section_id == "Q2"
    assert controller.snapshot.tracks["Q1"] is TrackState.SHUNT_BAD
    assert TrackInputSource.TRAIN not in controller.runtime.track_inputs["Q1"]
    assert controller.snapshot.tracks["Q2"] is TrackState.OCCUPIED


def test_reverse_direction_starts_from_last_configured_block() -> None:
    controller = _ready_controller("B", RunningDirection.B_TO_A)
    assert controller.establish_route("B_DEPART").success
    service = TrainDemoService(controller)
    train = service.create_train()

    assert service.dispatch(train.train_id).success
    assert train.section_id == "Q4"


def test_reset_only_removes_train_inputs() -> None:
    controller = _ready_controller("A", RunningDirection.A_TO_B)
    assert controller.establish_route("A_DEPART").success
    service = TrainDemoService(controller)
    train = service.create_train()
    assert service.dispatch(train.train_id).success
    controller.set_track_state("Q1", TrackInputSource.OPERATOR, TrackState.OCCUPIED)

    service.reset()

    assert train.status is TrainDemoStatus.RESET
    assert controller.snapshot.tracks["Q1"] is TrackState.OCCUPIED
    assert TrackInputSource.TRAIN not in controller.runtime.track_inputs["Q1"]


def test_train_pauses_while_direction_is_safely_locked() -> None:
    controller = _ready_controller("A", RunningDirection.A_TO_B)
    assert controller.establish_route("A_DEPART").success
    service = TrainDemoService(controller)
    train = service.create_train()
    assert service.dispatch(train.train_id).success
    controller.set_connection_state(ConnectionState.DEGRADED)

    service.tick(10.0)

    assert train.status is TrainDemoStatus.STOPPED
    assert train.position_m == 0.0
    assert train.section_id == "Q1"
