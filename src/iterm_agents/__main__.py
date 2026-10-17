"""Entry point for iterm-agents."""

from __future__ import annotations

import argparse
import fcntl
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import iterm2
import iterm2.connection

from iterm_agents import __version__
from iterm_agents.autolaunch import install_autolaunch
from iterm_agents.recovery import reload_panel, write_runtime
from iterm_agents.server import DEFAULT_PORT, AgentMonitorServer


def _acquire_single_instance(lock_path: Path) -> bool:
    """Hold an advisory lock for the process lifetime; False if already held."""
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    return True


async def _run(connection: iterm2.connection.Connection, port: int) -> None:
    """Build and start the monitor inside the iterm2 connection's event loop."""
    server = AgentMonitorServer(connection, port=port)
    await server.start()
    write_runtime(server.url)
    print(f"iterm-agents: running ({server.url})")
    print("iterm-agents: Ctrl+C to stop")


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry: parse flags, hold a single-instance lock, run the monitor."""
    parser = argparse.ArgumentParser(
        prog="iterm-agents",
        description=(
            "iTerm2 agent monitor for Claude Code, Codex, Cursor Agent, Devin, and Kimi Code"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port for the local web server (default: auto-select)",
    )
    parser.add_argument(
        "--install-autolaunch",
        action="store_true",
        help="Install an iTerm2 AutoLaunch wrapper and exit",
    )
    parser.add_argument(
        "--reload-panel",
        action="store_true",
        help="Rebuild blank or stuck Agents panels without restarting the monitor",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing AutoLaunch wrapper when used with --install-autolaunch",
    )
    args = parser.parse_args(argv)

    if args.force and not args.install_autolaunch:
        parser.error("--force can only be used with --install-autolaunch")
    if args.reload_panel and args.install_autolaunch:
        parser.error("--reload-panel cannot be combined with --install-autolaunch")

    if args.reload_panel:
        # Recovery must work while the running monitor holds the instance lock.
        iterm2.run_until_complete(reload_panel)  # type: ignore[attr-defined]
        return

    if args.install_autolaunch:
        result = install_autolaunch(force=args.force)
        action = "installed" if result.changed else "already installed"
        print(f"iterm-agents: AutoLaunch wrapper {action} at {result.path} (mode: {result.mode})")
        return

    lock_path = Path(tempfile.gettempdir()) / "iterm-agents.lock"
    if not _acquire_single_instance(lock_path):
        print("iterm-agents: already running")
        return

    try:
        iterm2.run_forever(lambda conn: _run(conn, args.port))  # type: ignore[attr-defined]
    except KeyboardInterrupt:
        print("\niterm-agents: stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
