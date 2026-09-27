"""阶段 4：TCC 启动自检顺序和双机教学诊断。"""

import pytest

from app.core.interface_models import InterfaceHealth, StartupStep
from app.services.interface_status_service import (
    DualComputeDiagnostic,
    InterfaceStatusService,
)


def test_startup_self_check_follows_specified_order() -> None:
    service = InterfaceStatusService()

    service.begin_startup(now_ms=0)
    order = []
    for step in StartupStep:
        order.append(service.complete_startup_step(step, success=True, now_ms=100))

    assert tuple(item.step for item in order) == tuple(StartupStep)
    assert service.startup_complete is True
    assert all(item.health is InterfaceHealth.HEALTHY for item in service.snapshot())


def test_failed_startup_step_stops_sequence_and_does_not_claim_healthy() -> None:
    service = InterfaceStatusService()
    service.begin_startup(now_ms=0)
    service.complete_startup_step(StartupStep.LOGIC_UNIT, success=True, now_ms=100)

    result = service.complete_startup_step(
        StartupStep.SAFETY_IO, success=False, now_ms=200, message="安全输入输出自检失败"
    )

    assert result.success is False
    assert service.startup_complete is False
    assert service.failed_step is StartupStep.SAFETY_IO
    assert service.get(StartupStep.SAFETY_IO.interface_id).health is InterfaceHealth.FAILED
    with pytest.raises(ValueError, match="不能继续"):
        service.complete_startup_step(StartupStep.DATA_STORE, success=True, now_ms=300)


def test_dual_compute_diagnostic_reports_match_and_mismatch() -> None:
    match = DualComputeDiagnostic.compare(
        primary_result={"code": "L", "state_version": 3},
        standby_result={"code": "L", "state_version": 3},
    )
    mismatch = DualComputeDiagnostic.compare(
        primary_result={"code": "L", "state_version": 3},
        standby_result={"code": "HU", "state_version": 3},
    )

    assert match.consistent is True
    assert match.degraded is False
    assert mismatch.consistent is False
    assert mismatch.degraded is True
    assert "主备" in mismatch.reason
