"""Web server and iTerm2 integration for the agent monitor."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
import weakref

import iterm2
import iterm2.app
import iterm2.connection
import iterm2.keyboard
import iterm2.mainmenu
import iterm2.session
import iterm2.tool
from aiohttp import web

from iterm_agents.detector import (
    AgentInfo,
    AgentState,
    AgentType,
    cursor_activity_signature,
    cursor_turn_is_live,
    detect_agents,
    get_git_info,
    screen_shows_active_turn,
)
from iterm_agents.session_state import SessionStateTracker
from iterm_agents.ui import AGENT_MONITOR_HTML

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 0

_SHOW_TOOLBELT_ID = iterm2.mainmenu.MainMenu.Toolbelt.SHOW_TOOLBELT.value.identifier


def _resolve_bound_port(addresses: list[object]) -> int:
    ports = {
        address[1]
        for address in addresses
        if isinstance(address, tuple) and len(address) >= 2 and isinstance(address[1], int)
    }
    if not ports:
        raise RuntimeError("iterm_agents: failed to determine bound port")
    if len(ports) != 1:
        raise RuntimeError(f"iterm_agents: multiple bound ports detected: {sorted(ports)}")
    return ports.pop()


class AgentMonitorServer:
    """Manages the aiohttp server and iTerm2 Toolbelt integration."""

    def __init__(
        self,
        connection: iterm2.connection.Connection,
        port: int = DEFAULT_PORT,
        host: str = DEFAULT_HOST,
    ) -> None:
        self.connection = connection
        self.host = host
        self.port = port
        self._sse_clients: weakref.WeakSet[web.StreamResponse] = weakref.WeakSet()
        self._session_state = SessionStateTracker()
        self._cursor_footer: dict[str, tuple[str, float]] = {}
        self._scan_lock = asyncio.Lock()
        self._scan_cache: tuple[float, list[dict[str, str | int]]] = (0.0, [])
        self._toolbelt_ready_windows: set[str] = set()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/api/sessions", self._handle_sessions)
        app.router.add_get("/api/focus", self._handle_focus)
        app.router.add_get("/api/clear", self._handle_clear)
        app.router.add_get("/api/events", self._handle_sse)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        self.port = _resolve_bound_port(runner.addresses)

        await iterm2.tool.async_register_web_view_tool(
            self.connection,
            display_name="Agents",
            identifier="dev.iterm-agents.monitor",
            reveal_if_already_registered=True,
            url=self.url,
        )

        self._toolbelt_ready_windows.update(await self._ensure_toolbelts_visible(None))
        self._keystroke_task = asyncio.ensure_future(self._monitor_keystroke())

    async def _ensure_toolbelt_visible(self) -> None:
        """Show the Toolbelt in the key window if it's not already visible.

        The Show Toolbelt item is disabled while iTerm2 is in the background.
        Selecting it then raises MenuItemException and used to take the whole
        monitor down. A failed open leaves the registered Agents panel in place.
        """
        if _SHOW_TOOLBELT_ID is None:
            return
        try:
            state = await iterm2.mainmenu.MainMenu.async_get_menu_item_state(
                self.connection,
                _SHOW_TOOLBELT_ID,
            )
            if not state.checked:
                await iterm2.mainmenu.MainMenu.async_select_menu_item(
                    self.connection,
                    _SHOW_TOOLBELT_ID,
                )
        except iterm2.mainmenu.MenuItemException:
            return

    async def _ensure_toolbelts_visible(self, window_ids: set[str] | None) -> set[str]:
        """Show the Toolbelt in each window; returns ids confirmed showing it.

        Toolbelt visibility is per window and Show Toolbelt only toggles the
        key window's, so each other target is briefly made key first, then the
        original key window is restored. `None` means every window. While
        iTerm2 is in the background the item is disabled; bail before
        activating anything and let the caller retry unconfirmed ids later.
        """
        ensured: set[str] = set()
        if _SHOW_TOOLBELT_ID is None:
            return ensured
        try:
            iterm2_app = await iterm2.app.async_get_app(self.connection)
        except Exception:
            return ensured
        if iterm2_app is None:
            return ensured

        try:
            gate = await iterm2.mainmenu.MainMenu.async_get_menu_item_state(
                self.connection,
                _SHOW_TOOLBELT_ID,
            )
        except iterm2.mainmenu.MenuItemException:
            return ensured
        if not gate.enabled:
            return ensured

        key_id = (
            iterm2_app.current_window.window_id
            if iterm2_app.current_window is not None
            else None
        )
        targets = [
            w
            for w in iterm2_app.terminal_windows
            if window_ids is None or w.window_id in window_ids
        ]
        targets.sort(key=lambda w: w.window_id != key_id)
        activated_other = False
        try:
            for window in targets:
                try:
                    if window.window_id != key_id:
                        await window.async_activate()
                        activated_other = True
                        await iterm2_app.async_refresh_focus()
                        if iterm2_app.current_terminal_window_id != window.window_id:
                            # Another space, a hotkey window, or closed: the
                            # menu item would hit the wrong window.
                            continue
                    state = (
                        gate
                        if window.window_id == key_id
                        else await iterm2.mainmenu.MainMenu.async_get_menu_item_state(
                            self.connection,
                            _SHOW_TOOLBELT_ID,
                        )
                    )
                    if not state.checked:
                        await iterm2.mainmenu.MainMenu.async_select_menu_item(
                            self.connection,
                            _SHOW_TOOLBELT_ID,
                        )
                    ensured.add(window.window_id)
                except Exception:
                    continue
        finally:
            if activated_other and key_id is not None:
                key_window = iterm2_app.get_window_by_id(key_id)
                if key_window is not None:
                    with contextlib.suppress(Exception):
                        await key_window.async_activate()
        return ensured

    async def _monitor_keystroke(self) -> None:
        """Monitor for Cmd+Shift+M to send focus event to WebView via SSE."""
        pattern = iterm2.keyboard.KeystrokePattern()  # type: ignore[no-untyped-call]
        pattern.required_modifiers = [
            iterm2.keyboard.Modifier.COMMAND,
            iterm2.keyboard.Modifier.SHIFT,
        ]
        pattern.characters = ["m"]

        try:
            async with iterm2.keyboard.KeystrokeMonitor(self.connection) as monitor:
                while True:
                    keystroke = await monitor.async_get()
                    if (
                        keystroke.characters == "m"
                        and iterm2.keyboard.Modifier.COMMAND in keystroke.modifiers
                        and iterm2.keyboard.Modifier.SHIFT in keystroke.modifiers
                    ):
                        await self._ensure_toolbelt_visible()
                        await self._broadcast_sse("focus-search")
        except Exception as e:
            print(f"iterm-agents: keystroke monitor error: {e}")

    async def _broadcast_sse(self, event: str) -> None:
        """Send an SSE event to all connected WebView clients."""
        dead: list[web.StreamResponse] = []
        for client in self._sse_clients:
            try:
                await client.write(f"event: {event}\ndata: {{}}\n\n".encode())
            except Exception:
                dead.append(client)
        for d in dead:
            self._sse_clients.discard(d)

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """SSE endpoint for pushing events to the WebView."""
        response = web.StreamResponse()
        response.content_type = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        await response.prepare(request)
        self._sse_clients.add(response)

        # Keep connection alive
        try:
            while True:
                await asyncio.sleep(30)
                await response.write(b": keepalive\n\n")
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self._sse_clients.discard(response)
        return response

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=AGENT_MONITOR_HTML, content_type="text/html")

    _SCAN_CACHE_TTL = 0.9

    async def _handle_sessions(self, request: web.Request) -> web.Response:
        """Serve the latest scan; concurrent or rapid polls share one scan.

        Clicking a session row refetches immediately, so without this cache a
        burst of clicks runs a full iTerm/git/screen scan per click and the
        RPC pipe backs up. The cache holds the raw scan; SessionStateTracker
        runs per request on copies so acknowledged flags clear correctly.
        """
        async with self._scan_lock:
            timestamp, raw = self._scan_cache
            if time.monotonic() - timestamp > self._SCAN_CACHE_TTL:
                raw = await self._scan_sessions()
                self._scan_cache = (time.monotonic(), raw)
            sessions = self._session_state.apply([dict(s) for s in raw])
            return web.json_response(sessions)

    async def _scan_sessions(self) -> list[dict[str, str | int]]:
        iterm2_app = await iterm2.app.async_get_app(self.connection)
        if iterm2_app is None:
            return []

        # A window opened after startup hides its toolbelt; open it once.
        # A window the user hides by hand stays marked and is not reopened.
        window_ids = {w.window_id for w in iterm2_app.terminal_windows}
        self._toolbelt_ready_windows.intersection_update(window_ids)
        new_window_ids = window_ids - self._toolbelt_ready_windows
        if new_window_ids:
            self._toolbelt_ready_windows.update(
                await self._ensure_toolbelts_visible(new_window_ids)
            )

        # Collect session PIDs for agent-session mapping
        session_map: dict[int, iterm2.session.Session] = {}
        sessions_info: list[dict[str, str | int]] = []

        for window in iterm2_app.terminal_windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    pid: int | None = None
                    try:
                        pid = await session.async_get_variable("pid")
                    except Exception:
                        pid = None
                    if pid is not None:
                        session_map[pid] = session

        # Detect agents and map to sessions. Off the event loop: it spawns
        # `ps`/`pmset` subprocesses that would stall focus requests.
        session_pids = set(session_map.keys())
        agents = (
            await asyncio.to_thread(detect_agents, session_pids)
            if session_pids
            else []
        )
        agent_by_session_pid: dict[int, AgentInfo] = {}
        for detected in agents:
            if detected.session_pid is not None:
                agent_by_session_pid[detected.session_pid] = detected

        # Build response
        for pid, session in session_map.items():
            path = ""
            try:
                path = await session.async_get_variable("path") or ""
            except Exception:
                path = ""

            git = await asyncio.to_thread(get_git_info, path) if path else None
            agent: AgentInfo | None = agent_by_session_pid.get(pid)
            home = os.path.expanduser("~")
            agent_state = agent.state.value if agent else ""
            if agent is not None and agent.state is AgentState.IDLE:
                if agent.agent_type is AgentType.CURSOR:
                    agent_state = await self._cursor_state_from_screen(session, agent_state)
                elif agent.agent_type in (AgentType.DEVIN, AgentType.CODEX, AgentType.KIMI):
                    agent_state = await self._screen_hint_state(
                        session, agent.agent_type, agent_state
                    )

            sessions_info.append(
                {
                    "id": session.session_id,
                    "name": session.name or "",
                    "path": path.replace(home, "~") if path else "",
                    "repo": git.repo if git else "",
                    "branch": git.branch if git else "",
                    "root_repo": git.root_repo.replace(home, "~") if git else "",
                    "agent_type": agent.agent_type.value if agent else "",
                    "agent_state": agent_state,
                    "pid": pid,
                }
            )

        # Sort: running first, then completion-waiting, idle, then non-agents
        state_priority = {"running": 0, "awaiting_user": 1, "idle": 2}
        sessions_info.sort(
            key=lambda s: (
                state_priority.get(str(s["agent_state"]), 3),
                s["name"],
            )
        )

        return sessions_info

    async def _handle_focus(self, request: web.Request) -> web.Response:
        session_id = request.query.get("session", "")
        if not session_id:
            return web.Response(text="no session id", status=400)
        self._session_state.acknowledge(session_id)

        iterm2_app = await iterm2.app.async_get_app(self.connection)
        if iterm2_app is None:
            return web.Response(text="app not found", status=500)

        for window in iterm2_app.terminal_windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    if session.session_id == session_id:
                        await session.async_activate()
                        return web.Response(text="ok")

        return web.Response(text="not found", status=404)

    async def _handle_clear(self, request: web.Request) -> web.Response:
        """Mark every done agent as read without focusing any session."""
        self._session_state.acknowledge_all()
        return web.Response(text="ok")

    async def _screen_text(self, session: iterm2.session.Session) -> str | None:
        try:
            screen = await session.async_get_screen_contents()
            return "\n".join(
                screen.line(index).string for index in range(screen.number_of_lines)
            )
        except Exception:
            return None

    async def _screen_hint_state(
        self,
        session: iterm2.session.Session,
        agent_type: AgentType,
        agent_state: str,
    ) -> str:
        """Upgrade an idle session while its live-turn hint is on screen."""
        text = await self._screen_text(session)
        if text is not None and screen_shows_active_turn(agent_type, text):
            return AgentState.RUNNING.value
        return agent_state

    async def _cursor_state_from_screen(
        self, session: iterm2.session.Session, agent_state: str
    ) -> str:
        """Upgrade an idle Cursor session only while its footer is still moving."""
        text = await self._screen_text(session)
        if text is None:
            return agent_state
        signature = cursor_activity_signature(text)
        session_id = session.session_id
        now = time.monotonic()
        if signature is None:
            self._cursor_footer.pop(session_id, None)
            return agent_state
        previous = self._cursor_footer.get(session_id)
        if previous is None or previous[0] != signature:
            self._cursor_footer[session_id] = (signature, now)
            previous_signature = None
            age = 0.0
        else:
            previous_signature = previous[0]
            age = now - previous[1]
        if cursor_turn_is_live(signature, previous_signature, age):
            return AgentState.RUNNING.value
        return agent_state
