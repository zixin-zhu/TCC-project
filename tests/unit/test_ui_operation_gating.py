"""UI 操作门禁一致性的回归测试（BugFix 阶段）。

背景：双站聚合安全锁闭(operation_locked / set_external_operation_lock)时，
列车相关按钮应当一致禁用。此前「暂停/复位」按钮遗漏了禁用，导致界面状态
不一致——锁闭时用户仍可点「暂停/复位」，造成「操作不了」的困惑。
本文件用键盘驱动真实组件验证修复。
"""

from pathlib import Path
from types import SimpleNamespace

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox

from app.core.enums import ConnectionState, RunningDirection, TrackState
from app.core.models import PeerSnapshot
from app.infrastructure.config_loader import (
    load_coding_rules,
    load_project_config,
    load_telegram_catalog,
)
from app.services.alarm_service import AlarmService
from app.services.dual_train_coordinator import DualTrainCoordinator
from app.services.tcc_controller import TccController
from app.ui.dual_main_window import DualStationMainWindow
from app.ui.dual_operations_pages import TrainOperationsPage
from app.ui.station_detail_widget import StationDetailWidget

ROOT = Path(__file__).resolve().parents[2]


class _MemoryPersistence:
    """内存持久化替身，避免测试依赖真实 SQLite 文件。"""

    def save_operation(self, _entry):  # type: ignore[no-untyped-def]
        return True

    def save_telegram(self, _entry):  # type: ignore[no-untyped-def]
        return True

    def save_direction_authority(self, _entry):  # type: ignore[no-untyped-def]
        return True

    def load_direction_authority(self, _station_id, *, now_ms):  # type: ignore[no-untyped-def]
        return None

    def close(self) -> None:
        pass


def _controller(station_id: str) -> TccController:
    """按正式配置构造一个健康状态的真实 TCC 控制器。"""
    controller = TccController(
        load_project_config(ROOT / "configs", station_id),
        load_coding_rules(ROOT / "configs" / "coding_rules.json"),
        load_telegram_catalog(ROOT / "configs" / "telegram_packets.json"),
        alarms=AlarmService(),
        persistence=_MemoryPersistence(),
        publish_state=lambda _payload: None,
        snapshot_listener=lambda _snapshot: None,
        clock_ms=lambda: 10_000,
        send_direction=lambda _message: None,
    )
    controller.set_connection_state(ConnectionState.HEALTHY)
    controller.update_peer_snapshot(
        PeerSnapshot(
            "B" if station_id == "A" else "A",
            {f"Q{index}": TrackState.CLEAR for index in range(1, 5)},
            0,
            10_000,
        )
    )
    controller.restore_authoritative_direction(RunningDirection.A_TO_B)
    return controller


def test_train_page_disables_all_buttons_including_pause_reset_when_locked(
    qapp, qtbot  # type: ignore[no-untyped-def]
) -> None:
    """问题 1：聚合锁闭时，「暂停/复位」必须与「创建/发送/开始」一起被禁用。"""
    station_a = _controller("A")
    station_b = _controller("B")
    coordinator = DualTrainCoordinator(station_a, station_b)
    page = TrainOperationsPage(station_a, station_b, coordinator)
    qtbot.addWidget(page)

    # 解锁状态下全部可用
    page.set_snapshot(SimpleNamespace(operation_locked=False))
    for button in (
        page.create_button,
        page.dispatch_button,
        page.start_button,
        page.pause_button,
        page.reset_button,
    ):
        assert button.isEnabled(), f"{button.objectName()} 在解锁时应可用"

    # 锁闭状态下全部禁用（含此前遗漏的 pause / reset）
    page.set_snapshot(SimpleNamespace(operation_locked=True))
    for button in (
        page.create_button,
        page.dispatch_button,
        page.start_button,
        page.pause_button,
        page.reset_button,
    ):
        assert not button.isEnabled(), (
            f"{button.objectName()} 在锁闭时应被一致禁用"
        )


def test_station_detail_train_buttons_consistent_under_external_lock(
    qapp, qtbot  # type: ignore[no-untyped-def]
) -> None:
    """问题 2：双站外部安全锁闭时，单站控制页列车按钮应全部一致禁用。"""
    station_a = _controller("A")
    widget = StationDetailWidget(station_a, include_train_page=True)
    qtbot.addWidget(widget)

    assert widget.pause_train_button.isEnabled()
    assert widget.reset_train_button.isEnabled()

    # 外部锁闭触发后，含「暂停/复位」在内的列车按钮必须全部禁用
    widget.set_external_operation_lock(True, "测试锁闭")
    for button in (
        widget.create_train_button,
        widget.dispatch_train_button,
        widget.start_train_button,
        widget.pause_train_button,
        widget.reset_train_button,
    ):
        assert not button.isEnabled(), (
            f"{button.objectName()} 在外部锁闭时应被禁用"
        )


def test_window_refuses_to_close_and_warns_when_runtime_stop_fails(
    qapp, qtbot, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    """问题 5：网络停止失败(关闭超时)时，窗口必须拒绝关闭并给出明确警告提示。

    此前关闭失败只会改顶部文字后静默拒绝退出，用户看不到原因而误以为“卡死”。
    """
    station_a = _controller("A")
    station_b = _controller("B")

    class _FailingRuntime(SimpleNamespace):
        """stop() 恒失败的最小运行时代理。"""

        def stop(self, *, timeout_ms=3000) -> bool:  # type: ignore[no-untyped-def]
            return False

        def set_station_network_fault(self, station_id, enabled):  # type: ignore[no-untyped-def]
            pass

    runtime = _FailingRuntime()
    runtime.station_a = SimpleNamespace(controller=station_a)
    runtime.station_b = SimpleNamespace(controller=station_b)

    window = DualStationMainWindow(runtime)
    qtbot.addWidget(window)

    # 记录是否调用了“关闭失败提示”；用无害替身替换模态弹窗，避免测试阻塞。
    notified: list[bool] = []
    monkeypatch.setattr(
        window, "_notify_close_failed", lambda: notified.append(True)
    )

    window.close()

    # 关闭被拒绝：_closed 仍为 False，窗口未真正销毁，且确实给出了失败提示。
    assert notified == [True]
    assert window._closed is False


def test_corridor_drawing_tolerates_empty_balise_group(
    qapp, qtbot  # type: ignore[no-untyped-def]
) -> None:
    """问题 6：应答器组为空(无 balise 成员)时线路图绘制不得 IndexError。

    原实现直接访问 ``group.balises[0]``，遇到空组会越界崩溃；此处验证
    空安全保护在正常绘制路径下不抛异常。
    """
    from dataclasses import replace

    from PyQt5.QtGui import QPainter

    from app.core.enums import BaliseDirection, BaliseKind
    from app.core.models import BaliseConfig, BaliseGroupConfig, BaliseGroupsConfig
    from app.infrastructure.config_loader import load_project_config
    from app.ui.corridor_overview_widget import CorridorOverviewWidget

    project = load_project_config(ROOT / "configs", "A")
    topology = project.topology
    section_id = topology.sections[0].id

    # 构造一个「不含任何应答器成员」的空应答器组，替换到真实配置上。
    empty_group = BaliseGroupConfig(
        id="EMPTY_GROUP",
        direction=BaliseDirection.A_TO_B,
        section_id=section_id,
        balises=tuple(),
    )
    empty_config = replace(
        project.balise_groups, groups=(empty_group,)
    )

    widget = CorridorOverviewWidget(topology, empty_config)
    qtbot.addWidget(widget)
    widget.resize(1200, 400)

    # 先按 paintEvent 的真实顺序填充区段矩形，再绘制应答器分支：
    # 空组必须被空安全跳过，不应触发 IndexError。
    widget._section_rects = widget._layout_sections()  # type: ignore[attr-defined]
    painter = QPainter(widget)
    try:
        widget._draw_balises(painter)  # type: ignore[attr-defined]
    finally:
        painter.end()
