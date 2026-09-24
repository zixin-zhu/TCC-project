"""教学仿真封装的确定性测试。"""

from pathlib import Path

from app.domain.balise_telegram import LogicalTelegramService, SimulationEnvelopeCodec
from app.infrastructure.config_loader import load_telegram_catalog


ROOT = Path(__file__).resolve().parents[2]


def test_envelope_is_stable_and_clearly_named() -> None:
    service = LogicalTelegramService(
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json")
    )
    first = service.build("TG_A_FIXED", "BG_A_01", "B_A_FIX", "A_TO_B", 1)
    second = service.build("TG_A_FIXED", "BG_A_01", "B_A_FIX", "A_TO_B", 1)

    encoded_a = SimulationEnvelopeCodec.encode(first)
    encoded_b = SimulationEnvelopeCodec.encode(second)

    assert encoded_a.format == "simulation_envelope"
    assert encoded_a.canonical_json == encoded_b.canonical_json
    assert encoded_a.crc32 == encoded_b.crc32
    assert encoded_a.hex_payload == encoded_a.canonical_json.encode().hex().upper()


def test_envelope_crc_changes_when_payload_changes() -> None:
    service = LogicalTelegramService(
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json")
    )
    original = service.build("TG_A_FIXED", "BG_A_01", "B_A_FIX", "A_TO_B", 1)
    changed = service.build("TG_A_FIXED", "BG_A_01", "B_A_FIX", "A_TO_B", 2)

    assert SimulationEnvelopeCodec.encode(original).crc32 != SimulationEnvelopeCodec.encode(changed).crc32
