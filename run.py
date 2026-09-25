"""TCC 教学仿真系统统一入口。"""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from app.core.exceptions import ConfigError
from app.infrastructure.config_loader import load_project_config


PROJECT_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器，避免入口逻辑散落到界面模块。"""
    parser = argparse.ArgumentParser(description="CTCS-2 TCC 教学仿真系统")
    parser.add_argument("--station", required=True, choices=("A", "B"))
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs",
        help="配置目录，默认使用项目 configs",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data",
        help="SQLite 历史数据目录，默认使用项目 data",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只校验配置，不创建窗口或启动网络",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """校验参数；非验证模式装配正式单站窗口、网络线程和持久化。"""
    args = build_parser().parse_args(argv)
    try:
        config = load_project_config(args.config, args.station)
    except ConfigError as exc:
        print(f"配置校验失败：{exc}")
        return 2

    if args.validate_only:
        print(
            "配置校验通过 "
            f"station={config.station.station_id} "
            f"role={config.station.network.role.value} "
            f"sections={len(config.topology.sections)} "
            f"balise_groups={len(config.balise_groups.groups)}"
        )
        return 0

    from app.ui.qt_bootstrap import configure_qt_plugin_path

    configure_qt_plugin_path()
    from PyQt5.QtWidgets import QApplication

    from app.application import ApplicationRuntime
    from app.ui.main_window import TccMainWindow

    app = QApplication.instance() or QApplication([sys.argv[0]])
    try:
        runtime = ApplicationRuntime.build(
            station_id=config.station.station_id,
            config_dir=args.config,
            data_dir=args.data_dir,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        # 权威方向库无法读取时必须阻止启动，不能用默认方向覆盖历史真值。
        print(f"运行环境初始化失败：{exc}")
        return 3
    window = TccMainWindow(runtime.controller, network_thread=runtime)
    window.show()
    runtime.start()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
