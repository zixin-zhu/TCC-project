"""阶段 3：CTCS-2 六档限速、重叠范围和生命周期字段。"""

import pytest

from app.domain.temporary_speed import (
    CTCS2_TSR_SPEEDS_KMH,
    TemporarySpeedService,
    TemporarySpeedState,
)


def test_ctcs2_tsr_accepts_only_six_specified_speed_levels() -> None:
    service = TemporarySpeedService(0, 20_000, tcc_id="TCC_A")

    for index, speed in enumerate(CTCS2_TSR_SPEEDS_KMH):
        item = service.prestore(
            f"TSR-{index}",
            index * 500,
            index * 500 + 300,
            speed,
            100,
            5000,
            now_ms=50,
            braking_distance_m=120,
            update_point="B1",
        )
        assert item.tcc_id == "TCC_A"
        assert item.overlap_m == 80
        assert item.braking_distance_m == 120
        assert item.update_point == "B1"

    assert tuple(CTCS2_TSR_SPEEDS_KMH) == (45, 80, 120, 160, 200, 250)


def test_tsr_rejects_non_ctcs2_speed_and_ranges_within_eighty_meters() -> None:
    service = TemporarySpeedService(0, 20_000, tcc_id="TCC_A")

    with pytest.raises(ValueError, match="等级"):
        service.prestore("BAD", 1000, 2000, 60, 100, 5000, now_ms=50)
    service.prestore("TSR-1", 1000, 2000, 80, 100, 5000, now_ms=50)

    with pytest.raises(ValueError, match="重叠"):
        service.prestore("TSR-2", 2070, 3000, 120, 100, 5000, now_ms=50)
