"""离屏生成三种分辨率的正式双站控制台视觉验收截图。"""

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
from app.dual_application import DualStationApplication
from app.ui.qt_bootstrap import configure_qt_plugin_path


def _prepare_visual_state(runtime: DualStationApplication) -> None:
    """只为截图准备一致健康快照；不把截图当成真实网络验收证据。"""
    boundary_states = {f"Q{index}": TrackState.CLEAR for index in range(1, 5)}
    for station, peer_id in (
        (runtime.station_a, "B"),
        (runtime.station_b, "A"),
    ):
        station.controller.set_connection_state(ConnectionState.HEALTHY)
        station.controller.update_peer_snapshot(
            PeerSnapshot(peer_id, boundary_states, 0, station.controller.now_ms())
        )
        station.controller.restore_authoritative_direction(RunningDirection.A_TO_B)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成双站正式控制台验收截图")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "acceptance" / "dual-dashboard",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    configure_qt_plugin_path()
    from PyQt5.QtWidgets import QApplication

    from app.ui.dual_main_window import DualStationMainWindow

    application = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="tcc-dual-dashboard-") as temporary:
        runtime = DualStationApplication.build(
            config_dir=PROJECT_ROOT / "configs",
            data_root=Path(temporary) / "data",
        )
        _prepare_visual_state(runtime)
        window = DualStationMainWindow(runtime)
        window.show()
        for width, height in ((1280, 800), (1440, 900), (1920, 1080)):
            window.resize(width, height)
            application.processEvents()
            output = args.output / f"dual_dashboard_{width}x{height}.png"
            if not window.grab().save(str(output), "PNG"):
                raise RuntimeError(f"截图保存失败：{output}")
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
