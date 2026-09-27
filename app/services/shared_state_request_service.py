"""公共区段人工状态调整的双站确认事务。

列车自动占用由 ``SharedTrackInputAdapter`` 独立处理；本服务只处理界面
发起的公共区段人工调整。申请方提交后不写入状态，只有对站确认后才执行
一次双端写入，任何校验或写入失败都保守拒绝并留下可追溯记录。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from PyQt5.QtCore import QObject, pyqtSignal

from app.core.enums import ConnectionState, TrackInputSource, TrackState
from app.core.models import OperationResult
from app.services.alarm_service import AlarmLevel
from app.services.tcc_controller import TccController


class SharedRequestStatus(str, Enum):
    PENDING = "待确认"
    APPLIED = "已生效"
    REJECTED = "已拒绝"


@dataclass(frozen=True)
class SharedStateRequest:
    request_id: str
    section_id: str
    requested_state: TrackState
    requester_station_id: str
    created_at: str
    status: SharedRequestStatus = SharedRequestStatus.PENDING
    approver_station_id: str | None = None
    processed_at: str | None = None
    reason: str = "等待对站确认"

    @property
    def approvals(self) -> tuple[str, ...]:
        """兼容界面/测试使用的确认站点列表。"""
        return (self.approver_station_id,) if self.approver_station_id else ()


class SharedStateRequestService(QObject):
    """管理 Q 区段人工状态申请及其双端原子化教学写入。"""

    requests_changed = pyqtSignal()

    def __init__(self, station_a: TccController, station_b: TccController) -> None:
        super().__init__()
        self.station_a = station_a
        self.station_b = station_b
        self._pending: dict[str, SharedStateRequest] = {}
        self._history: list[SharedStateRequest] = []

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    def pending_requests(self) -> tuple[SharedStateRequest, ...]:
        return tuple(self._pending.values())

    def history(self) -> tuple[SharedStateRequest, ...]:
        return tuple(self._history)

    def submit(
        self, section_id: str, requested_state: TrackState, requester_station_id: str
    ) -> OperationResult:
        if not section_id.startswith("Q"):
            return OperationResult(False, "只有 Q1～Q4 公共区段需要双站申请")
        if requester_station_id not in {"A", "B"}:
            return OperationResult(False, f"未知申请站点：{requester_station_id}")
        if any(item.section_id == section_id for item in self._pending.values()):
            return OperationResult(False, f"{section_id} 已存在待处理申请")
        request = SharedStateRequest(
            request_id=f"SSR-{uuid4().hex[:8].upper()}",
            section_id=section_id,
            requested_state=requested_state,
            requester_station_id=requester_station_id,
            created_at=self._now(),
        )
        self._pending[request.request_id] = request
        self.requests_changed.emit()
        return OperationResult(True, "已提交申请，正在等待 A/B 站确认……")

    def approve(self, request_id: str, station_id: str) -> OperationResult:
        request = self._pending.get(request_id)
        if request is None:
            return OperationResult(False, "申请不存在或已处理")
        if station_id not in {"A", "B"}:
            return OperationResult(False, f"未知确认站点：{station_id}")
        if station_id == request.requester_station_id:
            return OperationResult(False, "申请方不能确认自己的申请，必须由对站确认")
        if not self._both_healthy():
            return OperationResult(False, "A/B 站间通信未健康，暂不能生效")

        requester = self.station_a if request.requester_station_id == "A" else self.station_b
        responder = self.station_b if request.requester_station_id == "A" else self.station_a
        before = requester.snapshot.tracks.get(request.section_id, TrackState.OCCUPIED)
        first = requester.set_track_state(
            request.section_id, TrackInputSource.OPERATOR, request.requested_state
        )
        if not first.success:
            return self._reject_after_apply(request, station_id, f"申请方写入失败：{first.reason}")
        second = responder.set_track_state(
            request.section_id, TrackInputSource.OPERATOR, request.requested_state
        )
        if not second.success:
            compensation = requester.set_track_state(
                request.section_id, TrackInputSource.OPERATOR, before
            )
            reason = f"对站写入失败：{second.reason}"
            if not compensation.success:
                reason += f"；保守恢复失败：{compensation.reason}"
            for controller in (self.station_a, self.station_b):
                controller.raise_external_alarm(
                    "SHARED_STATE_CONFIRM_FAILURE",
                    AlarmLevel.CRITICAL,
                    reason,
                    "SHARED_STATE_REQUEST",
                )
            return self._reject_after_apply(request, station_id, reason)

        completed = replace(
            request,
            status=SharedRequestStatus.APPLIED,
            approver_station_id=station_id,
            processed_at=self._now(),
            reason="对站确认通过，A/B 两端公共区段状态已同步生效",
        )
        self._finish(request.request_id, completed)
        return OperationResult(True, completed.reason)

    def reject(self, request_id: str, station_id: str, reason: str) -> OperationResult:
        request = self._pending.get(request_id)
        if request is None:
            return OperationResult(False, "申请不存在或已处理")
        if station_id == request.requester_station_id:
            return OperationResult(False, "申请方不能处理自己的申请")
        completed = replace(
            request,
            status=SharedRequestStatus.REJECTED,
            approver_station_id=station_id,
            processed_at=self._now(),
            reason=reason or "对站拒绝申请",
        )
        self._finish(request.request_id, completed)
        return OperationResult(True, completed.reason)

    def _reject_after_apply(
        self, request: SharedStateRequest, station_id: str, reason: str
    ) -> OperationResult:
        completed = replace(
            request,
            status=SharedRequestStatus.REJECTED,
            approver_station_id=station_id,
            processed_at=self._now(),
            reason=reason,
        )
        self._finish(request.request_id, completed)
        return OperationResult(False, reason)

    def _finish(self, request_id: str, completed: SharedStateRequest) -> None:
        self._pending.pop(request_id, None)
        self._history.insert(0, completed)
        del self._history[100:]
        self.requests_changed.emit()

    def _both_healthy(self) -> bool:
        return (
            self.station_a.snapshot.connection_state is ConnectionState.HEALTHY
            and self.station_b.snapshot.connection_state is ConnectionState.HEALTHY
        )
