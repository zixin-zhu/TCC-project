"""离屏渲染 A/B 正式窗口，生成可重复的课程验收截图。"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.enums import ConnectionState, RunningDirection, TrackState
from app.core.models import PeerSnapshot
from app.infrastructure.config_loader import (
    load_coding_rules,
    load_project_config,
    load_telegram_catalog,
)
from app.infrastructure.sqlite_repository import SQLiteRepository
from app.services.alarm_service import AlarmService
from app.services.persistence_service import PersistenceService
from app.services.tcc_controller import TccController
from app.ui.qt_bootstrap import configure_qt_plugin_path


def _controller(station_id: str, data_dir: Path) -> TccController:
    config_dir = PROJECT_ROOT / "configs"
    config = load_project_config(config_dir, station_id)
    alarms = AlarmService()
    controller = TccController(
        config,
        load_coding_rules(config_dir / "coding_rules.json"),
        load_telegram_catalog(config_dir / "telegram_packets.json"),
        alarms=alarms,
        persistence=PersistenceService(
            SQLiteRepository(data_dir / f"screenshot_{station_id.lower()}.db"),
            alarms,
        ),
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


def main() -> int:
    parser = argparse.ArgumentParser(description="生成阶段7正式窗口验收截图")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "acceptance" / "screenshots",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    configure_qt_plugin_path()
    from PyQt5.QtWidgets import QApplication

    from app.ui.main_window import TccMainWindow

    application = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="tcc-screenshot-") as temporary:
        for station_id in ("A", "B"):
            controller = _controller(station_id, Path(temporary))
            window = TccMainWindow(controller)
            window.show()
            application.processEvents()
            output = args.output / f"station_{station_id.lower()}_overview.png"
            if not window.grab().save(str(output), "PNG"):
                raise RuntimeError(f"截图保存失败：{output}")
            window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
