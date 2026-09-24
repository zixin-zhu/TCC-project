"""可控应答器的 LEU 教学报文选择。"""

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from app.core.enums import BaliseKind, TelegramMode
from app.core.models import BaliseGroupsConfig
from app.domain.balise_telegram import LogicalTelegram, LogicalTelegramService


@dataclass(frozen=True)
class LeuContext:
    connected: bool
    input_updated_ms: int
    state_version: int
    selected_template_id: Optional[str]
    overrides: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class TelegramSelectionResult:
    telegram: LogicalTelegram
    mode: TelegramMode
    reason: str
    alarm_level: Optional[str]


class LeuService:
    """将 TCC 上下文选择为正常报文或确定的默认报文。"""

    def __init__(
        self,
        groups: BaliseGroupsConfig,
        telegrams: LogicalTelegramService,
        input_timeout_ms: int,
    ):
        self._groups = groups
        self._telegrams = telegrams
        self._timeout_ms = input_timeout_ms

    def select_for_port(
        self, port_id: str, context: LeuContext, now_ms: int
    ) -> TelegramSelectionResult:
        group, balise = self._find_controlled(port_id)
        if not context.connected:
            return self._default(group, balise, context, "LEU 输入断联", True)
        if now_ms - context.input_updated_ms > self._timeout_ms:
            return self._default(group, balise, context, "LEU 输入过期", True)
        if context.selected_template_id is None:
            return self._default(group, balise, context, "无匹配的正常报文", False)
        selected = self._telegrams.build(
            context.selected_template_id,
            group.id,
            balise.id,
            group.direction.value,
            context.state_version,
            context.overrides,
        )
        issues = self._telegrams.validate(selected)
        if issues:
            return self._default(
                group, balise, context, f"所选逻辑报文校验失败：{issues[0].path}", True
            )
        return TelegramSelectionResult(
            selected, TelegramMode.SELECTED, "命中正常报文选择规则", None
        )

    def _find_controlled(self, port_id: str):
        for group in self._groups.groups:
            for balise in group.balises:
                if balise.kind is BaliseKind.CONTROLLED and balise.leu_port_id == port_id:
                    return group, balise
        raise ValueError(f"未知或未绑定可控应答器的 LEU 端口：{port_id}")

    def _default(self, group, balise, context, reason: str, fault: bool):
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
        )
