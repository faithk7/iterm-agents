"""Panel recovery independent of the sidebar's JavaScript and renderer."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import iterm2.connection
import iterm2.tool
from aiohttp import ClientSession, ClientTimeout

from iterm_agents.ui import AGENT_MONITOR_HTML


def runtime_path() -> Path:
    """Per-user discovery file; the HTTP port can change after a restart."""
    return Path.home() / ".cache/iterm-agents/runtime.json"


def write_runtime(url: str) -> None:
    path = runtime_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump({"url": url, "pid": os.getpid()}, stream)
    temporary.replace(path)


async def register_panel(
    connection: iterm2.connection.Connection, url: str, *, rebuild: bool = False
) -> None:
    """A changed registration URL asks iTerm to replace the native tool view."""
    version = hashlib.sha256(AGENT_MONITOR_HTML.encode()).hexdigest()[:12]
    panel_url = f"{url}?v={version}"
    if rebuild:
        panel_url += f"&recovery={time.monotonic_ns()}"
    await asyncio.wait_for(
        iterm2.tool.async_register_web_view_tool(
            connection,
            display_name="Agents",
            identifier="dev.iterm-agents.monitor",
            reveal_if_already_registered=True,
            url=panel_url,
        ),
        timeout=10,
    )


async def reload_panel(connection: iterm2.connection.Connection) -> None:
    """Find the live monitor and rebuild its views without restarting it."""
    try:
        state = json.loads(runtime_path().read_text())
        url = state["url"]
        parsed = urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or not parsed.port
            or parsed.path != "/"
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
        ):
            raise ValueError("Invalid monitor address")
        async with (
            ClientSession(timeout=ClientTimeout(total=3)) as client,
            client.get(url + "api/diagnostics") as response,
        ):
            response.raise_for_status()
            if (await response.json()).get("service") != "iterm-agents":
                raise ValueError("Monitor address is no longer active")
    except Exception as error:
        raise RuntimeError("Monitor unavailable. Start iterm-agents first.") from error
    await register_panel(connection, url, rebuild=True)
    print("iterm-agents: Agents panels rebuilt")
