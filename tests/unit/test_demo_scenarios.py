"""交付场景必须覆盖方案要求，并给出复位条件。"""

from app.services.demo_scenarios import DELIVERY_SCENARIOS


def test_delivery_catalog_contains_seven_complete_scenarios() -> None:
    assert {item.scenario_id for item in DELIVERY_SCENARIOS} == {
        "all-clear",
        "block-occupied",
        "track-fault",
        "red-lamp-failure",
        "temporary-speed",
        "direction-change-normal",
        "direction-change-disconnect",
    }
    assert all(item.steps for item in DELIVERY_SCENARIOS)
    assert all(item.expected_results for item in DELIVERY_SCENARIOS)
    assert all(item.reset_steps for item in DELIVERY_SCENARIOS)
