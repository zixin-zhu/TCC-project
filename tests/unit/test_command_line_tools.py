"""阶段 1 命令行交付物测试。"""

import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("station_id, role", [("A", "SERVER"), ("B", "CLIENT")])
def test_validate_only_checks_station_config(station_id: str, role: str) -> None:
    """防止正式入口在创建 GUI 前跳过配置校验。"""
    completed = subprocess.run(
        [sys.executable, "run.py", "--station", station_id, "--validate-only"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"station={station_id}" in completed.stdout
    assert f"role={role}" in completed.stdout


def test_qt_diagnostic_reports_versions_and_plugin_path() -> None:
    """防止 Qt 环境故障只能通过崩溃猜测原因。"""
    completed = subprocess.run(
        [sys.executable, "scripts/diagnose_qt.py"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Python:" in completed.stdout
    assert "PyQt5:" in completed.stdout
    assert "Qt:" in completed.stdout
    assert "Qt plugins:" in completed.stdout
    assert "Platform plugins directory exists: True" in completed.stdout
    assert "macOS cocoa plugin exists: True" in completed.stdout


def test_dual_validate_only_checks_both_station_configs() -> None:
    """双站入口必须在创建 GUI 和数据库之前完成交叉配置校验。"""
    completed = subprocess.run(
        [sys.executable, "run_dual.py", "--validate-only"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "station=A role=SERVER" in completed.stdout
    assert "station=B role=CLIENT" in completed.stdout
    assert "shared_endpoint=127.0.0.1:9500" in completed.stdout
