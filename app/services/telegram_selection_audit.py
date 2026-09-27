"""LEU 报文选择审计；仅保存教学仿真的可追溯记录。"""

from dataclasses import dataclass

from app.domain.leu import LeuContext, TelegramSelectionResult


@dataclass(frozen=True)
class TelegramSelectionAuditRecord:
    station_id: str
    port_id: str
    direction: str | None
    route_ids: tuple[str, ...]
    temporary_speed_ids: tuple[str, ...]
    state_version: int
    template_id: str
    mode: str
    success: bool
    reason_code: str
    reason: str
    occurred_at_ms: int


class TelegramSelectionAuditService:
    """按时间顺序保存报文选择输入、结果和结构化原因。"""

    def __init__(self) -> None:
        self._records: list[TelegramSelectionAuditRecord] = []

    @property
    def records(self) -> tuple[TelegramSelectionAuditRecord, ...]:
        return tuple(self._records)

    def append(
        self,
        station_id: str,
        port_id: str,
        context: LeuContext,
        result: TelegramSelectionResult,
        *,
        occurred_at_ms: int,
    ) -> TelegramSelectionAuditRecord:
        record = TelegramSelectionAuditRecord(
            station_id=station_id,
            port_id=port_id,
            direction=context.direction,
            route_ids=tuple(context.route_ids),
            temporary_speed_ids=tuple(context.temporary_speed_ids),
            state_version=context.state_version,
            template_id=result.telegram.template_id,
            mode=result.mode.value,
            success=result.success,
            reason_code=result.reason_code,
            reason=result.reason,
            occurred_at_ms=occurred_at_ms,
        )
        self._records.append(record)
        return record
