"""公共区段设备双站确认事务的测试。"""

from app.core.enums import RunningDirection, TrackInputSource, TrackState
from app.core.models import OperationResult
from app.services.shared_state_request_service import (
    SharedRequestStatus,
    SharedStateRequestService,
)
from tests.integration.test_main_window import _controller


def _service():
    station_a = _controller("A")
    station_b = _controller("B")
    return (
        station_a,
        station_b,
        SharedStateRequestService(station_a, station_b),
    )


def test_submit_does_not_change_shared_state_until_other_station_approves() -> None:
    station_a, station_b, service = _service()

    submitted = service.submit("Q1", TrackState.OCCUPIED, "A")

    assert submitted.success
    assert station_a.snapshot.tracks["Q1"] is TrackState.CLEAR
    assert station_b.snapshot.tracks["Q1"] is TrackState.CLEAR
    request = service.pending_requests()[0]
    assert request.requester_station_id == "A"
    assert request.approvals == ()

    approved = service.approve(request.request_id, "B")

    assert approved.success
    assert station_a.snapshot.tracks["Q1"] is TrackState.OCCUPIED
    assert station_b.snapshot.tracks["Q1"] is TrackState.OCCUPIED
    assert service.pending_requests() == ()
    assert service.history()[-1].status is SharedRequestStatus.APPLIED


def test_requester_cannot_approve_own_request_and_rejection_is_recorded() -> None:
    station_a, station_b, service = _service()
    assert service.submit("Q2", TrackState.FAULT_OCCUPIED, "B").success
    request = service.pending_requests()[0]

    own_approval = service.approve(request.request_id, "B")
    rejected = service.reject(request.request_id, "A", "A站检查到共享区段仍有进路")

    assert not own_approval.success
    assert rejected.success
    assert station_a.snapshot.tracks["Q2"] is TrackState.CLEAR
    assert station_b.snapshot.tracks["Q2"] is TrackState.CLEAR
    record = service.history()[-1]
    assert record.status is SharedRequestStatus.REJECTED
    assert "仍有进路" in record.reason


def test_only_one_pending_request_is_allowed_for_a_shared_section() -> None:
    _station_a, _station_b, service = _service()

    assert service.submit("Q3", TrackState.OCCUPIED, "A").success
    duplicate = service.submit("Q3", TrackState.SHUNT_BAD, "A")

    assert not duplicate.success
    assert "待处理申请" in duplicate.reason


def test_direction_request_is_executed_only_after_peer_approval() -> None:
    station_a, station_b, service = _service()
    calls: list[str] = []

    def request(direction):  # type: ignore[no-untyped-def]
        calls.append(direction.value)
        return OperationResult(True, "改方事务已发起")

    station_a.request_direction_change = request  # type: ignore[method-assign]
    assert service.submit_direction(RunningDirection.B_TO_A, "A").success
    assert calls == []
    request_record = service.pending_requests_for("B")[0]
    assert "方向由A_TO_B改为B_TO_A" in request_record.content

    approved = service.approve(request_record.request_id, "B")

    assert approved.success
    assert calls == ["B_TO_A"]
