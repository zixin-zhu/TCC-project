"""双站窗口关闭后的线程、数据库和端口释放验收。"""

import socket
import sqlite3
from pathlib import Path

from PyQt5.QtWidgets import QPushButton

from app.dual_application import DualStationApplication
from app.ui.dual_main_window import DualStationMainWindow, NAVIGATION_ITEMS
from tests.integration.test_dual_application_integration import (
    _copy_configs_with_port,
    _free_port,
)


def test_close_releases_threads_databases_and_listener_port(
    tmp_path: Path, qtbot
) -> None:  # type: ignore[no-untyped-def]
    port = _free_port()
    config_dir = tmp_path / "configs"
    data_root = tmp_path / "data"
    _copy_configs_with_port(config_dir, port)
    runtime = DualStationApplication.build(
        config_dir=config_dir, data_root=data_root
    )
    window = DualStationMainWindow(runtime)
    qtbot.addWidget(window)
    runtime.start()
    qtbot.waitUntil(
        lambda: (
            window.aggregator.snapshot is not None
            and window.aggregator.snapshot.communication_healthy
        ),
        timeout=5000,
    )

    assert window.close()
    assert not runtime.station_a.network_thread.thread.isRunning()
    assert not runtime.station_b.network_thread.thread.isRunning()
    assert not window.train_coordinator.timer.isActive()

    for database in (
        data_root / "A" / "tcc_a.db",
        data_root / "B" / "tcc_b.db",
    ):
        with sqlite3.connect(database) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))


def test_all_navigation_pages_are_visible_and_buttons_are_named(qtbot) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.test_dual_main_window import DualRuntimeStub

    window = DualStationMainWindow(DualRuntimeStub())
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()

    assert window.pages.count() == len(NAVIGATION_ITEMS) == 12
    for index, expected_name in enumerate(NAVIGATION_ITEMS):
        window.navigation.setCurrentRow(index)
        assert window.pages.currentWidget().isVisible(), expected_name

    buttons = window.findChildren(QPushButton)
    assert buttons
    assert all(button.text().strip() for button in buttons)
    assert all(
        page.result_label.text().startswith("操作结果：")
        for page in (
            window.track_operations_page,
            window.signal_operations_page,
            window.tsr_operations_page,
            window.direction_operations_page,
            window.network_status_page,
            window.train_operations_page,
        )
    )
