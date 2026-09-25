"""交付场景必须覆盖方案要求，并给出复位条件。"""

from app.services.demo_scenarios import DELIVERY_SCENARIOS
from app.ui.dual_main_window import NAVIGATION_ITEMS
from app.ui.dual_operations_pages import DUAL_OPERATION_BUTTON_OBJECTS


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


def test_every_scenario_targets_real_dual_page_station_and_controls() -> None:
    assert all(item.target_page in NAVIGATION_ITEMS for item in DELIVERY_SCENARIOS)
    assert all(item.target_station in {"A站", "B站", "A/B双站"} for item in DELIVERY_SCENARIOS)
    assert all(item.preconditions for item in DELIVERY_SCENARIOS)
    assert all(item.control_object_names for item in DELIVERY_SCENARIOS)
    assert all(
        set(item.control_object_names) <= DUAL_OPERATION_BUTTON_OBJECTS
        for item in DELIVERY_SCENARIOS
    )
