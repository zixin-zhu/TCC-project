"""CTCS-2 双站方向/闭塞一致性守卫。

本模块只做纯规则判断，不发送网络消息，也不直接修改任一站的运行态。
这样 A、B 两站可以分别持有本站权威状态，再通过相同规则检查是否允许
进入改方事务。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import DirectionPhase, RunningDirection, TrackState
from app.core.models import LocalAuthorityState, OperationResult, PeerSnapshot


@dataclass(frozen=True)
class InterstationAgreement:
    """一次站间方向/闭塞安全协商的不可变投影。"""

    direction: RunningDirection
    requester_station: str | None
    responder_station: str | None
    phase: DirectionPhase
    transaction_id: str | None
    local_version: int
    peer_version: int
    expires_at_ms: int | None


def can_change_direction(
    local: LocalAuthorityState,
    peer: PeerSnapshot,
    agreement: InterstationAgreement,
    *,
    now_ms: int | None = None,
    snapshot_timeout_ms: int = 6000,
) -> OperationResult:
    """检查改方前的共同安全条件。

    规则对 A→B 与 B→A 完全对称；``requester_station`` 只表示本次事务
    的角色，不代表永久权威站。函数返回既可展示给 UI，也可写入操作日志。
    """

    if local.station_id not in {
        agreement.requester_station,
        agreement.responder_station,
    }:
        return OperationResult(False, "本站不属于当前站间事务")
    if agreement.requester_station == agreement.responder_station:
        return OperationResult(False, "改方事务请求方和应答方不能相同")
    if agreement.phase not in {
        DirectionPhase.PREPARING,
        DirectionPhase.WAIT_PEER,
        DirectionPhase.APPROVED,
    }:
        return OperationResult(False, "当前事务阶段不允许改方")
    if agreement.local_version != local.state_version:
        return OperationResult(False, "本站状态版本不一致")
    if agreement.peer_version != peer.state_version:
        return OperationResult(False, "对端状态版本不一致")
    if now_ms is not None:
        if agreement.expires_at_ms is not None and now_ms >= agreement.expires_at_ms:
            return OperationResult(False, "改方事务已超时")
        if not peer.is_fresh(now_ms, snapshot_timeout_ms):
            return OperationResult(False, "对端状态快照已过期")
    if peer.direction_operation_locked:
        return OperationResult(False, "对端仍处于方向安全锁闭")
    if local.active_route_ids:
        return OperationResult(False, "本站存在活动进路，不能改方")
    if peer.active_route_ids:
        return OperationResult(False, "对端存在活动进路，不能改方")
    if any(state is not TrackState.CLEAR for state in local.tracks.values()):
        return OperationResult(False, "本站存在占用、故障占用或分路不良区段")
    if any(state is not TrackState.CLEAR for state in peer.boundary_states.values()):
        return OperationResult(False, "对端存在占用、故障占用或分路不良区段")
    return OperationResult(True, "双方本站权威状态满足改方条件")
