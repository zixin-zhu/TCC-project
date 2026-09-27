"""统一接口状态在站间链路故障和恢复时的集成行为。"""

from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal

from app.application import ApplicationRuntime
from app.core.enums import ConnectionState
from app.core.interface_models import InterfaceHealth, InterfaceId


ROOT = Path(__file__).resolve().parents[2]


class FakeWorker(QObject):
    state_changed = pyqtSignal(object)
    message_received = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    message_sent = pyqtSignal(object)

    def submit(self, *_args: object, **_kwargs: object) -> None:
        """接收控制器初始化时发布的状态；本测试不需要真正传输。"""
        return None


class FakeThread:
    def start(self) -> None:
        pass


def test_peer_interface_failure_is_visible_and_recoverable(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """U 接口必须随连接状态降级，并在协议恢复后回到健康。"""
    worker = FakeWorker()
    runtime = ApplicationRuntime.build(
        station_id="A",
        config_dir=ROOT / "configs",
        data_dir=tmp_path,
        worker=worker,
        network_thread=FakeThread(),
    )

    worker.state_changed.emit(ConnectionState.DEGRADED)
    qtbot.waitUntil(
        lambda: runtime.interface_status.get(InterfaceId.U).health
        is InterfaceHealth.DEGRADED,
        timeout=1000,
    )
    assert "DEGRADED" in runtime.interface_status.get(InterfaceId.U).message

    worker.state_changed.emit(ConnectionState.HEALTHY)
    qtbot.waitUntil(
        lambda: runtime.interface_status.get(InterfaceId.U).health
        is InterfaceHealth.HEALTHY,
        timeout=1000,
    )
    assert "HEALTHY" in runtime.interface_status.get(InterfaceId.U).message
