"""把已通过网络会话门禁的载荷转换为只读对站快照。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable

from app.core.enums import TrackState
from app.core.exceptions import ProtocolError
from app.core.models import PeerSnapshot
from app.network.protocol import MessageType, ProtocolMessage


class PeerSyncService:
    """维护单一对站的同步基线，并拒绝未知区段或版本回退。"""

    def __init__(self, *, peer_station_id: str, allowed_boundary_ids: Iterable[str]) -> None:
        self.peer_station_id = peer_station_id
        self._allowed_boundary_ids = frozenset(allowed_boundary_ids)
        self._snapshot: PeerSnapshot | None = None

    @property
    def snapshot(self) -> PeerSnapshot | None:
        return self._snapshot

    def reset(self) -> None:
        """传输中断后丢弃基线，防止把旧状态当作新会话增量基础。"""
        self._snapshot = None

    def apply_full_sync(
        self, payload: Mapping[str, Any], *, received_at_ms: int
    ) -> PeerSnapshot:
        states = payload.get("boundary_states")
        version = payload.get("state_version")
        if not isinstance(states, Mapping):
            raise ProtocolError("全量同步缺少 boundary_states 对象")
        validated = self._validate_states(states)
        self._validate_version(
            version,
            allow_equal=False,
            compare_existing=self._snapshot is not None,
        )
        self._snapshot = PeerSnapshot(
            station_id=self.peer_station_id,
            boundary_states=validated,
            state_version=version,
            received_at_ms=received_at_ms,
        )
        return self._snapshot

    def validate_and_apply(
        self, message: ProtocolMessage, *, received_at_ms: int
    ) -> None:
        """校验状态类消息，并仅在全部字段合法后提交新快照。"""
        if message.message_type not in {
            MessageType.STATE_SYNC,
            MessageType.TRACK_BOUNDARY,
        }:
            return
        if not isinstance(message.payload, Mapping):
            raise ProtocolError("状态消息 payload 必须是对象")
        payload_version = message.payload.get("state_version")
        if payload_version != message.state_version:
            raise ProtocolError(
                "消息头与载荷状态版本不一致："
                f"header={message.state_version}, payload={payload_version}"
            )
        if message.message_type is MessageType.STATE_SYNC:
            self.apply_full_sync(message.payload, received_at_ms=received_at_ms)
        else:
            self.apply_boundary_update(message.payload, received_at_ms=received_at_ms)

    def apply_boundary_update(
        self, payload: Mapping[str, Any], *, received_at_ms: int
    ) -> PeerSnapshot:
        if self._snapshot is None:
            raise ProtocolError("尚无全量同步基线，拒绝增量状态")
        boundary_id = payload.get("boundary_id")
        if boundary_id not in self._allowed_boundary_ids:
            raise ProtocolError(f"未知对站边界：{boundary_id}")
        state = self._parse_track_state(payload.get("state"))
        version = payload.get("state_version")
        self._validate_version(version, allow_equal=False, compare_existing=True)
        states = dict(self._snapshot.boundary_states)
        states[boundary_id] = state
        self._snapshot = PeerSnapshot(
            station_id=self.peer_station_id,
            boundary_states=states,
            state_version=version,
            received_at_ms=received_at_ms,
        )
        return self._snapshot

    def _validate_states(self, raw_states: Mapping[object, object]) -> dict[str, TrackState]:
        states: dict[str, TrackState] = {}
        for boundary_id, raw_state in raw_states.items():
            if not isinstance(boundary_id, str) or boundary_id not in self._allowed_boundary_ids:
                raise ProtocolError(f"未知对站边界：{boundary_id}")
            states[boundary_id] = self._parse_track_state(raw_state)
        return states

    @staticmethod
    def _parse_track_state(raw_state: object) -> TrackState:
        try:
            return TrackState(raw_state)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"未知轨道状态：{raw_state}") from exc

    def _validate_version(
        self,
        version: object,
        *,
        allow_equal: bool,
        compare_existing: bool,
    ) -> None:
        if type(version) is not int or version < 0:
            raise ProtocolError(f"状态版本必须是非负整数：{version}")
        if compare_existing and self._snapshot is not None:
            minimum = self._snapshot.state_version if allow_equal else self._snapshot.state_version + 1
            if version < minimum:
                raise ProtocolError(
                    f"状态版本未递增：current={self._snapshot.state_version}, received={version}"
                )
