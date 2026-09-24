"""CTCS-2 教学逻辑报文测试。"""

from dataclasses import replace
from pathlib import Path

from app.domain.balise_telegram import LogicalTelegramService
from app.infrastructure.config_loader import load_telegram_catalog


ROOT = Path(__file__).resolve().parents[2]


def _service() -> LogicalTelegramService:
    return LogicalTelegramService(
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json")
    )


def test_minimum_packet_set_builds_a_traceable_logical_telegram() -> None:
    service = _service()
    telegram = service.build(
        "TG_A_FIXED", "BG_A_01", "B_A_FIX", "A_TO_B", state_version=7
    )

    assert [packet.packet_id for packet in telegram.packets] == [
        "ETCS-5", "ETCS-21", "ETCS-27", "CTCS-1"
    ]
    assert telegram.state_version == 7
    assert service.validate(telegram) == ()


def test_invalid_speed_override_reports_field_path() -> None:
    service = _service()
    telegram = service.build(
        "TG_A_FIXED",
        "BG_A_01",
        "B_A_FIX",
        "A_TO_B",
        state_version=1,
        overrides={"ETCS-27": {"speed_kmh": 800}},
    )

    issues = service.validate(telegram)

    assert any(issue.path.endswith("ETCS-27.speed_kmh") for issue in issues)


def test_temporary_speed_packet_rejects_reversed_range() -> None:
    service = _service()
    telegram = service.build(
        "TG_A_TSR",
        "BG_A_01",
        "B_A_CTL",
        "A_TO_B",
        state_version=2,
        overrides={"CTCS-2": {"start_m": 3000, "end_m": 2000}},
    )

    assert any("start_m" in issue.path for issue in service.validate(telegram))


def test_direction_and_template_packet_order_are_validated() -> None:
    """防止绕过 build 后把非法方向或乱序信息包送入 LEU。"""
    service = _service()
    valid = service.build("TG_A_FIXED", "BG_A_01", "B_A_FIX", "A_TO_B", 1)
    invalid = replace(valid, direction="SIDEWAYS", packets=tuple(reversed(valid.packets)))

    issues = service.validate(invalid)

    assert any(issue.path == "direction" for issue in issues)
    assert any(issue.path == "packets" and "顺序" in issue.message for issue in issues)
