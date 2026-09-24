"""TCC 教学仿真系统统一入口。"""

import argparse
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
        "--validate-only",
        action="store_true",
        help="只校验配置，不创建窗口或启动网络",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """校验启动参数和配置；阶段 6 将在此处接入正式单站窗口。"""
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

    print("阶段 1 已完成配置校验；正式单站界面将在阶段 6 接入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
