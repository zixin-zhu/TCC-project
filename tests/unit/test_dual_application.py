"""单进程双站编排必须保证先 A 后 B，并按 B、A 顺序关闭。"""

import json
import shutil
from pathlib import Path

import pytest
from PyQt5.QtCore import QObject, pyqtSignal

from app.core.exceptions import ConfigError
from app.dual_application import DualLifecycleState, DualStationApplication


ROOT = Path(__file__).resolve().parents[2]


class FakeWorker(QObject):
    server_ready = pyqtSignal(str, int)
    error_occurred = pyqtSignal(str)


class FakeRuntime:
    def __init__(self, name: str, events: list[str], *, stop_result: bool = True) -> None:
        self.name = name
        self.worker = FakeWorker()
        self.events = events
        self.stop_result = stop_result

    def start(self) -> None:
        self.events.append(f"start:{self.name}")

    def stop(self, *, timeout_ms: int = 3000) -> bool:
        self.events.append(f"stop:{self.name}")
        return self.stop_result


def test_b_starts_once_only_after_a_reports_real_listener_ready(qtbot) -> None:  # type: ignore[no-untyped-def]
    events: list[str] = []
    station_a = FakeRuntime("A", events)
    station_b = FakeRuntime("B", events)
    application = DualStationApplication(station_a, station_b)

    application.start()
    assert events == ["start:A"]

    station_a.worker.server_ready.emit("127.0.0.1", 9500)
    qtbot.waitUntil(lambda: events == ["start:A", "start:B"])
    station_a.worker.server_ready.emit("127.0.0.1", 9500)
    qtbot.wait(10)

    assert events == ["start:A", "start:B"]
    assert application.state is DualLifecycleState.RUNNING


def test_a_startup_error_prevents_b_from_starting(qtbot) -> None:  # type: ignore[no-untyped-def]
    events: list[str] = []
    station_a = FakeRuntime("A", events)
    station_b = FakeRuntime("B", events)
    application = DualStationApplication(station_a, station_b)

    application.start()
    station_a.worker.error_occurred.emit("监听失败：地址已占用")
    qtbot.waitUntil(lambda: application.state is DualLifecycleState.FAILED)

    assert events == ["start:A"]
    assert application.failure_reason == "A站启动失败：监听失败：地址已占用"


def test_stop_retries_only_failed_station_and_is_idempotent_after_success() -> None:
    events: list[str] = []
    station_a = FakeRuntime("A", events)
    station_b = FakeRuntime("B", events, stop_result=False)
    application = DualStationApplication(station_a, station_b)

    assert application.stop(timeout_ms=25) is False
    assert events == ["stop:B", "stop:A"]
    station_b.stop_result = True

    assert application.stop(timeout_ms=25) is True
    assert events == ["stop:B", "stop:A", "stop:B"]
    assert application.stop(timeout_ms=25) is True
    assert events == ["stop:B", "stop:A", "stop:B"]


def test_stop_retries_a_without_reclosing_successful_b() -> None:
    events: list[str] = []
    station_a = FakeRuntime("A", events, stop_result=False)
    station_b = FakeRuntime("B", events)
    application = DualStationApplication(station_a, station_b)

    assert application.stop(timeout_ms=25) is False
    station_a.stop_result = True

    assert application.stop(timeout_ms=25) is True
    assert events == ["stop:B", "stop:A", "stop:A"]


def test_build_rejects_mismatched_addresses_before_creating_databases(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    shutil.copytree(ROOT / "configs", config_dir)
    station_b_path = config_dir / "station_b.json"
    station_b = json.loads(station_b_path.read_text(encoding="utf-8"))
    station_b["network"]["port"] = 9501
    station_b_path.write_text(
        json.dumps(station_b, ensure_ascii=False), encoding="utf-8"
    )
    data_root = tmp_path / "data"

    with pytest.raises(ConfigError, match="地址或端口不一致"):
        DualStationApplication.build(config_dir=config_dir, data_root=data_root)

    assert not data_root.exists()


def test_build_closes_station_a_when_station_b_initialization_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """B 站装配失败时必须关闭已创建的 A 站数据库，避免半初始化泄漏。"""
    events: list[str] = []

    class FakeController:
        def close(self) -> None:
            events.append("close:A")

    class BuiltStationA:
        controller = FakeController()

    def build_runtime(*, station_id: str, config_dir: Path, data_dir: Path):
        if station_id == "A":
            return BuiltStationA()
        raise OSError("B database unavailable")

    monkeypatch.setattr(
        "app.dual_application.ApplicationRuntime.build", build_runtime
    )

    with pytest.raises(OSError, match="B database unavailable"):
        DualStationApplication.build(
            config_dir=ROOT / "configs", data_root=tmp_path / "data"
        )

    assert events == ["close:A"]
