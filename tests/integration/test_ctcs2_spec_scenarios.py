"""CTCS-2 规范场景验收矩阵：把关键要求绑定到可执行证据。"""

import json
from pathlib import Path

from app.core.interface_models import InterfaceId, StartupStep
from app.domain.temporary_speed import CTCS2_TSR_SPEEDS_KMH
from app.services.demo_scenarios import DELIVERY_SCENARIOS


ROOT = Path(__file__).resolve().parents[2]


def test_delivery_catalog_covers_all_ctcs2_demo_scenario_ids() -> None:
    scenario_ids = {item.scenario_id for item in DELIVERY_SCENARIOS}
    assert scenario_ids == {
        "all-clear",
        "block-occupied",
        "track-fault",
        "red-lamp-failure",
        "temporary-speed",
        "direction-change-normal",
        "direction-change-disconnect",
    }
    for scenario in DELIVERY_SCENARIOS:
        assert scenario.preconditions
        assert scenario.control_object_names
        assert scenario.steps
        assert scenario.expected_results
        assert scenario.reset_steps


def test_ctcs2_spec_configuration_matrix_is_complete() -> None:
    rules = json.loads((ROOT / "configs" / "ctcs2_tsr_levels.json").read_text())
    assert tuple(rules["allowed_speeds_kmh"]) == CTCS2_TSR_SPEEDS_KMH
    assert rules["overlap_m"] == 80
    assert set(rules["required_fields"]) == {
        "start_m",
        "end_m",
        "braking_distance_m",
        "tcc_id",
        "update_point",
    }
    coding = json.loads((ROOT / "configs" / "ctcs2_coding_rules.json").read_text())
    protection = json.loads(
        (ROOT / "configs" / "ctcs2_protection_rules.json").read_text()
    )
    assert coding["offline_code"] == "OFFLINE"
    assert protection["unknown_state_action"] == "HU"


def test_interface_and_startup_matrix_matches_ctcs2_requirement() -> None:
    assert tuple(InterfaceId) == tuple(InterfaceId(letter) for letter in "PQRSTUVW")
    assert tuple(step.interface_id for step in StartupStep) == (
        InterfaceId.R,
        InterfaceId.T,
        InterfaceId.R,
        InterfaceId.T,
        InterfaceId.Q,
        InterfaceId.U,
        InterfaceId.S,
    )
