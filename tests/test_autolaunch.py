from __future__ import annotations

from pathlib import Path

import pytest

from iterm_agents.autolaunch import (
    BINARY_AUTO_LAUNCH_SCRIPT,
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

        assert result == type(result)(path=script_path, changed=True, mode="binary")
        assert script_path.read_text() == BINARY_AUTO_LAUNCH_SCRIPT
        assert script_path.stat().st_mode & 0o777 == 0o755

    def test_is_idempotent_for_managed_script(self, tmp_path: Path) -> None:
        script_path = tmp_path / "AutoLaunch" / "iterm-agents.py"
        script_path.parent.mkdir(parents=True)
        script_path.write_text(BINARY_AUTO_LAUNCH_SCRIPT)

        result = install_autolaunch(script_path=script_path, launch_mode="binary")

        assert result.changed is False
        assert script_path.read_text() == BINARY_AUTO_LAUNCH_SCRIPT

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

        assert result.changed is True
        assert script_path.read_text() == BINARY_AUTO_LAUNCH_SCRIPT


class TestBuildAutoLaunchScript:
    def test_builds_project_wrapper(self, tmp_path: Path) -> None:
        script, mode = build_autolaunch_script(
            launch_mode="project",
            project_root=tmp_path,
        )

        assert mode == "project"
        assert str(tmp_path) in script
        assert ".venv/bin/iterm-agents" in script
