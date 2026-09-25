"""A/B 双站同屏模式统一入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from app.core.exceptions import ConfigError
from app.core.models import ProjectConfig
from app.dual_application import (
    DualStationApplication,
    validate_dual_station_config,
)


PROJECT_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    """创建双站入口参数，默认路径均相对于项目根目录。"""
    parser = argparse.ArgumentParser(description="CTCS-2 TCC A/B 双站同屏仿真系统")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs",
        help="A/B 配置目录，默认使用项目 configs",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=PROJECT_ROOT / "data" / "dual",
        help="双站 SQLite 数据根目录，默认使用 data/dual",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只交叉校验 A/B 配置，不创建窗口、数据库或网络线程",
    )
    return parser


def _print_validation_summary(
    config_a: ProjectConfig, config_b: ProjectConfig
) -> None:
    """输出适合人工检查和自动化测试的双站配置摘要。"""
    endpoint = config_a.station.network
    for config in (config_a, config_b):
        print(
            "配置校验通过 "
            f"station={config.station.station_id} "
            f"role={config.station.network.role.value} "
            f"sections={len(config.topology.sections)} "
            f"balise_groups={len(config.balise_groups.groups)}"
        )
    print(f"shared_endpoint={endpoint.host}:{endpoint.port}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """校验双站配置，随后装配一个进程内的两套独立运行时。"""
    args = build_parser().parse_args(argv)
    try:
        config_a, config_b = validate_dual_station_config(args.config)
    except ConfigError as exc:
        print(f"双站配置校验失败：{exc}")
        return 2

    if args.validate_only:
        _print_validation_summary(config_a, config_b)
        return 0

    from app.ui.qt_bootstrap import configure_qt_plugin_path

    configure_qt_plugin_path()
    from PyQt5.QtWidgets import QApplication

    from app.ui.dual_main_window import DualStationMainWindow

    app = QApplication.instance() or QApplication([sys.argv[0]])
    try:
        runtime = DualStationApplication.build(
            config_dir=args.config, data_root=args.data_root
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"双站运行环境初始化失败：{exc}")
        return 3
    window = DualStationMainWindow(runtime)
    window.show()
    runtime.start()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
