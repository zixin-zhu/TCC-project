"""将同一列车占用输入安全地投送到 A/B 两个 TCC 控制器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.enums import SectionKind, TrackInputSource, TrackState
from app.core.models import OperationResult, ProjectConfig
from app.services.alarm_service import AlarmLevel


class _TrackInputController(Protocol):
    """共享适配器所需的最小控制器接口，便于隔离测试。"""

    config: ProjectConfig

    def set_track_state(
        self,
        section_id: str,
        source: TrackInputSource,
        state: TrackState,
    ) -> OperationResult: ...

    def raise_external_alarm(
        self,
        code: str,
        level: AlarmLevel,
        message: str,
        source: str,
    ) -> None: ...


@dataclass(frozen=True)
class DualWriteResult:
    """一次轨道输入投送在两个控制器上的完整结果。"""

    success: bool
    reason: str
    station_a: OperationResult | None
    station_b: OperationResult | None


class SharedTrackInputAdapter:
    """按物理归属投送 TRAIN 输入，共享闭塞分区执行保守双写。"""

    _ALARM_CODE = "SHARED_INPUT_PARTIAL_FAILURE"
    _ALARM_SOURCE = "SHARED_TRACK_INPUT"

    def __init__(
        self,
        station_a: _TrackInputController,
        station_b: _TrackInputController,
    ) -> None:
        self._station_a = station_a
        self._station_b = station_b
        sections = {
            item.id: item for item in station_a.config.topology.sections
        }
        self._station_a_sections = {
            section_id for section_id in sections if section_id.startswith("A_")
        }
        self._station_b_sections = {
            section_id for section_id in sections if section_id.startswith("B_")
        }
        self._shared_sections = {
            section_id
            for section_id, item in sections.items()
            if item.kind is SectionKind.BLOCK
        }

    def set_state(
        self,
        section_id: str,
        source: TrackInputSource,
        state: TrackState,
    ) -> DualWriteResult:
        """投送列车输入；其他来源必须由目标站控制器直接处理。"""
        if source is not TrackInputSource.TRAIN:
            raise ValueError("共享轨道输入适配器只允许 TRAIN 来源")

        if section_id in self._station_a_sections:
            result = self._station_a.set_track_state(section_id, source, state)
            return DualWriteResult(result.success, result.reason, result, None)
        if section_id in self._station_b_sections:
            result = self._station_b.set_track_state(section_id, source, state)
            return DualWriteResult(result.success, result.reason, None, result)
        if section_id not in self._shared_sections:
            return DualWriteResult(
                False,
                f"未知或不受支持的轨道区段 {section_id}",
                None,
                None,
            )

        # 共享区段固定按 A 后 B 写入，便于审计并避免并发下的不确定顺序。
        result_a = self._station_a.set_track_state(section_id, source, state)
        if not result_a.success:
            return DualWriteResult(False, f"A站：{result_a.reason}", result_a, None)

        result_b = self._station_b.set_track_state(section_id, source, state)
        if result_b.success:
            return DualWriteResult(True, "共享区段状态已同步", result_a, result_b)

        # CLEAR 在 A 成功、B 失败时会造成双站分歧。立即把 A 的 TRAIN 来源
        # 重新置为占用，宁可保留双占用，也不能让任何一站丢失列车检测。
        compensation_text = ""
        if state is TrackState.CLEAR:
            compensation = self._station_a.set_track_state(
                section_id, source, TrackState.OCCUPIED
            )
            compensation_text = (
                "；A站已重新置为占用"
                if compensation.success
                else f"；A站重新占用失败：{compensation.reason}"
            )
        reason = (
            f"共享区段 {section_id} 双写部分失败：{result_b.reason}"
            f"{compensation_text}"
        )
        for controller in (self._station_a, self._station_b):
            controller.raise_external_alarm(
                self._ALARM_CODE,
                AlarmLevel.CRITICAL,
                reason,
                self._ALARM_SOURCE,
            )
        return DualWriteResult(False, reason, result_a, result_b)
