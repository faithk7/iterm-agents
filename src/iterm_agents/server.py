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


def _focused_sessions_by_window(iterm2_app: iterm2.app.App) -> dict[str, str]:
    """Each window retains the active pane in its selected tab."""
    return {
        window.window_id: window.current_tab.active_session_id
        for window in iterm2_app.terminal_windows
        if window.current_tab is not None and window.current_tab.active_session_id
    }


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
        self._sse_window_ids: weakref.WeakKeyDictionary[web.StreamResponse, str] = (
            weakref.WeakKeyDictionary()
        )
        self._session_state = SessionStateTracker()
        self._cursor_footer: dict[str, tuple[str, float]] = {}
        self._scan_lock = asyncio.Lock()
        self._scan_rpc_gate = asyncio.Semaphore(self._SCAN_RPC_CONCURRENCY)
        self._scan_cache: tuple[float, list[dict[str, str | int]]] = (0.0, [])
        self._scan_refresh_task: asyncio.Task[None] | None = None
        self._window_ids: set[str] | None = None
        self._toolbelt_ready_windows: set[str] = set()
        self._git_cache: dict[str, tuple[float, GitInfo]] = {}
        self._keystroke_task: asyncio.Task[None] | None = None
        self._focus_task: asyncio.Task[None] | None = None
        self._focus_worker_task: asyncio.Task[None] | None = None
        self._pending_focus_id: str | None = None
        self._focused_by_window: dict[str, str] = {}
        self._session_window_ids: dict[str, str] = {}
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
        app.router.add_get("/api/panel-window", self._handle_panel_window)
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
                        window_id = await self._current_window_id()
                        if window_id:
                            await self._broadcast_sse("focus-search", window_id=window_id)
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
        window_id = self._session_window_ids.get(session_id)
        if window_id is None:
            return False
        self._focused_by_window[window_id] = session_id
        self._apply_focused_cache()
        return True

    async def _refresh_focused_rows(self) -> None:
        """Recompute focused ids from a fresh snapshot and push them out."""
        iterm2_app = await iterm2.app.async_get_app(self.connection)
        if iterm2_app is None:
            return
        self._window_ids = {w.window_id for w in iterm2_app.terminal_windows}
        self._focused_by_window = _focused_sessions_by_window(iterm2_app)
        self._session_window_ids = {
            session.session_id: window.window_id
            for window in iterm2_app.terminal_windows
            for tab in window.tabs
            for session in tab.sessions
        }
        self._apply_focused_cache()
        await self._broadcast_focus()

    def _apply_focused_cache(self) -> None:
        """Update the focused flags on the cached scan in place."""
        for row in self._scan_cache[1]:
            session_id = str(row["id"])
            window_id = self._session_window_ids.get(session_id)
            row["focused"] = self._focused_by_window.get(window_id or "") == session_id

    async def _broadcast_focus(self) -> None:
        """Send each panel only the focus state of its owning window."""
        for window_id in set(self._sse_window_ids.values()):
            session_id = self._focused_by_window.get(window_id)
            await self._broadcast_sse(
                "focus-changed",
                {"window_id": window_id, "focused": [session_id] if session_id else []},
                window_id=window_id,
            )

    async def _broadcast_sse(
        self, event: str, data: object = None, *, window_id: str | None = None
    ) -> None:
        """Send an event, optionally restricted to panels bound to one window."""
        payload = json.dumps({} if data is None else data)
        dead: list[web.StreamResponse] = []
        for client in list(self._sse_clients):
            if window_id is not None and self._sse_window_ids.get(client) != window_id:
                continue
            try:
                await client.write(f"event: {event}\ndata: {payload}\n\n".encode())
            except Exception:
                dead.append(client)
        for d in dead:
            self._sse_clients.discard(d)
            self._sse_window_ids.pop(d, None)

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """SSE endpoint for pushing events to the WebView."""
        response = web.StreamResponse()
        response.content_type = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        await response.prepare(request)
        self._sse_clients.add(response)
        self._sse_window_ids[response] = request.query.get("window", "")

        # Keep connection alive
        try:
            while True:
                await asyncio.sleep(30)
                await response.write(b": keepalive\n\n")
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self._sse_clients.discard(response)
            self._sse_window_ids.pop(response, None)
        return response

    async def _current_window_id(self) -> str:
        """Resolve the key window once the panel has seen its own window is key."""
        app = await iterm2.app.async_get_app(self.connection)
        if app is None:
            return ""
        self._window_ids = {w.window_id for w in app.terminal_windows}
        await app.async_refresh_focus()
        return app.current_window.window_id if app.current_window is not None else ""

    async def _handle_panel_window(self, request: web.Request) -> web.Response:
        """Binding handshake; the page keeps this id for its lifetime."""
        window_id = await self._current_window_id()
        if not window_id:
            raise web.HTTPServiceUnavailable(text="No current terminal window")
        print(f"iterm-agents: panel focus binding resolved to {window_id}", flush=True)
        return web.json_response({"window_id": window_id})

    async def _handle_index(self, request: web.Request) -> web.Response:
        """Serve the single-page panel UI."""
        return web.Response(text=AGENT_MONITOR_HTML, content_type="text/html")

    _SCAN_CACHE_TTL = 0.9
    _SCAN_RPC_CONCURRENCY = 4

    async def _handle_sessions(self, request: web.Request | None) -> web.Response:
        """Serve the latest scan; concurrent or rapid polls share one scan.

        Clicking a session row refetches immediately, so without this cache a
        burst of clicks runs a full iTerm/git/screen scan per click and the
        RPC pipe backs up. The cache holds the raw scan; SessionStateTracker
        runs per request on copies so acknowledged flags clear correctly.
        """
        # A newly opened panel can display the last complete snapshot without
        # joining a slow scan or waiting for new-window Toolbelt setup.
        if request is not None and request.query.get("cached") == "1" and self._scan_cache[0]:
            self._refresh_sessions_in_background()
            return self._sessions_response(request)

        async with self._scan_lock:
            timestamp, raw = self._scan_cache
            fresh = False
            if timestamp == 0.0 or time.monotonic() - timestamp > self._SCAN_CACHE_TTL:
                try:
                    raw = await self._scan_sessions()
                except Exception as error:
                    self._session_state.invalidate_observations()
                    if timestamp == 0.0:
                        raise web.HTTPServiceUnavailable(text="Session scan unavailable") from error
                    # Serve the previous display state; retry on the next poll.
                else:
                    timestamp = time.monotonic()
                    self._scan_cache = (timestamp, raw)
                    fresh = True
            response = self._sessions_response(request, fresh=fresh)
            if fresh:
                self._spawn_detached(self._broadcast_sse("sessions-changed"))
            return response

    def _refresh_sessions_in_background(self) -> None:
        """At most one refresh; callers keep reading the completed snapshot."""
        if time.monotonic() - self._scan_cache[0] <= self._SCAN_CACHE_TTL:
            return
        if self._scan_lock.locked():
            return
        if self._scan_refresh_task is not None and not self._scan_refresh_task.done():
            return
        self._scan_refresh_task = asyncio.create_task(self._refresh_sessions())
        self._detached_tasks.add(self._scan_refresh_task)
        self._scan_refresh_task.add_done_callback(self._detached_tasks.discard)

    async def _refresh_sessions(self) -> None:
        await self._handle_sessions(None)

    def _sessions_response(
        self, request: web.Request | None, *, fresh: bool = False
    ) -> web.Response:
        """Decorate a completed snapshot without advancing cached observations."""
        timestamp, raw = self._scan_cache
        sessions = self._session_state.apply(
            [dict(s) for s in raw], fresh=fresh, observed_at=timestamp
        )
        window_id = request.query.get("window", "") if request is not None else ""
        focused_id = self._focused_by_window.get(window_id)
        for row in sessions:
            row["focused"] = bool(window_id and row["id"] == focused_id)
        # Cached rows can predate a new window. Their absence is not evidence
        # that its confirmed binding is invalid; use the native window snapshot.
        owner = "unknown"
        if window_id and self._window_ids is not None:
            owner = "present" if window_id in self._window_ids else "missing"
        return web.json_response(
            sessions, headers={"X-Agents-Window": owner, "Cache-Control": "no-store"}
        )

    async def _scan_sessions(self) -> list[dict[str, str | int]]:
        """Snapshot every session: variables, agent state, git, screen hints."""
        iterm2_app = await iterm2.app.async_get_app(self.connection)
        if iterm2_app is None:
            raise RuntimeError("iterm-agents: session scan unavailable")

        # A window opened after startup hides its toolbelt; open it once.
        # A window the user hides by hand stays marked and is not reopened.
        window_ids = {w.window_id for w in iterm2_app.terminal_windows}
        self._window_ids = window_ids
        self._toolbelt_ready_windows.intersection_update(window_ids)
        new_window_ids = window_ids - self._toolbelt_ready_windows
        if new_window_ids:
            self._toolbelt_ready_windows.update(
                await self._ensure_toolbelts_visible(new_window_ids)
            )

        # Collect session PIDs for agent-session mapping. Fetching pid and
        # path per session serially costs two RPC round trips per session. The
        # gather is bounded by _scan_rpc_gate so a focus request can enter the
        # shared iTerm connection between small batches. The id map then lets
        # focus clicks and focus-change updates skip a full app snapshot.
        all_sessions = [
            session
            for window in iterm2_app.terminal_windows
            for tab in window.tabs
            for session in tab.sessions
        ]
        self._sessions_by_id = {s.session_id: s for s in all_sessions}
        self._session_window_ids = {
            session.session_id: window.window_id
            for window in iterm2_app.terminal_windows
            for tab in window.tabs
            for session in tab.sessions
        }
        pids, paths = await asyncio.gather(
            asyncio.gather(*(self._scan_session_variable(s, "pid") for s in all_sessions)),
            asyncio.gather(*(self._scan_session_variable(s, "path") for s in all_sessions)),
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
        self._focused_by_window = _focused_sessions_by_window(iterm2_app)
        focused_ids = set(self._focused_by_window.values())

        # Resolve each directory once before rows share its cached Git info.
        git_paths = set(session_paths.values()) - {""}
        git_by_path = dict(
            zip(
                git_paths,
                await asyncio.gather(*(self._git_for(path) for path in git_paths)),
                strict=True,
            )
        )
        sessions_info = await asyncio.gather(
            *(
                self._session_row(
                    pid,
                    session,
                    session_paths[pid],
                    agent_by_session_pid.get(pid),
                    session.session_id in focused_ids,
                    git_by_path.get(session_paths[pid]),
                    self._session_window_ids.get(session.session_id, ""),
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

    async def _scan_session_variable(self, session: iterm2.session.Session, name: str) -> object:
        """Read scan metadata without flooding iTerm's focus RPC queue."""
        async with self._scan_rpc_gate:
            if name == "pid":
                # Failed reads are different from a valid session with no PID.
                return await session.async_get_variable(name)
            return await _session_variable(session, name)

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
        git: GitInfo | None,
        window_id: str = "",
    ) -> dict[str, str | int]:
        """Build one session's API row, upgrading idle agents via the screen."""
        agent_state = agent.state.value if agent else ""
        if agent is not None and agent.state in (AgentState.IDLE, AgentState.UNKNOWN):
            if agent.agent_type is AgentType.CURSOR:
                agent_state = await self._cursor_state_from_screen(session, agent_state)
            elif agent.agent_type in (AgentType.DEVIN, AgentType.CODEX, AgentType.KIMI):
                agent_state = await self._screen_hint_state(session, agent.agent_type, agent_state)

        return {
            "id": session.session_id,
            "window_id": window_id,
            "name": session.name or "",
            "path": path.replace(_HOME_DIR, "~") if path else "",
            "repo": git.repo if git else "",
            "branch": git.branch if git else "",
            "root_repo": git.root_repo.replace(_HOME_DIR, "~") if git else "",
            "agent_type": agent.agent_type.value if agent else "",
            "agent_pid": agent.pid if agent else 0,
            "agent_state": agent_state,
            "pid": pid,
            "focused": focused,
        }

    async def _handle_focus(self, request: web.Request) -> web.Response:
        """Queue a pane focus and clear its done mark without blocking the UI."""
        session_id = request.query.get("session", "")
        if not session_id:
            return web.Response(text="no session id", status=400)
        self._session_state.acknowledge(session_id)

        # iTerm serializes activation work internally. Letting every HTTP click
        # issue its own RPC makes fast cross-window clicks pile up and sometimes
        # complete out of order. One worker owns that RPC stream; while it is
        # busy, only the most recent requested destination matters.
        self._pending_focus_id = session_id
        if self._focus_worker_task is None or self._focus_worker_task.done():
            self._focus_worker_task = asyncio.create_task(self._drain_focus_requests())
        return web.Response(text="ok")

    async def _drain_focus_requests(self) -> None:
        """Activate the current target, coalescing queued clicks to the latest."""
        try:
            while self._pending_focus_id is not None:
                session_id = self._pending_focus_id
                self._pending_focus_id = None
                try:
                    await self._activate_session(session_id)
                except Exception:
                    # A pane can close between the click and activation. Keep
                    # draining so a newer click cannot be stranded behind it.
                    continue
        finally:
            self._focus_worker_task = None

    async def _activate_session(self, session_id: str) -> None:
        """Activate one session, using the cached object before a full lookup."""

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
                    self._spawn_detached(self._broadcast_focus())
                return

        iterm2_app = await iterm2.app.async_get_app(self.connection)
        if iterm2_app is None:
            return

        for window in iterm2_app.terminal_windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    if session.session_id == session_id:
                        await session.async_activate()
                        self._sessions_by_id[session_id] = session
                        self._session_window_ids[session_id] = window.window_id
                        if self._patch_focused_session(session_id):
                            self._spawn_detached(self._broadcast_focus())
                        return

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
        async with self._scan_rpc_gate:
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
        if text is None and agent_type is AgentType.CODEX:
            return AgentState.UNKNOWN.value
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
