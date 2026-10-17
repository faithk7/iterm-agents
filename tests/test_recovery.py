"""Failure recovery must stay outside the renderer and avoid reload loops."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from iterm_agents import recovery
from iterm_agents.server import AgentMonitorServer


async def test_reload_discovers_live_monitor_and_rebuilds_without_restart(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(recovery, "runtime_path", lambda: runtime)
    register = AsyncMock()
    monkeypatch.setattr(recovery, "register_panel", register)
    server = AgentMonitorServer(connection=None)
    server._session_state.set_label("session", "keep me")
    app = web.Application()
    app.router.add_get("/api/diagnostics", server._handle_diagnostics)
    async with TestServer(app) as site:
        recovery.write_runtime(str(site.make_url("/")))
        assert runtime.stat().st_mode & 0o777 == 0o600
        await recovery.reload_panel("connection")
        register.assert_awaited_once_with("connection", str(site.make_url("/")), rebuild=True)
        assert server._session_state._labels == {"session": "keep me"}


async def test_reload_rejects_stale_or_nonlocal_discovery(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(recovery, "runtime_path", lambda: runtime)
    register = AsyncMock()
    monkeypatch.setattr(recovery, "register_panel", register)
    for url in ("https://example.com/", "http://127.0.0.1:0/", "invalid"):
        runtime.write_text(json.dumps({"url": url}))
        with pytest.raises(RuntimeError, match="Start iterm-agents first"):
            await recovery.reload_panel("connection")
    register.assert_not_awaited()


def stalled_panel(server, *, visible=True, busy=False):
    client = web.WebSocketResponse()
    server._sse_clients.add(client)
    server._sse_window_ids[client] = "w1"
    server._panel_health[client] = {
        "seen": 900.0, "visible": visible, "busy": busy, "data_age_ms": 0,
    }
    return client


async def test_watchdog_rebuilds_confirmed_stalled_owner_with_cooldown(monkeypatch):
    server = AgentMonitorServer(connection=None)
    client = stalled_panel(server)
    server._current_window_id = AsyncMock(return_value="w1")
    monkeypatch.setattr(
        "iterm_agents.server.iterm2.mainmenu.MainMenu.async_get_menu_item_state",
        AsyncMock(return_value=SimpleNamespace(enabled=True, checked=True)),
    )
    register = AsyncMock()
    monkeypatch.setattr("iterm_agents.server.register_panel", register)
    await server._check_panel_health(1000.0, 985.0)
    register.assert_not_awaited()
    await server._check_panel_health(1015.0, 1000.0)
    register.assert_awaited_once_with(None, server.url, rebuild=True)
    await server._check_panel_health(1030.0, 1015.0)
    assert register.await_count == 1
    assert server._panel_recoveries == 1
    assert client in server._sse_clients


@pytest.mark.parametrize(
    "reason", ["hidden", "busy", "background", "sleep", "healthy", "unbound", "toolbelt-hidden"]
)
async def test_watchdog_leaves_normal_suspension_and_active_work_alone(monkeypatch, reason):
    server = AgentMonitorServer(connection=None)
    client = stalled_panel(server, visible=reason != "hidden", busy=reason == "busy")
    server._current_window_id = AsyncMock(return_value="w2" if reason == "background" else "w1")
    monkeypatch.setattr(
        "iterm_agents.server.iterm2.mainmenu.MainMenu.async_get_menu_item_state",
        AsyncMock(return_value=SimpleNamespace(enabled=True, checked=reason != "toolbelt-hidden")),
    )
    if reason == "healthy":
        server._panel_health[client]["seen"] = 990.0
    if reason == "unbound":
        server._sse_window_ids[client] = ""
    register = AsyncMock()
    monkeypatch.setattr("iterm_agents.server.register_panel", register)
    await server._check_panel_health(1000.0, 800.0 if reason == "sleep" else 985.0)
    register.assert_not_awaited()
    if reason == "sleep":
        assert server._panel_health[client]["seen"] == 1000.0


async def test_health_acknowledgement_tracks_js_without_terminal_content():
    server = AgentMonitorServer(connection=None)
    app = web.Application()
    app.router.add_get("/api/ws", server._handle_ws)
    app.router.add_get("/api/diagnostics", server._handle_diagnostics)
    async with TestServer(app) as site, ClientSession() as http:
        socket = await http.ws_connect(site.make_url("/api/ws"))
        await socket.send_json({"event": "panel-health", "visible": True, "data_age_ms": 42})
        # Same WebSocket response after processing the preceding ack establishes ordering.
        await socket.ping()
        for _ in range(20):
            if any(h["visible"] for h in server._panel_health.values()):
                break
            await asyncio.sleep(0)
        async with http.get(site.make_url("/api/diagnostics")) as response:
            data = await response.json()
        assert len(data["panels"]) == 1
        assert data["panels"][0]["visible"] is True
        assert data["panels"][0]["data_age_ms"] == 42
        assert set(data["panels"][0]) == {"visible", "data_age_ms", "js_age_seconds"}
        await socket.close()


async def test_timed_out_git_read_is_shared_instead_of_spawning_more_threads(monkeypatch):
    server = AgentMonitorServer(connection=None)
    blocked = asyncio.Event()
    calls = 0

    async def fake_thread(function, path):
        nonlocal calls
        calls += 1
        await blocked.wait()
        return SimpleNamespace(repo="repo")

    monkeypatch.setattr("iterm_agents.server.asyncio.to_thread", fake_thread)
    for _ in range(3):
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(server._git_for("/blocked"), 0.01)
    assert calls == 1
    blocked.set()
    assert (await server._git_for("/blocked")).repo == "repo"
    assert server._git_tasks == {}
