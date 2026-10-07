"""Helpers for installing an iTerm2 AutoLaunch wrapper script."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AUTO_LAUNCH_DIR = Path.home() / "Library/Application Support/iTerm2/Scripts/AutoLaunch"
AUTO_LAUNCH_SCRIPT_NAME = "iterm-agents.py"

LaunchMode = Literal["auto", "binary", "project"]

BINARY_AUTO_LAUNCH_SCRIPT = """#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess


def _resolve_binary() -> str:
    binary = shutil.which("iterm-agents")
    if binary is not None:
        return binary

    for candidate in (
        "/opt/homebrew/bin/iterm-agents",
        "/usr/local/bin/iterm-agents",
        os.path.expanduser("~/.local/bin/iterm-agents"),
    ):
        if pathlib.Path(candidate).exists():
            return candidate

    raise SystemExit("iterm-agents not found. Install it or add it to PATH.")


subprocess.Popen([_resolve_binary()])
"""

PROJECT_AUTO_LAUNCH_TEMPLATE = """#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import shutil
import subprocess

PROJECT_ROOT = pathlib.Path({project_root!r})
PROJECT_BINARY = PROJECT_ROOT / ".venv/bin/iterm-agents"
PROJECT_PYTHON = PROJECT_ROOT / ".venv/bin/python"


def _command() -> list[str]:
    if PROJECT_BINARY.exists():
        return [str(PROJECT_BINARY)]
    if PROJECT_PYTHON.exists():
        return [str(PROJECT_PYTHON), "-m", "iterm_agents"]

    uv = shutil.which("uv")
    if uv is not None:
        return [uv, "--project", str(PROJECT_ROOT), "run", "iterm-agents"]

    raise SystemExit(
        "iterm-agents project environment not found. Run `uv sync` in the project or install uv."
    )


subprocess.Popen(_command(), cwd=PROJECT_ROOT)
"""


@dataclass(frozen=True)
class AutoLaunchInstallResult:
    path: Path
    changed: bool
    mode: Literal["binary", "project"]


def autolaunch_script_path(base_dir: Path | None = None) -> Path:
    root = base_dir if base_dir is not None else AUTO_LAUNCH_DIR
    return root / AUTO_LAUNCH_SCRIPT_NAME


def build_autolaunch_script(
    *,
    launch_mode: LaunchMode = "auto",
    project_root: Path | None = None,
) -> tuple[str, Literal["binary", "project"]]:
    if launch_mode == "binary":
        return BINARY_AUTO_LAUNCH_SCRIPT, "binary"

    resolved_project_root = project_root
    if launch_mode == "auto":
        resolved_project_root = _detect_project_root()

    if launch_mode == "project" or resolved_project_root is not None:
        if resolved_project_root is None:
            raise ValueError("project_root is required when launch_mode='project'")
        return (
            PROJECT_AUTO_LAUNCH_TEMPLATE.format(project_root=str(resolved_project_root)),
            "project",
        )

    return BINARY_AUTO_LAUNCH_SCRIPT, "binary"


def install_autolaunch(
    *,
    force: bool = False,
    script_path: Path | None = None,
    launch_mode: LaunchMode = "auto",
    project_root: Path | None = None,
) -> AutoLaunchInstallResult:
    path = script_path if script_path is not None else autolaunch_script_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    script, mode = build_autolaunch_script(
        launch_mode=launch_mode,
        project_root=project_root,
    )

    if path.exists():
        existing = path.read_text()
        if existing == script:
            path.chmod(0o755)
            return AutoLaunchInstallResult(path=path, changed=False, mode=mode)
        if not force:
            raise FileExistsError(
                f"{path} already exists and differs from the iterm-agents-managed wrapper. "
                "Re-run with --force to overwrite it."
            )

    path.write_text(script)
    path.chmod(0o755)
    return AutoLaunchInstallResult(path=path, changed=True, mode=mode)


def _detect_project_root() -> Path | None:
    module_path = Path(__file__).resolve()
    try:
        src_dir = module_path.parent.parent
        project_root = src_dir.parent
    except IndexError:
        return None

    expected_main = project_root / "src/iterm_agents/__main__.py"
    pyproject = project_root / "pyproject.toml"
    if src_dir.name != "src" or not expected_main.exists() or not pyproject.exists():
        return None

    return project_root
