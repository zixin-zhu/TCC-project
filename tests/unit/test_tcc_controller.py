"""统一 TccController 的事件顺序和单一写入口测试。"""

from pathlib import Path

from app.core.enums import (
    ConnectionState,
    RunningDirection,
    SignalAspect,
    TrackInputSource,
    TrackState,
)
from app.core.exceptions import ProtocolError
from app.core.models import PeerSnapshot
from app.infrastructure.config_loader import (
    load_coding_rules,
    load_project_config,
    load_telegram_catalog,
)
from app.services.alarm_service import AlarmService
from app.services.persistence_service import PersistenceService
from app.services.tcc_controller import TccController
from app.infrastructure.sqlite_repository import (
    DirectionAuthorityEntry,
    SQLiteRepository,
)


ROOT = Path(__file__).resolve().parents[2]


class FakePersistence:
    def __init__(self) -> None:
        self.operations = []
        self.telegrams = []
        self.closed = False
        self.direction = None

    def save_operation(self, entry):  # type: ignore[no-untyped-def]
        self.operations.append(entry)
        return True

    def save_telegram(self, entry):  # type: ignore[no-untyped-def]
        self.telegrams.append(entry)
        return True

    def save_direction_authority(self, entry):  # type: ignore[no-untyped-def]
        self.direction = entry
        return True

    def load_direction_authority(self, _station_id, *, now_ms):  # type: ignore[no-untyped-def]
        return self.direction

    def close(self) -> None:
        self.closed = True


def _controller(*, stages=None, published=None, snapshots=None):  # type: ignore[no-untyped-def]
    config = load_project_config(ROOT / "configs", "A")
    controller = TccController(
        config,
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=FakePersistence(),
        publish_state=(published if published is not None else []).append,
        snapshot_listener=(snapshots if snapshots is not None else []).append,
        stage_listener=(stages if stages is not None else []).append,
        clock_ms=lambda: 10_000,
        send_direction=lambda _message: None,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot("B", {"Q1": TrackState.CLEAR}, 0, 10_000)
    )
    controller.restore_authoritative_direction(RunningDirection.A_TO_B)
    return controller


def test_effective_change_runs_required_event_chain_in_order() -> None:
    stages = []
    published = []
    snapshots = []
    controller = _controller(stages=stages, published=published, snapshots=snapshots)
    stages.clear()
    published.clear()
    snapshots.clear()

    result = controller.set_track_state(
        "Q2", TrackInputSource.OPERATOR, TrackState.OCCUPIED
    )

    assert result.success
    assert stages == [
        "state",
        "coding",
        "signals",
        "leu",
        "alarms",
        "peer_sync",
        "ui_snapshot",
        "operation_log",
    ]
    assert published[-1]["state_version"] == 1
    assert snapshots[-1].tracks["Q2"] is TrackState.OCCUPIED
    assert snapshots[-1].state_version == 1


def test_controller_starts_disconnected_and_fail_closed() -> None:
    config = load_project_config(ROOT / "configs", "A")
    controller = TccController(
        config,
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=FakePersistence(),
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
    )

    assert controller.snapshot.connection_state is ConnectionState.DISCONNECTED
    assert controller.snapshot.direction_operation_locked is True
    assert not controller.establish_route("A_DEPART").success


def test_invalid_track_id_does_not_change_or_publish_state() -> None:
    published = []
    controller = _controller(published=published)
    published.clear()
    before = controller.snapshot

    result = controller.set_track_state(
        "NOT_EXISTS", TrackInputSource.OPERATOR, TrackState.OCCUPIED
    )

    assert not result.success
    assert controller.snapshot.state_version == before.state_version
    assert controller.snapshot.tracks == before.tracks
    assert published == []


def test_route_command_recalculates_signal_and_is_logged() -> None:
    controller = _controller()

    result = controller.establish_route("A_DEPART")

    assert result.success
    assert "A_DEPART" in controller.snapshot.active_route_ids
    assert controller.snapshot.signals["SA"].reason
    assert controller.persistence.operations[-1].operation == "建立进路 A_DEPART"


def test_controller_close_closes_persistence_once() -> None:
    controller = _controller()
    controller.close()
    controller.close()

    assert controller.persistence.closed is True


def test_active_temporary_speed_selects_ctcs2_logical_telegram() -> None:
    controller = _controller()
    assert controller.prestore_temporary_speed(
        "TSR-UI", 1000, 2000, 80, 9000, 20_000
    ).success

    result = controller.activate_temporary_speed("TSR-UI")

    assert result.success
    assert controller.snapshot.telegram.template_id == "TG_A_TSR"
    packets = controller.snapshot.telegram.logical_payload["packets"]
    ctcs2 = next(item for item in packets if item["packet_id"] == "CTCS-2")
    assert ctcs2["fields"]["tsr_id"] == "TSR-UI"
    assert controller.snapshot.telegram.simulation_format == "simulation_envelope"
    assert controller.snapshot.telegram.teaching_bit_view


def test_operation_history_and_network_metrics_are_exposed_in_snapshot() -> None:
    controller = _controller()

    controller.establish_route("A_DEPART")
    controller.update_network_metrics(received=3, sent=5)

    assert controller.snapshot.operation_logs[0].operation == "建立进路 A_DEPART"
    assert controller.snapshot.network_received == 3
    assert controller.snapshot.network_sent == 5


def test_two_controllers_complete_authoritative_direction_change() -> None:
    pending_a = []
    pending_b = []
    confirmations = []
    published_a = []
    published_b = []

    def build(station_id, outgoing, published, confirmation=None):  # type: ignore[no-untyped-def]
        config = load_project_config(ROOT / "configs", station_id)
        return TccController(
            config,
            load_coding_rules(ROOT / "configs" / "coding_rules.json"),
            load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
            alarms=AlarmService(),
            persistence=FakePersistence(),
            publish_state=published.append,
            snapshot_listener=lambda _snapshot: None,
            clock_ms=lambda: 10_000,
            send_direction=outgoing.append,
            send_direction_confirmation=(
                confirmation.append if confirmation is not None else None
            ),
        )

    station_a = build("A", pending_b, published_a, confirmations)
    station_b = build("B", pending_a, published_b)
    for local, peer_id in ((station_a, "B"), (station_b, "A")):
        local.set_connection_state(ConnectionState.HEALTHY)
        local.update_peer_snapshot(
            PeerSnapshot(peer_id, {"Q1": TrackState.CLEAR}, 0, 10_000)
        )
        local.restore_authoritative_direction(RunningDirection.A_TO_B)
    published_a.clear()
    published_b.clear()

    assert station_a.request_direction_change(RunningDirection.B_TO_A).success
    assert station_b.handle_direction_message(pending_b.pop(0)).success
    assert station_a.handle_direction_message(pending_a.pop(0)).success
    assert station_b.handle_direction_message(pending_b.pop(0)).success
    assert station_a.handle_direction_message(pending_a.pop(0)).success
    assert station_b.handle_direction_confirmation(confirmations.pop(0)).success

    assert station_a.snapshot.running_direction == RunningDirection.B_TO_A.value
    assert station_b.snapshot.running_direction == RunningDirection.B_TO_A.value
    assert station_a.snapshot.direction_operation_locked is False
    assert station_b.snapshot.direction_operation_locked is False
    assert station_a.persistence.direction.recovery is not None
    assert [item["state_version"] for item in published_a] == [1]
    assert [item["state_version"] for item in published_b] == [1]


def test_disconnect_locks_direction_dependent_operations() -> None:
    controller = _controller()

    controller.set_connection_state(ConnectionState.DEGRADED)

    assert controller.snapshot.direction_operation_locked is True
    assert not controller.establish_route("A_DEPART").success


def test_direction_transport_failure_is_visible_and_remains_fail_safe() -> None:
    config = load_project_config(ROOT / "configs", "A")

    def broken_sender(_message):  # type: ignore[no-untyped-def]
        raise OSError("发送队列不可用")

    controller = TccController(
        config,
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=FakePersistence(),
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
        send_direction=broken_sender,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot("B", {"Q1": TrackState.CLEAR}, 0, 10_000)
    )
    controller.restore_authoritative_direction(RunningDirection.A_TO_B)

    result = controller.request_direction_change(RunningDirection.B_TO_A)

    assert not result.success
    assert "发送队列不可用" in result.reason
    assert controller.snapshot.direction_operation_locked is True
    assert any(
        alarm.code == "DIRECTION_TRANSPORT_FAILURE"
        for alarm in controller.snapshot.alarms
    )


def test_lock_only_direction_transition_does_not_publish_duplicate_version() -> None:
    published = []
    controller = _controller(published=published)
    published.clear()

    result = controller.request_direction_change(RunningDirection.B_TO_A)

    assert result.success
    assert controller.snapshot.direction_operation_locked is True
    assert published == []


def test_authoritative_direction_is_restored_after_restart(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "authority.db")
    repository.save_direction_authority(
        DirectionAuthorityEntry(
            "A",
            RunningDirection.B_TO_A,
            9000,
            6,
            {
                "transaction_id": "9e724768-fc99-4cba-a410-1bc19f6cc98d",
                "requester_station_id": "A",
                "responder_station_id": "B",
                "original_direction": "A_TO_B",
                "target_direction": "B_TO_A",
                "requester_state_version": 5,
                "responder_state_version": 3,
                "requester_applied": True,
            },
        )
    )
    persistence = PersistenceService(repository, AlarmService())
    config = load_project_config(ROOT / "configs", "A")

    controller = TccController(
        config,
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=persistence.alarms,
        persistence=persistence,
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
    )

    assert controller.snapshot.running_direction == RunningDirection.B_TO_A.value
    assert controller.snapshot.state_version == 6
    assert controller.snapshot.direction_operation_locked is True


def test_state_publish_failure_keeps_snapshot_and_audit_consistent() -> None:
    fail = False

    def publisher(_payload):  # type: ignore[no-untyped-def]
        if fail:
            raise ProtocolError("发送队列已满")

    config = load_project_config(ROOT / "configs", "A")
    controller = TccController(
        config,
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=FakePersistence(),
        publish_state=publisher,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot("B", {"Q1": TrackState.CLEAR}, 0, 10_000)
    )
    controller.restore_authoritative_direction(RunningDirection.A_TO_B)
    fail = True

    result = controller.set_track_state(
        "Q2", TrackInputSource.OPERATOR, TrackState.OCCUPIED
    )

    assert result.success
    assert controller.snapshot.tracks["Q2"] is TrackState.OCCUPIED
    assert controller.snapshot.direction_operation_locked is True
    assert controller.snapshot.operation_logs[0].operation == "设置区段 Q2"
    assert any(
        alarm.code == "NETWORK_SEND_FAILURE"
        for alarm in controller.snapshot.alarms
    )


def test_direction_transaction_expires_without_network_disconnect() -> None:
    now = [10_000]
    config = load_project_config(ROOT / "configs", "A")
    controller = TccController(
        config,
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=FakePersistence(),
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: now[0],
        send_direction=lambda _message: None,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot("B", {"Q1": TrackState.CLEAR}, 0, now[0])
    )
    controller.restore_authoritative_direction(RunningDirection.A_TO_B)
    assert controller.request_direction_change(RunningDirection.B_TO_A).success
    log_count = len(controller.snapshot.operation_logs)
    telegram_count = len(controller.persistence.telegrams)

    assert controller.expire_direction_change() is None
    assert len(controller.snapshot.operation_logs) == log_count
    assert len(controller.persistence.telegrams) == telegram_count

    now[0] += 5_001

    result = controller.expire_direction_change()

    assert result is not None
    assert not result.success
    assert controller.snapshot.direction_operation_locked is True
    assert "超时" in result.reason


def test_authority_persistence_failure_prevents_apply_and_commit() -> None:
    class FailNewDirectionPersistence(FakePersistence):
        def save_direction_authority(self, entry):  # type: ignore[no-untyped-def]
            if entry.direction is RunningDirection.B_TO_A:
                return False
            return super().save_direction_authority(entry)

    to_a = []
    to_b = []
    config_a = load_project_config(ROOT / "configs", "A")
    persistence_a = FailNewDirectionPersistence()
    station_a = TccController(
        config_a,
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=persistence_a,
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
        send_direction=to_b.append,
    )
    config_b = load_project_config(ROOT / "configs", "B")
    station_b = TccController(
        config_b,
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=FakePersistence(),
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
        send_direction=to_a.append,
    )
    for local, peer_id in ((station_a, "B"), (station_b, "A")):
        local.set_connection_state(ConnectionState.HEALTHY)
        local.update_peer_snapshot(
            PeerSnapshot(peer_id, {"Q1": TrackState.CLEAR}, 0, 10_000)
        )
        local.restore_authoritative_direction(RunningDirection.A_TO_B)
    assert station_a.request_direction_change(RunningDirection.B_TO_A).success
    assert station_b.handle_direction_message(to_b.pop(0)).success

    result = station_a.handle_direction_message(to_a.pop(0))

    assert not result.success
    assert station_a.runtime.running_direction is RunningDirection.A_TO_B
    assert persistence_a.direction.direction is RunningDirection.A_TO_B
    assert station_a.snapshot.direction_operation_locked is True
    assert to_b == []


def test_restart_replays_persisted_recovery_confirmation() -> None:
    recovery = {
        "transaction_id": "9e724768-fc99-4cba-a410-1bc19f6cc98d",
        "requester_station_id": "A",
        "responder_station_id": "B",
        "original_direction": "A_TO_B",
        "target_direction": "B_TO_A",
        "requester_state_version": 5,
        "responder_state_version": 3,
        "requester_applied": True,
    }
    persistence = FakePersistence()
    persistence.direction = DirectionAuthorityEntry(
        "A", RunningDirection.B_TO_A, 9000, 6, recovery
    )
    confirmations = []
    config = load_project_config(ROOT / "configs", "A")
    controller = TccController(
        config,
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=persistence,
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
        send_direction=lambda _message: None,
        send_direction_confirmation=confirmations.append,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot("B", {"Q1": TrackState.CLEAR}, 3, 10_000)
    )

    result = controller.restore_authoritative_direction(RunningDirection.B_TO_A)

    assert result.success
    assert confirmations[0].transaction_id == recovery["transaction_id"]
    assert persistence.direction.recovery == recovery


def test_peer_snapshot_expiry_recalculates_once_and_fails_closed() -> None:
    now = [10_000]
    config = load_project_config(ROOT / "configs", "A")
    persistence = FakePersistence()
    controller = TccController(
        config,
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=persistence,
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: now[0],
        send_direction=lambda _message: None,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot("B", {"Q1": TrackState.CLEAR}, 0, now[0])
    )
    controller.restore_authoritative_direction(RunningDirection.A_TO_B)
    telegram_count = len(persistence.telegrams)
    now[0] += 3_501

    assert controller.reevaluate_time_dependent_safety() is True
    assert controller.snapshot.direction_operation_locked is True
    assert all(
        signal.aspect is SignalAspect.RED
        for signal in controller.snapshot.signals.values()
    )
    assert any(
        alarm.code == "PEER_SNAPSHOT_STALE"
        for alarm in controller.snapshot.alarms
    )
    assert len(persistence.telegrams) == telegram_count + 1

    assert controller.reevaluate_time_dependent_safety() is False
    assert len(persistence.telegrams) == telegram_count + 1
