"""双站启动器必须固定先 A 后 B，并以本次 A 的就绪凭据为准。"""

import subprocess
from pathlib import Path

import scripts.launch_two_stations as launcher
from scripts.launch_two_stations import (
    build_station_commands,
    child_process_group_options,
    terminate_processes,
    wait_for_any_process,
    wait_for_server_ready,
)


def test_station_commands_use_separate_identity_and_data_directories() -> None:
    ready_file = Path("/tmp/tcc-ready/server.json")
    commands = build_station_commands(
        python=Path("/tmp/python"),
        project_root=Path("/tmp/tcc"),
        data_root=Path("/tmp/tcc-data"),
        config_dir=Path("/tmp/tcc-config"),
        server_ready_file=ready_file,
    )

    assert commands[0][-8:] == [
        "--station", "A", "--config", "/tmp/tcc-config",
        "--data-dir", "/tmp/tcc-data/A", "--server-ready-file", str(ready_file),
    ]
    assert commands[1][-6:] == [
        "--station", "B", "--config", "/tmp/tcc-config",
        "--data-dir", "/tmp/tcc-data/B",
    ]


def test_wait_for_server_ready_requires_file_from_live_a(tmp_path: Path) -> None:
    class FakeProcess:
        def __init__(self, returncodes):  # type: ignore[no-untyped-def]
            self.returncodes = list(returncodes)

        def poll(self):  # type: ignore[no-untyped-def]
            if len(self.returncodes) > 1:
                return self.returncodes.pop(0)
            return self.returncodes[0]

    ready_file = tmp_path / "a-ready.json"
    exited = FakeProcess([None, 3])
    assert not wait_for_server_ready(
        exited, ready_file, timeout_s=0.1, poll_interval_s=0.001
    )

    ready_file.write_text("{}", encoding="utf-8")
    live = FakeProcess([None])
    assert wait_for_server_ready(
        live, ready_file, timeout_s=0.1, poll_interval_s=0.001
    )


def test_child_process_group_is_isolated_on_current_platform() -> None:
    options = child_process_group_options()
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        assert options == {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        assert options == {"start_new_session": True}


def test_main_does_not_start_b_without_a_ready_credential(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    created = []

    class FakeProcess:
        def __init__(self, command, **_kwargs):  # type: ignore[no-untyped-def]
            self.command = command
            self.terminated = False
            created.append(self)

        def poll(self):  # type: ignore[no-untyped-def]
            return None if not self.terminated else 0

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout):  # type: ignore[no-untyped-def]
            return 0

        def kill(self) -> None:
            self.terminated = True

    monkeypatch.setattr(launcher.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(launcher, "wait_for_server_ready", lambda *_args, **_kwargs: False)

    result = launcher.main(["--data-root", str(tmp_path)])

    assert result == 2
    assert len(created) == 1
    assert "A" in created[0].command
    assert created[0].terminated


def test_terminate_processes_only_terminates_live_children() -> None:
    class FakeProcess:
        def __init__(self, returncode):  # type: ignore[no-untyped-def]
            self.returncode = returncode
            self.terminated = False
            self.waited = False

        def poll(self):  # type: ignore[no-untyped-def]
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout):  # type: ignore[no-untyped-def]
            self.waited = True
            self.returncode = 0

        def kill(self) -> None:
            self.returncode = -9

    live = FakeProcess(None)
    exited = FakeProcess(0)

    terminate_processes([live, exited], timeout_s=0.1)

    assert live.terminated and live.waited
    assert not exited.terminated


def test_wait_returns_when_either_station_exits() -> None:
    class FakeProcess:
        def __init__(self, values):  # type: ignore[no-untyped-def]
            self.values = list(values)

        def poll(self):  # type: ignore[no-untyped-def]
            if len(self.values) > 1:
                return self.values.pop(0)
            return self.values[0]

    station_a = FakeProcess([None, None])
    station_b = FakeProcess([None, 7])

    assert wait_for_any_process(
        [station_a, station_b], poll_interval_s=0.001
    ) == 7
