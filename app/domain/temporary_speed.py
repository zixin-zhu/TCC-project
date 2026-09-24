"""临时限速命令的教学生命周期。"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, Tuple


class TemporarySpeedState(str, Enum):
    PRESTORED = "PRESTORED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class TemporarySpeedRestriction:
    tsr_id: str
    start_m: float
    end_m: float
    speed_kmh: float
    valid_from_ms: int
    valid_until_ms: int
    state: TemporarySpeedState


class TemporarySpeedService:
    """验证、预存、执行和撤销临时限速。"""

    def __init__(self, line_start_m: float, line_end_m: float):
        self._line_start = line_start_m
        self._line_end = line_end_m
        self._items: Dict[str, TemporarySpeedRestriction] = {}

    def validate(
        self,
        start_m: float,
        end_m: float,
        speed_kmh: float,
        valid_from_ms: int,
        valid_until_ms: int,
        now_ms: int,
    ) -> Tuple[str, ...]:
        issues = []
        if start_m < self._line_start or end_m > self._line_end or start_m >= end_m:
            issues.append("限速里程范围无效")
        if speed_kmh <= 0 or speed_kmh > 500:
            issues.append("限速值必须大于 0 且不超过 500 km/h")
        if valid_from_ms >= valid_until_ms:
            issues.append("生效时间必须早于失效时间")
        if valid_until_ms <= now_ms:
            issues.append("限速命令已经过期")
        return tuple(issues)

    def prestore(
        self,
        tsr_id: str,
        start_m: float,
        end_m: float,
        speed_kmh: float,
        valid_from_ms: int,
        valid_until_ms: int,
        now_ms: int,
    ) -> TemporarySpeedRestriction:
        issues = self.validate(
            start_m, end_m, speed_kmh, valid_from_ms, valid_until_ms, now_ms
        )
        if issues:
            raise ValueError("；".join(issues))
        if tsr_id in self._items and self._items[tsr_id].state is not TemporarySpeedState.CANCELLED:
            raise ValueError(f"临时限速 {tsr_id} 已存在")
        for existing in self._items.values():
            if existing.state is TemporarySpeedState.CANCELLED:
                continue
            mileage_overlaps = max(start_m, existing.start_m) < min(
                end_m, existing.end_m
            )
            time_overlaps = max(valid_from_ms, existing.valid_from_ms) < min(
                valid_until_ms, existing.valid_until_ms
            )
            if mileage_overlaps and time_overlaps:
                raise ValueError(f"与临时限速 {existing.tsr_id} 的里程和时间窗重叠")
        item = TemporarySpeedRestriction(
            tsr_id,
            start_m,
            end_m,
            speed_kmh,
            valid_from_ms,
            valid_until_ms,
            TemporarySpeedState.PRESTORED,
        )
        self._items[tsr_id] = item
        return item

    def activate(self, tsr_id: str, now_ms: int) -> TemporarySpeedRestriction:
        item = self._require(tsr_id)
        if item.state is not TemporarySpeedState.PRESTORED:
            raise ValueError(f"临时限速 {tsr_id} 未处于预存状态")
        if not item.valid_from_ms <= now_ms < item.valid_until_ms:
            raise ValueError(f"临时限速 {tsr_id} 不在有效时间窗")
        active = replace(item, state=TemporarySpeedState.ACTIVE)
        self._items[tsr_id] = active
        return active

    def cancel(self, tsr_id: str) -> TemporarySpeedRestriction:
        item = self._require(tsr_id)
        cancelled = replace(item, state=TemporarySpeedState.CANCELLED)
        self._items[tsr_id] = cancelled
        return cancelled

    def _require(self, tsr_id: str) -> TemporarySpeedRestriction:
        if tsr_id not in self._items:
            raise ValueError(f"未知临时限速：{tsr_id}")
        return self._items[tsr_id]
