"""由最终码序唯一导出信号灯色和教学继电器状态。"""

from typing import Dict, Iterable, List, Tuple

from app.core.enums import RunningDirection, SignalAspect, TrackCode
from app.core.models import (
    SignalControlResult,
    StationRuntimeState,
    TopologyConfig,
    TrackCodingResult,
)


_CODE_TO_ASPECT: Dict[TrackCode, SignalAspect] = {
    TrackCode.NONE: SignalAspect.RED,
    TrackCode.DETECT: SignalAspect.RED,
    TrackCode.HU: SignalAspect.RED,
    TrackCode.U: SignalAspect.YELLOW,
    TrackCode.LU: SignalAspect.DOUBLE_YELLOW,
    TrackCode.L: SignalAspect.GREEN,
    TrackCode.L2: SignalAspect.GREEN,
    TrackCode.L3: SignalAspect.GREEN,
    TrackCode.L5: SignalAspect.GREEN,
}

_RELAYS: Dict[SignalAspect, Tuple[bool, bool, bool]] = {
    SignalAspect.DARK: (False, False, False),
    SignalAspect.RED: (True, False, False),
    SignalAspect.YELLOW: (False, True, False),
    SignalAspect.DOUBLE_YELLOW: (False, True, True),
    SignalAspect.GREEN: (False, False, True),
    SignalAspect.RED_LAMP_FAILURE: (False, False, False),
}


class SignalControlService:
    """信号结果是只读计算值，界面不得直接设置灯色。"""

    def __init__(self, topology: TopologyConfig):
        self.topology = topology

    def recalculate(
        self,
        runtime: StationRuntimeState,
        coding_results: Iterable[TrackCodingResult],
    ) -> List[SignalControlResult]:
        codes = {item.section_id: item for item in coding_results}
        results: List[SignalControlResult] = []
        for signal in self.topology.signals:
            expected_direction = RunningDirection(signal.direction.value)
            coding = codes.get(signal.protects_section)
            if runtime.direction_operation_locked:
                aspect = SignalAspect.RED
                reason = "区间方向安全锁闭，保持红灯"
                protected = True
            elif expected_direction is not runtime.running_direction:
                aspect = SignalAspect.RED
                reason = "非运行方向，保持红灯"
                protected = True
            elif coding is None:
                aspect = SignalAspect.RED
                reason = "缺少防护区段编码，保持红灯"
                protected = True
            else:
                aspect = _CODE_TO_ASPECT[coding.code]
                reason = f"防护区段 {signal.protects_section} 编码为 {coding.code.value}"
                protected = coding.protected or aspect is SignalAspect.RED

            alarm_level = None
            if aspect is SignalAspect.RED and signal.id in runtime.failed_red_lamp_ids:
                aspect = SignalAspect.RED_LAMP_FAILURE
                reason = f"{reason}；红灯灯丝故障"
                protected = True
                alarm_level = "CRITICAL"
            relay_hj, relay_uj, relay_lj = _RELAYS[aspect]
            results.append(
                SignalControlResult(
                    signal_id=signal.id,
                    aspect=aspect,
                    relay_hj=relay_hj,
                    relay_uj=relay_uj,
                    relay_lj=relay_lj,
                    reason=reason,
                    protected_section=signal.protects_section,
                    protected=protected,
                    state_version=runtime.state_version,
                    alarm_level=alarm_level,
                )
            )
        return results
