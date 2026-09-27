"""阶段 3：LEU 容量余量和报文选择审计。"""

from pathlib import Path

from app.core.enums import TelegramMode
from app.domain.balise_telegram import LogicalTelegramService
from app.domain.leu import LeuContext, LeuService, LeuStorageModel
from app.infrastructure.config_loader import load_project_config, load_telegram_catalog
from app.services.telegram_selection_audit import TelegramSelectionAuditService


ROOT = Path(__file__).resolve().parents[2]


def _service() -> LeuService:
    project = load_project_config(ROOT / "configs", "A")
    telegrams = LogicalTelegramService(
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json")
    )
    return LeuService(
        project.balise_groups,
        telegrams,
        input_timeout_ms=3500,
        storage=LeuStorageModel(capacity_total=5, capacity_used=3),
    )


def test_leu_storage_keeps_twenty_percent_reserve_and_rejects_new_template() -> None:
    storage = LeuStorageModel(capacity_total=5, capacity_used=3)
    service = _service()

    assert storage.reserve_ratio >= 0.20
    assert service.store_template("TG_A_ROUTE").success is True
    assert service.store_template("TG_A_TSR").success is False
    assert "余量" in service.store_template("TG_A_TSR").reason


def test_default_selection_is_not_reported_as_successful_send_and_is_audited() -> None:
    service = _service()
    audit = TelegramSelectionAuditService()
    context = LeuContext(
        connected=False,
        input_updated_ms=9000,
        state_version=4,
        selected_template_id="TG_A_ROUTE",
        overrides={},
        direction="A_TO_B",
        route_ids=("A_DEPART",),
        operation_locked=False,
    )

    result = service.select_for_port("LEU_A_1", context, now_ms=10_000)
    audit.append("A", "LEU_A_1", context, result, occurred_at_ms=10_000)

    assert result.mode is TelegramMode.FAULT_DEFAULT
    assert result.success is False
    assert audit.records[-1].reason_code == "LEU_DISCONNECTED"
    assert audit.records[-1].direction == "A_TO_B"
