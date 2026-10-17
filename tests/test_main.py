from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from iterm_agents import __version__
from iterm_agents.__main__ import _acquire_single_instance, main
from iterm_agents.autolaunch import AutoLaunchInstallResult
from iterm_agents.server import DEFAULT_PORT


class TestMain:
    def test_reload_panel_bypasses_the_held_monitor_lock(self) -> None:
        with (
            patch("iterm_agents.__main__.iterm2.run_until_complete") as runner,
            patch("iterm_agents.__main__._acquire_single_instance") as lock,
        ):
            main(["--reload-panel"])
        runner.assert_called_once()
        lock.assert_not_called()

    def test_version_flag_prints_package_version(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])

        assert excinfo.value.code == 0
        captured = capsys.readouterr()
        assert captured.out == f"iterm-agents {__version__}\n"

    def test_default_port_is_forwarded_to_runner(self) -> None:
        with (
            patch("iterm_agents.__main__._run", new_callable=AsyncMock) as mock_run,
            patch("iterm_agents.__main__.iterm2.run_forever") as mock_run_forever,
            patch("iterm_agents.__main__._acquire_single_instance", return_value=True),
        ):
            main([])
            callback = mock_run_forever.call_args.args[0]
            asyncio.run(callback("connection"))

        mock_run.assert_awaited_once_with("connection", DEFAULT_PORT)

    def test_port_argument_is_forwarded_to_runner(self) -> None:
        with (
            patch("iterm_agents.__main__._run", new_callable=AsyncMock) as mock_run,
            patch("iterm_agents.__main__.iterm2.run_forever") as mock_run_forever,
            patch("iterm_agents.__main__._acquire_single_instance", return_value=True),
        ):
            main(["--port", "50123"])
            callback = mock_run_forever.call_args.args[0]
            asyncio.run(callback("connection"))

        mock_run.assert_awaited_once_with("connection", 50123)

    def test_second_instance_exits_when_lock_is_held(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch("iterm_agents.__main__._acquire_single_instance", return_value=False),
            patch("iterm_agents.__main__.iterm2.run_forever") as mock_run_forever,
        ):
            main([])

        mock_run_forever.assert_not_called()
        assert "already running" in capsys.readouterr().out

    def test_single_instance_lock_is_exclusive(self, tmp_path: Path) -> None:
        lock = tmp_path / "iterm-agents.lock"
        assert _acquire_single_instance(lock)
        assert not _acquire_single_instance(lock)

    def test_install_autolaunch_flag_installs_wrapper_and_skips_runner(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        result = AutoLaunchInstallResult(
            path=Path("/tmp/iterm-agents.py"), changed=True, mode="binary"
        )
        with (
            patch("iterm_agents.__main__.install_autolaunch", return_value=result) as mock_install,
            patch("iterm_agents.__main__.iterm2.run_forever") as mock_run_forever,
        ):
            main(["--install-autolaunch"])

        mock_install.assert_called_once_with(force=False)
        mock_run_forever.assert_not_called()
        captured = capsys.readouterr()
        assert "AutoLaunch wrapper installed" in captured.out
        assert "mode: binary" in captured.out

    def test_force_requires_install_autolaunch(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["--force"])

        assert excinfo.value.code == 2
