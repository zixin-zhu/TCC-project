"""临时限速生命周期测试。"""

import pytest

from app.domain.temporary_speed import TemporarySpeedService, TemporarySpeedState


def test_tsr_must_be_prestored_before_activation_and_can_be_cancelled() -> None:
    service = TemporarySpeedService(line_start_m=0, line_end_m=10000)
    stored = service.prestore("TSR-1", 1000, 3000, 80, 100, 5000, now_ms=50)
    active = service.activate("TSR-1", now_ms=100)
    cancelled = service.cancel("TSR-1")

    assert stored.state is TemporarySpeedState.PRESTORED
    assert active.state is TemporarySpeedState.ACTIVE
    assert cancelled.state is TemporarySpeedState.CANCELLED


def test_invalid_or_expired_tsr_is_rejected() -> None:
    service = TemporarySpeedService(line_start_m=0, line_end_m=10000)

    assert service.validate(2000, 1000, 80, 100, 5000, now_ms=50)
    assert service.validate(1000, 2000, 0, 100, 5000, now_ms=50)
    assert service.validate(1000, 2000, 80, 100, 5000, now_ms=6000)


def test_overlapping_tsr_is_rejected_during_prestore() -> None:
    """防止同一里程和时间窗出现两条互相竞争的限速命令。"""
    service = TemporarySpeedService(line_start_m=0, line_end_m=10000)
    service.prestore("TSR-1", 1000, 3000, 80, 100, 5000, now_ms=50)

    with pytest.raises(ValueError, match="重叠"):
        service.prestore("TSR-2", 2500, 4000, 60, 200, 6000, now_ms=50)
