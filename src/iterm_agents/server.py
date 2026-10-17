"""Web server and iTerm2 integration for the agent monitor."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import weakref
from collections.abc import Callable, Coroutine
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

from iterm_agents.detector import detect_agents
from iterm_agents.git_info import get_git_info
from iterm_agents.models import AgentInfo, AgentState, AgentType, GitInfo, SessionRow
from iterm_agents.recovery import register_panel
from iterm_agents.screen_signals import (
    cursor_activity_signature,
    cursor_turn_is_live,
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


class AgentMonitorServer:
    """Coordinate panel requests, session scans, and iTerm2 focus events.

    Shared state belongs to the iTerm2 event loop. Blocking process and Git
    reads run in worker threads and return values without mutating it.
    Scans are serialized, but focus events can patch the layout while a
    scan awaits RPCs; the focus epoch prevents older snapshots winning.
    """

    _SCAN_CACHE_TTL = 0.9
    _SCAN_RPC_CONCURRENCY = 4
    _GIT_CACHE_TTL = 5.0
    _SCAN_TIMEOUT = 6.0
    _MONITOR_RETRY_DELAY = 1.0
    _STALE_AFTER = 15.0
    _HEALTH_INTERVAL = 15.0
    _PANEL_TIMEOUT = 60.0
    _RECOVERY_COOLDOWN = 300.0

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
        # SSE and WebSocket panels share routing and window ownership.
        self._sse_clients: weakref.WeakSet[web.StreamResponse] = weakref.WeakSet()
        self._sse_window_ids: weakref.WeakKeyDictionary[web.StreamResponse, str] = (
            weakref.WeakKeyDictionary()
        )
        self._sse_focus_ids: weakref.WeakKeyDictionary[web.StreamResponse, str] = (
            weakref.WeakKeyDictionary()
        )
        # Cached rows contain observations; completion and labels are added
        # to response copies so acknowledgements also affect cached polls.
        self._session_state = SessionStateTracker()
        self._cursor_footer: dict[str, tuple[str, float]] = {}
        self._scan_lock = asyncio.Lock()
        self._scan_rpc_gate = asyncio.Semaphore(self._SCAN_RPC_CONCURRENCY)
        self._scan_cache: tuple[float, list[SessionRow]] = (0.0, [])
        self._scan_refresh_task: asyncio.Task[None] | None = None
        # None means the window layout has not yet been observed.
        self._window_ids: set[str] | None = None
        self._toolbelt_ready_windows: set[str] = set()
        self._git_cache: dict[str, tuple[float, GitInfo]] = {}
        self._keystroke_task: asyncio.Task[None] | None = None
        self._focus_task: asyncio.Task[None] | None = None
        self._focus_worker_task: asyncio.Task[None] | None = None
        self._focus_refresh_task: asyncio.Task[None] | None = None
        self._focus_refresh_pending = False
        self._focus_epoch = 0
        self._pending_focus_id: str | None = None
        # Remember selected tabs and panes even in inactive windows.
        self._iterm_app: iterm2.app.App | None = None
        self._focused_by_window: dict[str, str] = {}
        self._active_sessions_by_tab: dict[str, str] = {}
        self._selected_tabs_by_window: dict[str, str] = {}
        self._tab_window_ids: dict[str, str] = {}
        self._session_tab_ids: dict[str, str] = {}
        self._session_window_ids: dict[str, str] = {}
        self._sessions_by_id: dict[str, iterm2.session.Session] = {}
        self._detached_tasks: set[asyncio.Task[None]] = set()
        self._scan_error: str | None = None
        self._scan_started_at: float | None = None
        self._monitor_states: dict[str, str] = {}
        self._health_task: asyncio.Task[None] | None = None
        self._panel_health: weakref.WeakKeyDictionary[web.StreamResponse, dict[str, Any]] = (
            weakref.WeakKeyDictionary()
        )
        self._last_panel_recovery = -float("inf")
        self._panel_recoveries = 0
        self._panel_recovery_candidate: tuple[str, float] | None = None
        self._runner: web.AppRunner | None = None
        self._git_tasks: dict[str, asyncio.Task[GitInfo]] = {}

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
        app.router.add_get("/api/ws", self._handle_ws)
        app.router.add_get("/api/diagnostics", self._handle_diagnostics)

        runner = web.AppRunner(app)
        self._runner = runner
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        self.port = _resolve_bound_port(runner.addresses)

        await register_panel(self.connection, self.url)

        self._toolbelt_ready_windows.update(await self._ensure_toolbelts_visible(None))
        self._keystroke_task = asyncio.create_task(
            self._supervise_monitor("keyboard", self._monitor_keystroke)
        )
        self._focus_task = asyncio.create_task(
            self._supervise_monitor("focus", self._monitor_focus_changes)
        )
        self._health_task = asyncio.create_task(
            self._supervise_monitor("panels", self._monitor_panel_health)
        )

    async def stop(self) -> None:
        """Cancel workers and close clients before releasing the listening port."""
        tasks = set(self._detached_tasks)
        # A timed-out scan must not launch another thread for a Git read that
        # is still blocked on disk. Keep these jobs shared until completion.
        for git_task in self._git_tasks.values():
            git_task.cancel()
        await asyncio.gather(*self._git_tasks.values(), return_exceptions=True)
        tasks.update(
            task
            for task in (
                self._keystroke_task,
                self._focus_task,
                self._health_task,
                self._focus_worker_task,
                self._focus_refresh_task,
                self._scan_refresh_task,
            )
            if task is not None
        )
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for client in list(self._sse_clients):
            if isinstance(client, web.WebSocketResponse):
                await client.close()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _supervise_monitor(
        self, name: str, monitor: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Transient monitor failures must not silently disable a feature."""
        delay = self._MONITOR_RETRY_DELAY
        while True:
            self._monitor_states[name] = "running"
            started = time.monotonic()
            try:
                await monitor()
            except asyncio.CancelledError:
                self._monitor_states[name] = "stopped"
                raise
            except Exception as error:
                print(f"iterm-agents: {name} monitor restarting ({type(error).__name__})")
            self._monitor_states[name] = "retrying"
            if time.monotonic() - started > 60:
                delay = self._MONITOR_RETRY_DELAY
            await asyncio.sleep(delay)
            delay = min(30, delay * 2)

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

    async def _ensure_toolbelts_visible(
        self, window_ids: set[str] | None, *, activate_windows: bool = True
    ) -> set[str]:
        """Show the Toolbelt in each window; returns ids confirmed showing it.

        Toolbelt visibility is per window and Show Toolbelt only toggles the
        key window's, so each other target is briefly made key first, then the
        original key window is restored. `None` means every window. While
        iTerm2 is in the background the item is disabled; bail before
        activating anything and let the caller retry unconfirmed ids later.
        Background scans use activate_windows=False and wait for the user
        to activate a new window instead of stealing and restoring focus.
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
        self._iterm_app = iterm2_app

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
            if (window_ids is None or w.window_id in window_ids)
            and (activate_windows or w.window_id == key_id)
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
                            self._focus_epoch += 1
                            self._queue_focus_refresh()
                    elif update.selected_tab_changed:
                        if self._patch_selected_tab(update.selected_tab_changed.tab_id):
                            await self._broadcast_focus()
                        else:
                            self._focus_epoch += 1
                            self._queue_focus_refresh()
                    elif update.window_changed:
                        # Switching key windows does not change either one's
                        # selected tab or pane. Keep their markers untouched.
                        window_id = update.window_changed.window_id
                        if self._window_ids is None or window_id not in self._window_ids:
                            self._queue_focus_refresh()
        except Exception as e:
            print(f"iterm-agents: focus monitor error: {e}")

    def _queue_focus_refresh(self) -> None:
        """One snapshot worker, with one trailing refresh for newer events."""
        self._focus_refresh_pending = True
        if self._focus_refresh_task is None or self._focus_refresh_task.done():
            self._focus_refresh_task = asyncio.create_task(self._drain_focus_refreshes())
            self._detached_tasks.add(self._focus_refresh_task)
            self._focus_refresh_task.add_done_callback(self._detached_tasks.discard)

    async def _drain_focus_refreshes(self) -> None:
        try:
            while self._focus_refresh_pending:
                self._focus_refresh_pending = False
                await self._refresh_focused_rows()
        except Exception as error:
            # A disconnected API or closing window must not stop the focus
            # monitor; another event can retry once iTerm becomes available.
            print(f"iterm-agents: focus refresh error: {error}")
        finally:
            self._focus_refresh_task = None

    def _spawn_detached(self, coro: Coroutine[Any, Any, None]) -> None:
        """Run a coroutine detached, keeping a reference until it completes."""
        task = asyncio.create_task(coro)
        self._detached_tasks.add(task)
        task.add_done_callback(self._detached_done)

    def _detached_done(self, task: asyncio.Task[None]) -> None:
        self._detached_tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            print(f"iterm-agents: background task failed ({type(error).__name__})")

    def _patch_focused_session(self, session_id: str, *, select_tab: bool = False) -> bool:
        """Move the marker to a newly active session without any RPC.

        Uses the session map from the last scan; returns False for a session
        the map does not know so the caller can rescan instead.
        """
        if session_id not in self._sessions_by_id:
            return False
        window_id = self._session_window_ids.get(session_id)
        if window_id is None:
            return False
        self._focus_epoch += 1
        tab_id = self._session_tab_ids.get(session_id)
        if tab_id is not None:
            self._active_sessions_by_tab[tab_id] = session_id
            if select_tab:
                self._selected_tabs_by_window[window_id] = tab_id
            if self._selected_tabs_by_window.get(window_id) != tab_id:
                # A hidden tab can change its active pane without changing
                # the window's visible pane. Remember it for the next switch.
                return True
        self._focused_by_window[window_id] = session_id
        self._apply_focused_cache()
        return True

    def _patch_selected_tab(self, tab_id: str) -> bool:
        """Select a known tab using its remembered pane, with no iTerm RPC."""
        window_id = self._tab_window_ids.get(tab_id)
        if window_id is None:
            return False
        self._focus_epoch += 1
        self._selected_tabs_by_window[window_id] = tab_id
        session_id = self._active_sessions_by_tab.get(tab_id, "")
        if session_id:
            self._focused_by_window[window_id] = session_id
        else:
            self._focused_by_window.pop(window_id, None)
        self._apply_focused_cache()
        return True

    def _index_layout(self, app: iterm2.app.App, *, preserve_focus: bool = False) -> None:
        """Keep topology and every tab's focus warm, including inactive windows."""
        self._iterm_app = app
        self._window_ids = {w.window_id for w in app.terminal_windows}
        tabs = [(window.window_id, tab) for window in app.terminal_windows for tab in window.tabs]
        self._tab_window_ids = {tab.tab_id: window_id for window_id, tab in tabs}
        self._session_tab_ids = {
            session.session_id: tab.tab_id for _, tab in tabs for session in tab.sessions
        }
        self._session_window_ids = {
            session.session_id: window_id for window_id, tab in tabs for session in tab.sessions
        }
        self._sessions_by_id = {
            session.session_id: session for _, tab in tabs for session in tab.sessions
        }
        active = {tab.tab_id: tab.active_session_id or "" for _, tab in tabs}
        selected = {
            window.window_id: window.current_tab.tab_id
            for window in app.terminal_windows
            if window.current_tab is not None
        }
        if preserve_focus:
            # An event arrived while the layout RPC was running. Its focus
            # wins, provided the referenced tabs and panes still exist.
            active.update(
                (tab_id, session_id)
                for tab_id, session_id in self._active_sessions_by_tab.items()
                if self._session_tab_ids.get(session_id) == tab_id
            )
            selected.update(
                (window_id, tab_id)
                for window_id, tab_id in self._selected_tabs_by_window.items()
                if self._tab_window_ids.get(tab_id) == window_id
            )
        self._active_sessions_by_tab = active
        self._selected_tabs_by_window = selected
        self._focused_by_window = {
            window_id: active[tab_id]
            for window_id, tab_id in selected.items()
            if active.get(tab_id)
        }
        self._apply_focused_cache()

    async def _refresh_focused_rows(self) -> None:
        """Recompute focused ids from a fresh snapshot and push them out."""
        epoch = self._focus_epoch
        iterm2_app = await iterm2.app.async_get_app(self.connection)
        if iterm2_app is None:
            return
        if epoch != self._focus_epoch:
            # A newer pane event already patched the cache while this RPC
            # was in flight. A trailing snapshot resolves the latest tab.
            self._focus_refresh_pending = True
            return
        self._index_layout(iterm2_app)
        await self._broadcast_focus()

    def _apply_focused_cache(self) -> None:
        """Update the focused flags on the cached scan in place."""
        for row in self._scan_cache[1]:
            session_id = str(row["id"])
            window_id = self._session_window_ids.get(session_id)
            row["focused"] = self._focused_by_window.get(window_id or "") == session_id

    async def _broadcast_focus(self) -> None:
        """Send only changed markers, scoped to each connected panel."""
        for client in list(self._sse_clients):
            window_id = self._sse_window_ids.get(client, "")
            if not window_id:
                continue
            session_id = self._focused_by_window.get(window_id, "")
            if self._sse_focus_ids.get(client) == session_id:
                continue
            try:
                await self._send_panel_event(
                    client,
                    "focus-changed",
                    {"window_id": window_id, "focused": [session_id] if session_id else []},
                )
            except Exception:
                self._sse_clients.discard(client)
                self._sse_window_ids.pop(client, None)
                self._sse_focus_ids.pop(client, None)
            else:
                self._sse_focus_ids[client] = session_id

    async def _broadcast_sse(
        self, event: str, data: object = None, *, window_id: str | None = None
    ) -> None:
        """Send an event, optionally restricted to panels bound to one window."""
        dead: list[web.StreamResponse] = []
        for client in list(self._sse_clients):
            if window_id is not None and self._sse_window_ids.get(client) != window_id:
                continue
            try:
                await self._send_panel_event(client, event, data)
            except Exception:
                dead.append(client)
        for d in dead:
            self._sse_clients.discard(d)
            self._sse_window_ids.pop(d, None)
            self._sse_focus_ids.pop(d, None)

    async def _send_panel_event(
        self, client: web.StreamResponse, event: str, data: object = None
    ) -> None:
        payload = {} if data is None else data
        if isinstance(client, web.WebSocketResponse):
            await asyncio.wait_for(client.send_json({"event": event, "data": payload}), timeout=2)
        else:
            # Older pages may reconnect before iTerm reloads their HTML.
            await asyncio.wait_for(
                client.write(f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()), timeout=2
            )

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """Push events without occupying WebKit's finite HTTP request slots."""
        response = web.WebSocketResponse(heartbeat=30, max_msg_size=1024)
        await response.prepare(request)
        self._sse_clients.add(response)
        self._sse_window_ids[response] = request.query.get("window", "")
        self._panel_health[response] = {
            "seen": time.monotonic(),
            "visible": False,
            "busy": False,
            "data_age_ms": None,
        }
        try:
            await self._broadcast_focus()
            async for message in response:
                if message.type != web.WSMsgType.TEXT:
                    continue
                try:
                    data = message.json()
                except (ValueError, TypeError):
                    continue
                if isinstance(data, dict) and data.get("event") == "panel-health":
                    age = data.get("data_age_ms")
                    self._panel_health[response] = {
                        "seen": time.monotonic(),
                        "visible": data.get("visible") is True,
                        "busy": data.get("busy") is True,
                        "data_age_ms": age if isinstance(age, (int, float)) and age >= 0 else None,
                    }
        finally:
            self._sse_clients.discard(response)
            self._sse_window_ids.pop(response, None)
            self._sse_focus_ids.pop(response, None)
            self._panel_health.pop(response, None)
        return response

    async def _monitor_panel_health(self) -> None:
        """Probe JS at low frequency; a live socket alone proves no UI health."""
        previous_tick = time.monotonic()
        while True:
            await asyncio.sleep(self._HEALTH_INTERVAL)
            now = time.monotonic()
            await self._check_panel_health(now, previous_tick)
            previous_tick = now
            await self._broadcast_sse("health-check")

    async def _check_panel_health(self, now: float, previous_tick: float) -> None:
        # Sleep/wake or a suspended event loop must get a new grace period.
        if now - previous_tick > self._HEALTH_INTERVAL * 3:
            self._panel_recovery_candidate = None
            for health in self._panel_health.values():
                health["seen"] = now
            return
        if now - self._last_panel_recovery < self._RECOVERY_COOLDOWN:
            return
        panels = [
            (self._sse_window_ids.get(client, ""), health)
            for client, health in list(self._panel_health.items())
            if client in self._sse_clients
        ]
        # Registration can rebuild all panels. Never discard an active edit,
        # search, or a panel known to be hidden; only repair a confirmed owner.
        if any(health["busy"] for _, health in panels):
            self._panel_recovery_candidate = None
            return
        stalled = {
            owner
            for owner, health in panels
            if owner and health["visible"] and now - health["seen"] > self._PANEL_TIMEOUT
        }
        if not stalled:
            self._panel_recovery_candidate = None
            return
        owner = await asyncio.wait_for(self._current_window_id(), timeout=3)
        if owner not in stalled:
            self._panel_recovery_candidate = None
            return
        if _SHOW_TOOLBELT_ID is None:
            return
        state = await asyncio.wait_for(
            iterm2.mainmenu.MainMenu.async_get_menu_item_state(self.connection, _SHOW_TOOLBELT_ID),
            timeout=3,
        )
        if not state.enabled or not state.checked:
            self._panel_recovery_candidate = None
            return
        # Give a newly foregrounded WebView a complete probe/ack round trip
        # before repairing it, even if its old visibility report was stale.
        candidate = self._panel_recovery_candidate
        if candidate is None or candidate[0] != owner:
            self._panel_recovery_candidate = (owner, now)
            return
        if now - candidate[1] < self._HEALTH_INTERVAL:
            return
        self._panel_recovery_candidate = None
        # Reserve the cooldown before calling iTerm so failures cannot loop.
        self._last_panel_recovery = now
        await register_panel(self.connection, self.url, rebuild=True)
        self._panel_recoveries += 1
        print("iterm-agents: rebuilt unresponsive Agents panels")

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """SSE endpoint for pushing events to the WebView."""
        response = web.StreamResponse()
        response.content_type = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        await response.prepare(request)
        self._sse_clients.add(response)
        self._sse_window_ids[response] = request.query.get("window", "")
        # A reconnect needs its current marker even if no pane has changed.
        await self._broadcast_focus()

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
            self._sse_focus_ids.pop(response, None)
        return response

    async def _current_window_id(self) -> str:
        """Resolve the key window once the panel has seen its own window is key."""
        # App receives layout notifications itself. Ownership validation only
        # needs fresh focus, not another full session hierarchy per activation.
        app = self._iterm_app or await iterm2.app.async_get_app(self.connection)
        if app is None:
            return ""
        self._iterm_app = app
        await app.async_refresh_focus()
        self._window_ids = {w.window_id for w in app.terminal_windows}
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
        return web.Response(
            text=AGENT_MONITOR_HTML, content_type="text/html", headers={"Cache-Control": "no-store"}
        )

    async def _handle_diagnostics(self, request: web.Request) -> web.Response:
        """Local transport counts, without session names or terminal content."""
        sockets = sum(isinstance(client, web.WebSocketResponse) for client in self._sse_clients)
        now = time.monotonic()
        return web.json_response(
            {
                "service": "iterm-agents",
                "event_streams": len(self._sse_clients) - sockets,
                "websocket_panels": sockets,
                "scan_age_seconds": now - self._scan_cache[0] if self._scan_cache[0] else None,
                "scan_in_progress_seconds": (
                    now - self._scan_started_at if self._scan_started_at is not None else None
                ),
                "scan_error": self._scan_error,
                "monitors": dict(self._monitor_states),
                "panel_recoveries": self._panel_recoveries,
                "panels": [
                    {
                        "js_age_seconds": now - health["seen"],
                        "visible": health["visible"],
                        "data_age_ms": health["data_age_ms"],
                    }
                    for client, health in list(self._panel_health.items())
                    if client in self._sse_clients
                ],
            }
        )

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
                    self._scan_started_at = time.monotonic()
                    raw = await asyncio.wait_for(self._scan_sessions(), timeout=self._SCAN_TIMEOUT)
                except Exception as error:
                    failure = type(error).__name__
                    if self._scan_error != failure:
                        print(f"iterm-agents: session scan unavailable ({failure})")
                    self._scan_error = failure
                    self._session_state.invalidate_observations()
                    if timestamp == 0.0:
                        raise web.HTTPServiceUnavailable(text="Session scan unavailable") from error
                    # Serve the previous display state; retry on the next poll.
                else:
                    self._scan_error = None
                    timestamp = time.monotonic()
                    self._scan_cache = (timestamp, raw)
                    fresh = True
                finally:
                    self._scan_started_at = None
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
        self._scan_refresh_task.add_done_callback(self._detached_done)

    async def _refresh_sessions(self) -> None:
        await self._handle_sessions(None)

    def _sessions_response(
        self, request: web.Request | None, *, fresh: bool = False
    ) -> web.Response:
        """Decorate a completed snapshot without advancing cached observations."""
        timestamp, raw = self._scan_cache
        sessions = self._session_state.apply(
            [s.copy() for s in raw], fresh=fresh, observed_at=timestamp
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
            sessions,
            headers={
                "X-Agents-Window": owner,
                "X-Agents-Stale": "1"
                if (self._scan_error or time.monotonic() - timestamp > self._STALE_AFTER)
                else "0",
                "Cache-Control": "no-store",
            },
        )

    async def _scan_sessions(self) -> list[SessionRow]:
        """Snapshot every session: variables, agent state, git, screen hints."""
        focus_epoch = self._focus_epoch
        iterm2_app = await iterm2.app.async_get_app(self.connection)
        if iterm2_app is None:
            raise RuntimeError("iterm-agents: session scan unavailable")
        self._index_layout(iterm2_app, preserve_focus=focus_epoch != self._focus_epoch)

        # A window opened after startup hides its toolbelt; open it once.
        # A window the user hides by hand stays marked and is not reopened.
        window_ids = {w.window_id for w in iterm2_app.terminal_windows}
        self._window_ids = window_ids
        self._toolbelt_ready_windows.intersection_update(window_ids)
        new_window_ids = window_ids - self._toolbelt_ready_windows
        if iterm2_app.current_terminal_window_id in new_window_ids:
            self._toolbelt_ready_windows.update(
                await self._ensure_toolbelts_visible(new_window_ids, activate_windows=False)
            )

        # Collect session PIDs for agent-session mapping. Fetching pid and
        # path per session serially costs two RPC round trips per session. The
        # gather is bounded by _scan_rpc_gate so a focus request can enter the
        # shared iTerm connection between small batches. The id map then lets
        # focus clicks and focus-change updates skip a full app snapshot.
        all_sessions = list(self._sessions_by_id.values())
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

        # Native process reads and fallback subprocesses are blocking, so
        # keep detection off the event loop to let focus requests proceed.
        session_pids = set(session_map.keys())
        agents = await asyncio.to_thread(detect_agents, session_pids) if session_pids else []
        agent_by_session_pid: dict[int, AgentInfo] = {}
        for detected in agents:
            if detected.session_pid is not None:
                agent_by_session_pid[detected.session_pid] = detected

        # Focus events update these maps during the scan. Do not reapply the
        # earlier layout snapshot after variables and process reads finish.
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

    async def _git_for(self, path: str) -> GitInfo | None:
        """Repo info for a path, cached briefly; sessions rarely move."""
        now = time.monotonic()
        cached = self._git_cache.get(path)
        if cached is not None and now - cached[0] < self._GIT_CACHE_TTL:
            return cached[1]
        task = self._git_tasks.get(path)
        if task is None:
            task = asyncio.create_task(asyncio.to_thread(get_git_info, path))
            self._git_tasks[path] = task
        try:
            info = await asyncio.shield(task)
        finally:
            if task.done():
                self._git_tasks.pop(path, None)
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
    ) -> SessionRow:
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
                if self._patch_focused_session(session_id, select_tab=True):
                    self._spawn_detached(self._broadcast_focus())
                return

        iterm2_app = await iterm2.app.async_get_app(self.connection)
        if iterm2_app is None:
            return
        self._index_layout(iterm2_app)

        for window in iterm2_app.terminal_windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    if session.session_id == session_id:
                        await session.async_activate()
                        if self._patch_focused_session(session_id, select_tab=True):
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
