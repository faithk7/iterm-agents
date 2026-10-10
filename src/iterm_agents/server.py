"""Web server and iTerm2 integration for the agent monitor."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import weakref
from collections.abc import Coroutine
from typing import Any

import iterm2
import iterm2.app
import iterm2.connection
import iterm2.focus
import iterm2.keyboard
import iterm2.mainmenu
import iterm2.session
import iterm2.tool
from aiohttp import web

from iterm_agents.detector import (
    AgentInfo,
    AgentState,
    AgentType,
    GitInfo,
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
_HOME_DIR = os.path.expanduser("~")


def _resolve_bound_port(addresses: list[object]) -> int:
    """The single port the site bound to; rejects ambiguous runner state."""
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


async def _session_variable(session: iterm2.session.Session, name: str) -> object:
    """Fetch one session variable, or None when the read fails."""
    try:
        return await session.async_get_variable(name)
    except Exception:
        return None


def _focused_session_ids(iterm2_app: iterm2.app.App) -> set[str]:
    """The active session of the current window's current tab, if any."""
    window = iterm2_app.current_window
    tab = window.current_tab if window is not None else None
    session_id = tab.active_session_id if tab is not None else None
    return {session_id} if session_id else set()


class AgentMonitorServer:
    """Manages the aiohttp server and iTerm2 Toolbelt integration."""

    def __init__(
        self,
        connection: iterm2.connection.Connection,
        port: int = DEFAULT_PORT,
        host: str = DEFAULT_HOST,
    ) -> None:
        """Store config and scan state; nothing connects until start()."""
        self.connection = connection
        self.host = host
        self.port = port
        self._sse_clients: weakref.WeakSet[web.StreamResponse] = weakref.WeakSet()
        self._session_state = SessionStateTracker()
        self._cursor_footer: dict[str, tuple[str, float]] = {}
        self._scan_lock = asyncio.Lock()
        self._scan_cache: tuple[float, list[dict[str, str | int]]] = (0.0, [])
        self._toolbelt_ready_windows: set[str] = set()
        self._git_cache: dict[str, tuple[float, GitInfo]] = {}
        self._keystroke_task: asyncio.Task[None] | None = None
        self._focus_task: asyncio.Task[None] | None = None
        self._focused_ids: set[str] = set()
        self._sessions_by_id: dict[str, iterm2.session.Session] = {}
        self._detached_tasks: set[asyncio.Task[None]] = set()

    @property
    def url(self) -> str:
        """Base URL the panel WebView loads."""
        return f"http://{self.host}:{self.port}/"

    async def start(self) -> None:
        """Start HTTP, register the Agents tool, and open every toolbelt."""
        app = web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/api/sessions", self._handle_sessions)
        app.router.add_get("/api/focus", self._handle_focus)
        app.router.add_get("/api/clear", self._handle_clear)
        app.router.add_get("/api/label", self._handle_label)
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
        self._keystroke_task = asyncio.create_task(self._monitor_keystroke())
        self._focus_task = asyncio.create_task(self._monitor_focus_changes())

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
            iterm2_app.current_window.window_id if iterm2_app.current_window is not None else None
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

    async def _monitor_focus_changes(self) -> None:
        """Push focus-marker updates; RPC-heavy paths run detached so neither
        the monitor loop nor the pane-switch flow ever waits on them."""
        try:
            async with iterm2.focus.FocusMonitor(self.connection) as monitor:
                while True:
                    update = await monitor.async_get_next_update()
                    if update.active_session_changed:
                        if self._patch_focused_session(update.active_session_changed.session_id):
                            await self._broadcast_focus()
                        else:
                            self._spawn_detached(self._refresh_focused_rows())
                    elif update.selected_tab_changed or update.window_changed:
                        self._spawn_detached(self._refresh_focused_rows())
        except Exception as e:
            print(f"iterm-agents: focus monitor error: {e}")

    def _spawn_detached(self, coro: Coroutine[Any, Any, None]) -> None:
        """Run a coroutine detached, keeping a reference until it completes."""
        task = asyncio.create_task(coro)
        self._detached_tasks.add(task)
        task.add_done_callback(self._detached_tasks.discard)

    def _patch_focused_session(self, session_id: str) -> bool:
        """Move the marker to a newly active session without any RPC.

        Uses the session map from the last scan; returns False for a session
        the map does not know so the caller can rescan instead.
        """
        if session_id not in self._sessions_by_id:
            return False
        self._focused_ids = {session_id}
        self._apply_focused_cache()
        return True

    async def _refresh_focused_rows(self) -> None:
        """Recompute focused ids from a fresh snapshot and push them out."""
        iterm2_app = await iterm2.app.async_get_app(self.connection)
        if iterm2_app is None:
            return
        self._focused_ids = _focused_session_ids(iterm2_app)
        self._apply_focused_cache()
        await self._broadcast_focus()

    def _apply_focused_cache(self) -> None:
        """Update the focused flags on the cached scan in place."""
        for row in self._scan_cache[1]:
            row["focused"] = row["id"] in self._focused_ids

    async def _broadcast_focus(self) -> None:
        """Push the current focused-id set to every WebView."""
        await self._broadcast_sse("focus-changed", {"focused": sorted(self._focused_ids)})

    async def _broadcast_sse(self, event: str, data: object = None) -> None:
        """Send an SSE event to all connected WebView clients."""
        payload = json.dumps({} if data is None else data)
        dead: list[web.StreamResponse] = []
        for client in self._sse_clients:
            try:
                await client.write(f"event: {event}\ndata: {payload}\n\n".encode())
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
        """Serve the single-page panel UI."""
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
        """Snapshot every session: variables, agent state, git, screen hints."""
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

        # Collect session PIDs for agent-session mapping. Fetching pid and
        # path per session serially costs two RPC round trips per session;
        # gathering sends them all at once. The id map lets focus clicks and
        # focus-change updates skip a full app snapshot entirely.
        all_sessions = [
            session
            for window in iterm2_app.terminal_windows
            for tab in window.tabs
            for session in tab.sessions
        ]
        self._sessions_by_id = {s.session_id: s for s in all_sessions}
        pids, paths = await asyncio.gather(
            asyncio.gather(*(_session_variable(s, "pid") for s in all_sessions)),
            asyncio.gather(*(_session_variable(s, "path") for s in all_sessions)),
        )
        session_map: dict[int, iterm2.session.Session] = {}
        session_paths: dict[int, str] = {}
        for session, pid, path in zip(all_sessions, pids, paths, strict=True):
            if isinstance(pid, int):
                session_map[pid] = session
                session_paths[pid] = path if isinstance(path, str) else ""

        # Detect agents and map to sessions. Off the event loop: it spawns
        # `ps`/`pmset` subprocesses that would stall focus requests.
        session_pids = set(session_map.keys())
        agents = await asyncio.to_thread(detect_agents, session_pids) if session_pids else []
        agent_by_session_pid: dict[int, AgentInfo] = {}
        for detected in agents:
            if detected.session_pid is not None:
                agent_by_session_pid[detected.session_pid] = detected

        # Each window's current tab marks its active session so the UI can
        # flag the focused pane; these are cached properties, not RPCs.
        focused_ids = _focused_session_ids(iterm2_app)
        self._focused_ids = focused_ids

        sessions_info = await asyncio.gather(
            *(
                self._session_row(
                    pid,
                    session,
                    session_paths[pid],
                    agent_by_session_pid.get(pid),
                    session.session_id in focused_ids,
                )
                for pid, session in session_map.items()
            )
        )

        # Drop tracking state for sessions that closed and expired cache
        # entries; both dicts would otherwise grow for the process lifetime.
        live_session_ids = {session.session_id for session in session_map.values()}
        self._cursor_footer = {
            session_id: entry
            for session_id, entry in self._cursor_footer.items()
            if session_id in live_session_ids
        }
        now = time.monotonic()
        self._git_cache = {
            path: entry
            for path, entry in self._git_cache.items()
            if now - entry[0] < self._GIT_CACHE_TTL
        }

        # Rows keep pane order (window, tab, session) so a status change
        # never moves a card out from under the cursor.
        return sessions_info

    _GIT_CACHE_TTL = 5.0

    async def _git_for(self, path: str) -> GitInfo | None:
        """Repo info for a path, cached briefly; sessions rarely move."""
        now = time.monotonic()
        cached = self._git_cache.get(path)
        if cached is not None and now - cached[0] < self._GIT_CACHE_TTL:
            return cached[1]
        info = await asyncio.to_thread(get_git_info, path)
        self._git_cache[path] = (now, info)
        return info

    async def _session_row(
        self,
        pid: int,
        session: iterm2.session.Session,
        path: str,
        agent: AgentInfo | None,
        focused: bool,
    ) -> dict[str, str | int]:
        """Build one session's API row, upgrading idle agents via the screen."""
        git = await self._git_for(path) if path else None
        agent_state = agent.state.value if agent else ""
        if agent is not None and agent.state is AgentState.IDLE:
            if agent.agent_type is AgentType.CURSOR:
                agent_state = await self._cursor_state_from_screen(session, agent_state)
            elif agent.agent_type in (AgentType.DEVIN, AgentType.CODEX, AgentType.KIMI):
                agent_state = await self._screen_hint_state(session, agent.agent_type, agent_state)

        return {
            "id": session.session_id,
            "name": session.name or "",
            "path": path.replace(_HOME_DIR, "~") if path else "",
            "repo": git.repo if git else "",
            "branch": git.branch if git else "",
            "root_repo": git.root_repo.replace(_HOME_DIR, "~") if git else "",
            "agent_type": agent.agent_type.value if agent else "",
            "agent_state": agent_state,
            "pid": pid,
            "focused": focused,
        }

    async def _handle_focus(self, request: web.Request) -> web.Response:
        """Focus a session's pane; also clears its done mark."""
        session_id = request.query.get("session", "")
        if not session_id:
            return web.Response(text="no session id", status=400)
        self._session_state.acknowledge(session_id)

        # Fast path: the session object from the last scan activates in a
        # single RPC — a fresh app snapshot costs hundreds of ms.
        session = self._sessions_by_id.get(session_id)
        if session is not None:
            try:
                await session.async_activate()
            except Exception:
                pass  # closed between scan and click; fall through to lookup
            else:
                if self._patch_focused_session(session_id):
                    await self._broadcast_focus()
                return web.Response(text="ok")

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
        """Mark done agents as read without focusing; one session, or all when omitted."""
        session_id = request.query.get("session", "")
        if session_id:
            self._session_state.acknowledge(session_id)
        else:
            self._session_state.acknowledge_all()
        return web.Response(text="ok")

    async def _handle_label(self, request: web.Request) -> web.Response:
        """Set or clear a session's custom label."""
        session_id = request.query.get("session", "")
        if not session_id:
            return web.Response(text="no session id", status=400)
        self._session_state.set_label(session_id, request.query.get("label", ""))
        return web.Response(text="ok")

    async def _screen_text(self, session: iterm2.session.Session) -> str | None:
        """The session's visible screen as text, or None when the read fails."""
        try:
            screen = await session.async_get_screen_contents()
            return "\n".join(screen.line(index).string for index in range(screen.number_of_lines))
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
