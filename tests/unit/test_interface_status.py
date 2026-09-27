"""阶段 4：P/Q/R/S/T/U/V/W 接口状态模型。"""

from app.core.interface_models import InterfaceId, InterfaceHealth
from app.services.interface_status_service import InterfaceStatusService


def test_all_ctcs2_interfaces_start_disconnected_and_can_be_observed() -> None:
    service = InterfaceStatusService()

    snapshot = service.snapshot()

    assert tuple(item.interface_id for item in snapshot) == tuple(InterfaceId)
    assert all(item.health is InterfaceHealth.DISCONNECTED for item in snapshot)


def test_interface_failure_is_degraded_until_explicit_recovery() -> None:
    service = InterfaceStatusService()
    service.set_state(InterfaceId.S, InterfaceHealth.HEALTHY, now_ms=100, message="LEU在线")
    service.set_state(InterfaceId.S, InterfaceHealth.FAILED, now_ms=200, message="发送失败")

    failed = service.get(InterfaceId.S)
    assert failed.health is InterfaceHealth.FAILED
    assert failed.message == "发送失败"

    service.set_state(InterfaceId.S, InterfaceHealth.HEALTHY, now_ms=300, message="恢复")
    assert service.get(InterfaceId.S).health is InterfaceHealth.HEALTHY
