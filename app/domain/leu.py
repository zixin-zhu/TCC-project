"""可控应答器的 LEU 教学报文选择和容量保护。"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from app.core.enums import BaliseKind, TelegramMode, TrackState
from app.core.models import BaliseGroupsConfig, OperationResult
from app.domain.balise_telegram import LogicalTelegram, LogicalTelegramService


@dataclass(frozen=True)
class LeuContext:
    connected: bool
    input_updated_ms: int
    state_version: int
    selected_template_id: Optional[str]
    overrides: Mapping[str, Mapping[str, Any]]
    # 以下字段将选择输入完整化；默认值保持旧版调用兼容。
    direction: Optional[str] = None
    route_ids: Tuple[str, ...] = ()
    temporary_speed_ids: Tuple[str, ...] = ()
    operation_locked: bool = False
    track_states: Mapping[str, TrackState] = field(default_factory=dict)
    balise_group_id: Optional[str] = None


@dataclass(frozen=True)
class TelegramSelectionResult:
    telegram: LogicalTelegram
    mode: TelegramMode
    reason: str
    alarm_level: Optional[str]
    success: bool = True
    reason_code: str = "SELECTED"


@dataclass
class LeuStorageModel:
    """LEU 报文存储容量模型，至少保留 20% 教学余量。"""

    capacity_total: int
    capacity_used: int = 0
    reserve_ratio: float = 0.20

    def __post_init__(self) -> None:
        if self.capacity_total <= 0:
            raise ValueError("LEU 总容量必须为正数")
        if not 0.20 <= self.reserve_ratio < 1:
            raise ValueError("LEU reserve_ratio 必须不小于 0.20 且小于 1")
        if not 0 <= self.capacity_used <= self.capacity_total:
            raise ValueError("LEU 已用容量必须在总容量范围内")

    @property
    def max_storable(self) -> int:
        return int(self.capacity_total * (1 - self.reserve_ratio))

    @property
    def available_slots(self) -> int:
        return max(0, self.max_storable - self.capacity_used)

    def can_store(self) -> bool:
        return self.available_slots > 0


class LeuService:
    """将 TCC 上下文选择为正常报文或确定的默认报文。"""

    def __init__(
        self,
        groups: BaliseGroupsConfig,
        telegrams: LogicalTelegramService,
        input_timeout_ms: int,
        storage: LeuStorageModel | None = None,
    ):
        self._groups = groups
        self._telegrams = telegrams
        self._timeout_ms = input_timeout_ms
        self.storage = storage or LeuStorageModel(capacity_total=100, capacity_used=0)
        self._stored_templates: set[str] = set()

    def store_template(self, template_id: str) -> OperationResult:
        """登记一个新逻辑报文；容量不足时拒绝写入并返回结构化原因。"""
        if template_id in self._stored_templates:
            return OperationResult(True, "逻辑报文已在 LEU 存储中")
        if not self._telegrams.has_template(template_id):
            return OperationResult(False, f"未知逻辑报文模板 {template_id}")
        if not self.storage.can_store():
            return OperationResult(False, "LEU 存储容量不足，必须保留 20% 余量")
        self._stored_templates.add(template_id)
        self.storage.capacity_used += 1
        return OperationResult(True, "逻辑报文已写入 LEU 存储")

    def select_for_port(
        self, port_id: str, context: LeuContext, now_ms: int
    ) -> TelegramSelectionResult:
        group, balise = self._find_controlled(port_id)
        if not context.connected:
            return self._default(
                group, balise, context, "LEU 输入断联", True, "LEU_DISCONNECTED"
            )
        if now_ms - context.input_updated_ms > self._timeout_ms:
            return self._default(
                group, balise, context, "LEU 输入过期", True, "LEU_INPUT_EXPIRED"
            )
        if context.operation_locked:
            return self._default(
                group, balise, context, "方向或进路处于安全锁闭", True, "OPERATION_LOCKED"
            )
        if any(state is not TrackState.CLEAR for state in context.track_states.values()):
            return self._default(
                group,
                balise,
                context,
                "区段状态不安全，回落默认报文",
                True,
                "TRACK_STATE_UNSAFE",
            )
        if context.selected_template_id is None:
            return self._default(
                group,
                balise,
                context,
                "无匹配的正常报文",
                False,
                "NO_MATCHING_TELEGRAM",
            )
        try:
            selected = self._telegrams.build(
                context.selected_template_id,
                group.id,
                balise.id,
                context.direction or group.direction.value,
                context.state_version,
                context.overrides,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._default(
                group,
                balise,
                context,
                f"所选逻辑报文不存在：{exc}",
                True,
                "TELEGRAM_SELECTION_ERROR",
            )
        issues = self._telegrams.validate(selected)
        if issues:
            return self._default(
                group,
                balise,
                context,
                f"所选逻辑报文校验失败：{issues[0].path}",
                True,
                "TELEGRAM_VALIDATION_ERROR",
            )
        return TelegramSelectionResult(
            selected,
            TelegramMode.SELECTED,
            "命中正常报文选择规则",
            None,
            True,
            "SELECTED",
        )

    def _find_controlled(self, port_id: str):
        for group in self._groups.groups:
            for balise in group.balises:
                if balise.kind is BaliseKind.CONTROLLED and balise.leu_port_id == port_id:
                    return group, balise
        raise ValueError(f"未知或未绑定可控应答器的 LEU 端口：{port_id}")

    def _default(
        self,
        group,
        balise,
        context,
        reason: str,
        fault: bool,
        reason_code: str,
    ):
        telegram = self._telegrams.build(
            balise.default_telegram_id,
            group.id,
            balise.id,
            group.direction.value,
            context.state_version,
        )
        return TelegramSelectionResult(
            telegram=telegram,
            mode=TelegramMode.FAULT_DEFAULT if fault else TelegramMode.DEFAULT,
            reason=reason,
            alarm_level="CRITICAL" if fault else "WARNING",
            success=False,
            reason_code=reason_code,
        )
