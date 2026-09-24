"""LEU 正常选择与默认报文路径测试。"""

from pathlib import Path

import pytest

from app.core.enums import TelegramMode
from app.domain.balise_telegram import LogicalTelegramService
from app.domain.leu import LeuContext, LeuService
from app.infrastructure.config_loader import load_project_config, load_telegram_catalog


ROOT = Path(__file__).resolve().parents[2]


def _service() -> LeuService:
    project = load_project_config(ROOT / "configs", "A")
    telegrams = LogicalTelegramService(
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json")
    )
    return LeuService(project.balise_groups, telegrams, input_timeout_ms=3500)


def test_selected_route_template_is_used_when_input_is_fresh() -> None:
    result = _service().select_for_port(
        "LEU_A_1",
        LeuContext(True, 9000, 4, "TG_A_ROUTE", {}),
        now_ms=10_000,
    )

    assert result.mode is TelegramMode.SELECTED
    assert result.telegram.template_id == "TG_A_ROUTE"
    assert result.alarm_level is None


@pytest.mark.parametrize(
    "context, expected_text",
    [
        (LeuContext(False, 9000, 1, "TG_A_ROUTE", {}), "断联"),
        (LeuContext(True, 1000, 1, "TG_A_ROUTE", {}), "过期"),
        (LeuContext(True, 9000, 1, None, {}), "无匹配"),
    ],
)
def test_default_paths_are_deterministic(context, expected_text) -> None:
    result = _service().select_for_port("LEU_A_1", context, now_ms=10_000)

    assert result.telegram.template_id == "TG_A_DEFAULT"
    assert expected_text in result.reason
    assert result.mode in {TelegramMode.DEFAULT, TelegramMode.FAULT_DEFAULT}


def test_invalid_selected_telegram_falls_back_to_fault_default() -> None:
    result = _service().select_for_port(
        "LEU_A_1",
        LeuContext(
            True,
            9000,
            1,
            "TG_A_TSR",
            {"CTCS-2": {"start_m": 5000, "end_m": 1000}},
        ),
        now_ms=10_000,
    )

    assert result.mode is TelegramMode.FAULT_DEFAULT
    assert result.telegram.template_id == "TG_A_DEFAULT"
    assert result.alarm_level == "CRITICAL"
