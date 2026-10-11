"""Tests for native process snapshots and the ps fallback."""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from iterm_agents.models import ProcessInfo
from iterm_agents.processes import (
    _libproc_process_table,
    _parse_procargs,
    _ps_process_table,
    build_process_table,
)


class TestProcessTable:
    def test_procargs_keep_empty_args_and_drop_the_environment(self) -> None:
        raw = (3).to_bytes(
            4, sys.byteorder
        ) + b"/opt/node\0\0\0\0node\0\0index.js\0CURSOR=/cursor-agent/\0"
        assert _parse_procargs(raw) == "node  index.js"

    @pytest.mark.skipif(sys.platform != "darwin", reason="libproc is macOS-only")
    def test_libproc_matches_ps_for_session_processes(self) -> None:
        table = _libproc_process_table({os.getpid()})
        ps_command = subprocess.run(
            ["ps", "-ww", "-o", "command=", "-p", str(os.getpid())],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert table[os.getpid()] == ProcessInfo(
            pid=os.getpid(), ppid=os.getppid(), command=ps_command
        )

    def test_falls_back_to_ps_when_libproc_fails(self) -> None:
        with (
            patch("iterm_agents.processes._libproc_process_table", side_effect=OSError),
            patch("iterm_agents.processes.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            run.return_value.stdout = "PID PPID COMMAND\n 10 1 zsh\n"
            assert build_process_table({10}) == {10: ProcessInfo(10, 1, "zsh")}

    def test_failed_process_scan_is_not_an_empty_snapshot(self) -> None:
        with patch("iterm_agents.processes.subprocess.run") as run:
            run.return_value.returncode = 1
            with pytest.raises(RuntimeError, match="process"):
                _ps_process_table()

    def test_empty_process_output_is_a_failed_scan(self) -> None:
        with patch("iterm_agents.processes.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "PID PPID COMMAND\n"
            with pytest.raises(RuntimeError, match="no valid rows"):
                _ps_process_table()
