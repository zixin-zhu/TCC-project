"""先确认本次 A 进程完成监听，再启动 B，并统一回收两个 GUI 进程。"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_station_commands(
    *,
    python: Path,
    project_root: Path,
    data_root: Path,
    config_dir: Path,
    server_ready_file: Path,
) -> tuple[list[str], list[str]]:
    base = [str(python), str(project_root / "run.py")]
    return (
        [
            *base,
            "--station", "A",
            "--config", str(config_dir),
            "--data-dir", str(data_root / "A"),
            "--server-ready-file", str(server_ready_file),
        ],
        [
            *base,
            "--station", "B",
            "--config", str(config_dir),
            "--data-dir", str(data_root / "B"),
        ],
    )


def wait_for_server_ready(
    process: subprocess.Popen[bytes],
    ready_file: Path,
    *,
    timeout_s: float = 8.0,
    poll_interval_s: float = 0.1,
) -> bool:
    """等待 A 自己发布监听凭据；A 提前退出时立即失败。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if ready_file.is_file():
            return True
        if process.poll() is not None:
            return False
        time.sleep(poll_interval_s)
    return False


def child_process_group_options() -> dict[str, object]:
    """隔离 Ctrl+C：POSIX 建新会话，Windows 建新进程组。"""
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_processes(
    processes: Sequence[subprocess.Popen[bytes]], *, timeout_s: float = 3.0
) -> None:
    live = [process for process in processes if process.poll() is None]
    for process in live:
        process.terminate()
    for process in live:
        try:
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout_s)


def wait_for_any_process(
    processes: Sequence[subprocess.Popen[bytes]], *, poll_interval_s: float = 0.2
) -> int:
    """任一窗口退出即返回，并由调用方 finally 回收其余窗口。"""
    while True:
        for process in processes:
            returncode = process.poll()
            if returncode is not None:
                return int(returncode)
        time.sleep(poll_interval_s)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动 CTCS-2 TCC A/B 双站界面")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="tcc-dual-launch-") as ready_dir:
        ready_file = Path(ready_dir) / "station-a-ready.json"
        commands = build_station_commands(
            python=args.python,
            project_root=PROJECT_ROOT,
            data_root=args.data_root,
            config_dir=args.config,
            server_ready_file=ready_file,
        )
        processes: list[subprocess.Popen[bytes]] = []
        process_options = child_process_group_options()
        try:
            station_a = subprocess.Popen(
                commands[0], cwd=PROJECT_ROOT, **process_options
            )
            processes.append(station_a)
            if not wait_for_server_ready(station_a, ready_file):
                print("A 站未发布本次进程的监听凭据，已取消启动 B 站")
                return 2
            processes.append(
                subprocess.Popen(commands[1], cwd=PROJECT_ROOT, **process_options)
            )
            return wait_for_any_process(processes)
        except KeyboardInterrupt:
            return 130
        finally:
            terminate_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
