from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from iterm_agents.autolaunch import (
    autolaunch_script_path,
    build_autolaunch_script,
    install_autolaunch,
)


class TestAutoLaunchScriptPath:
    def test_uses_expected_filename(self, tmp_path: Path) -> None:
        assert autolaunch_script_path(tmp_path) == tmp_path / "iterm-agents.py"


class TestInstallAutoLaunch:
    def test_creates_wrapper_script(self, tmp_path: Path) -> None:
        script_path = tmp_path / "AutoLaunch" / "iterm-agents.py"

        result = install_autolaunch(script_path=script_path, launch_mode="binary")
        expected_script, _ = build_autolaunch_script(launch_mode="binary")

        assert result == type(result)(path=script_path, changed=True, mode="binary")
        assert script_path.read_text() == expected_script
        assert script_path.stat().st_mode & 0o777 == 0o755

    def test_is_idempotent_for_managed_script(self, tmp_path: Path) -> None:
        script_path = tmp_path / "AutoLaunch" / "iterm-agents.py"
        script_path.parent.mkdir(parents=True)
        expected_script, _ = build_autolaunch_script(launch_mode="binary")
        script_path.write_text(expected_script)

        result = install_autolaunch(script_path=script_path, launch_mode="binary")

        assert result.changed is False
        assert script_path.read_text() == expected_script

    def test_refuses_to_overwrite_unknown_script_without_force(self, tmp_path: Path) -> None:
        script_path = tmp_path / "AutoLaunch" / "iterm-agents.py"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("#!/usr/bin/env python3\nprint('custom')\n")

        with pytest.raises(FileExistsError, match="Re-run with --force"):
            install_autolaunch(script_path=script_path, launch_mode="binary")

    def test_overwrites_unknown_script_with_force(self, tmp_path: Path) -> None:
        script_path = tmp_path / "AutoLaunch" / "iterm-agents.py"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("#!/usr/bin/env python3\nprint('custom')\n")

        result = install_autolaunch(force=True, script_path=script_path, launch_mode="binary")
        expected_script, _ = build_autolaunch_script(launch_mode="binary")

        assert result.changed is True
        assert script_path.read_text() == expected_script


class TestBuildAutoLaunchScript:
    def test_pip_venv_wrapper_launches_without_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scripts_dir = tmp_path / "project with 'quotes'" / ".venv" / "bin"
        scripts_dir.mkdir(parents=True)
        binary = scripts_dir / "iterm-agents"
        binary.write_text("#!/bin/sh\n")
        monkeypatch.setattr("iterm_agents.autolaunch._detect_project_root", lambda: None)
        monkeypatch.setattr("sysconfig.get_path", lambda name: str(scripts_dir))
        which = Mock(return_value=None)
        popen = Mock()
        monkeypatch.setattr("shutil.which", which)
        monkeypatch.setattr("subprocess.Popen", popen)

        script, mode = build_autolaunch_script()
        exec(compile(script, "iterm-agents.py", "exec"), {})

        assert mode == "binary"
        popen.assert_called_once_with([str(binary)])
        which.assert_not_called()

    def test_binary_wrapper_falls_back_to_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sysconfig.get_path", lambda name: str(tmp_path / "missing"))
        monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/iterm-agents")
        popen = Mock()
        monkeypatch.setattr("subprocess.Popen", popen)

        script, _ = build_autolaunch_script(launch_mode="binary")
        exec(compile(script, "iterm-agents.py", "exec"), {})

        popen.assert_called_once_with(["/usr/local/bin/iterm-agents"])

    def test_builds_project_wrapper(self, tmp_path: Path) -> None:
        script, mode = build_autolaunch_script(
            launch_mode="project",
            project_root=tmp_path,
        )

        assert mode == "project"
        assert str(tmp_path) in script
        assert ".venv/bin/iterm-agents" in script
