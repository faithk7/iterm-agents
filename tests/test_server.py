from __future__ import annotations

import asyncio

import pytest

from iterm_agents.detector import AgentType, GitInfo
from iterm_agents.server import DEFAULT_HOST, AgentMonitorServer, _resolve_bound_port


class _Line:
    def __init__(self, text: str) -> None:
        self.string = text


class _Screen:
    def __init__(self, text: str) -> None:
        self._lines = text.splitlines() or [""]

    @property
    def number_of_lines(self) -> int:
        return len(self._lines)

    def line(self, index: int) -> _Line:
        return _Line(self._lines[index])


class _Session:
    def __init__(self, text: str) -> None:
        self.session_id = "session-1"
        self._text = text

    async def async_get_screen_contents(self) -> _Screen:
        return _Screen(self._text)


_FROZEN_FOOTER = "\n".join(
    [
        "  ⠰⠳ Running  2.79k tokens",
        "  ▄▄▄▄▄▄▄▄",
        "  → Add a follow-up                                       ctrl+c to stop",
        "  ▀▀▀▀▀▀▀▀",
        "  3 tasks",
        "  ~",
    ]
)


class _State:
    def __init__(self, checked: bool, enabled: bool) -> None:
        self.checked = checked
        self.enabled = enabled


class _ScanSession:
    def __init__(self, pid: int, path: str = "") -> None:
        self.session_id = f"s-{pid}"
        self.name = ""
        self._pid = pid
        self._path = path

    async def async_get_variable(self, name: str) -> object:
        return self._pid if name == "pid" else self._path


class _FocusRequest:
    def __init__(self, session_id: str) -> None:
        self.query = {"session": session_id}


class _BlockingActivateSession:
    def __init__(
        self,
        session_id: str,
        starts: list[str],
        active: list[int],
        max_active: list[int],
    ) -> None:
        self.session_id = session_id
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self._starts = starts
        self._active = active
        self._max_active = max_active

    async def async_activate(self) -> None:
        self._starts.append(self.session_id)
        self._active[0] += 1
        self._max_active[0] = max(self._max_active[0], self._active[0])
        self.started.set()
        try:
            await self.release.wait()
        finally:
            self._active[0] -= 1


class _GatedScanSession(_ScanSession):
    def __init__(
        self,
        pid: int,
        calls: list[str],
        scan_saturated: asyncio.Event,
        release_scan: asyncio.Event,
        focus_started: asyncio.Event,
    ) -> None:
        super().__init__(pid)
        self._calls = calls
        self._scan_saturated = scan_saturated
        self._release_scan = release_scan
        self._focus_started = focus_started

    async def async_get_variable(self, name: str) -> object:
        self._calls.append(f"scan:{self.session_id}:{name}")
        if len(self._calls) >= 4:
            self._scan_saturated.set()
        await self._release_scan.wait()
        return await super().async_get_variable(name)

    async def async_activate(self) -> None:
        self._calls.append("focus")
        self._focus_started.set()


class _ScanTab:
    def __init__(
        self, sessions: list[_ScanSession], active_session_id: str | None = None
    ) -> None:
        self.sessions = sessions
        self.active_session_id = active_session_id


class _ToolbeltWindow:
    def __init__(self, window_id: str, app: _App, becomes_key: bool = True) -> None:
        self.window_id = window_id
        self._app = app
        self._becomes_key = becomes_key
        self.tabs: list[_ScanTab] = []

    @property
    def current_tab(self) -> _ScanTab | None:
        return self.tabs[0] if self.tabs else None

    async def async_activate(self) -> None:
        self._app.activations.append(self.window_id)
        if self._becomes_key:
            self._app.current_terminal_window_id = self.window_id


class _App:
    """Fake iTerm2 app: menu state and toggles are tracked per key window."""

    def __init__(self, shown: dict[str, bool], enabled: bool = True) -> None:
        self.shown = shown
        self.enabled = enabled
        self.activations: list[str] = []
        self.current_terminal_window_id = next(iter(shown), None)
        self.terminal_windows = [
            _ToolbeltWindow(window_id, self) for window_id in shown
        ]

    @property
    def current_window(self) -> _ToolbeltWindow | None:
        return self.get_window_by_id(self.current_terminal_window_id)

    def get_window_by_id(self, window_id: str | None) -> _ToolbeltWindow | None:
        return next(
            (w for w in self.terminal_windows if w.window_id == window_id), None
        )

    async def async_refresh_focus(self) -> None:
        pass

    async def async_get_menu_item_state(self, _connection: object, _identifier: str) -> _State:
        return _State(self.shown.get(self.current_terminal_window_id, False), self.enabled)

    async def async_select_menu_item(self, _connection: object, _identifier: str) -> None:
        window_id = self.current_terminal_window_id
        if window_id is not None:
            self.shown[window_id] = not self.shown.get(window_id, False)


def _patch_iterm(monkeypatch: pytest.MonkeyPatch, app: _App) -> None:
    async def fake_get_app(_connection: object) -> _App:
        return app

    monkeypatch.setattr("iterm_agents.server.iterm2.app.async_get_app", fake_get_app)
    monkeypatch.setattr(
        "iterm_agents.server.iterm2.mainmenu.MainMenu.async_get_menu_item_state",
        app.async_get_menu_item_state,
    )
    monkeypatch.setattr(
        "iterm_agents.server.iterm2.mainmenu.MainMenu.async_select_menu_item",
        app.async_select_menu_item,
    )


class TestResolveBoundPort:
    def test_resolves_ipv4_port(self) -> None:
        assert _resolve_bound_port([("127.0.0.1", 50123)]) == 50123

    def test_resolves_ipv6_port(self) -> None:
        assert _resolve_bound_port([("::1", 50123, 0, 0)]) == 50123

    def test_rejects_multiple_ports(self) -> None:
        with pytest.raises(RuntimeError, match="multiple bound ports detected"):
            _resolve_bound_port([("::1", 63200, 0, 0), ("127.0.0.1", 63201)])

    def test_rejects_missing_ports(self) -> None:
        with pytest.raises(RuntimeError, match="failed to determine bound port"):
            _resolve_bound_port([])


class TestAgentMonitorServer:
    def test_url_uses_default_host_and_current_port(self) -> None:
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
        server.port = 50123

        assert server.host == DEFAULT_HOST
        assert server.url == "http://127.0.0.1:50123/"

    async def test_frozen_footer_returns_to_idle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
        clock = {"now": 0.0}
        monkeypatch.setattr("iterm_agents.server.time.monotonic", lambda: clock["now"])
        session = _Session(_FROZEN_FOOTER)

        assert await server._cursor_state_from_screen(session, "idle") == "running"
        clock["now"] = 10.0
        assert await server._cursor_state_from_screen(session, "idle") == "running"
        clock["now"] = 31.0
        assert await server._cursor_state_from_screen(session, "idle") == "idle"

    async def test_devin_interrupt_hint_is_running(self) -> None:
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
        running = "\n".join(
            [
                "  ⠀⠸ Running tools · 2m 28s (esc twice to interrupt)",
                "  ─────────────────────────── (bypass permissions on) ─",
                "  ❭ Guide Devin while it works",
                "  ───────────────────────────────────────────────",
                "  SWE-2 Max                       Context: 89k / 262k tokens (34%)",
            ]
        )
        idle = "\n".join(
            [
                "  ─────────────────────────── (bypass permissions on) ─",
                "  ❭ Ask Devin to build features, fix bugs, or work on your code",
                "  ───────────────────────────────────────────────",
                "  SWE-2 Max                       Context: 89k / 262k tokens (34%)",
            ]
        )

        assert (
            await server._screen_hint_state(_Session(running), AgentType.DEVIN, "idle")
            == "running"
        )
        assert (
            await server._screen_hint_state(_Session(idle), AgentType.DEVIN, "idle")
            == "idle"
        )

    async def test_codex_interrupt_hint_is_running(self) -> None:
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
        running = "\n".join(
            [
                "  • Working (4m 34s • esc to interrupt)",
                "    └ Tip: Press ⌃r to search previously entered prompts.",
                "  \u203a Ask Codex to do anything",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
            ]
        )
        idle = "\n".join(
            [
                "  \u203a Ask Codex to do anything",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
                "  ? for shortcuts",
            ]
        )

        assert (
            await server._screen_hint_state(_Session(running), AgentType.CODEX, "idle")
            == "running"
        )
        assert (
            await server._screen_hint_state(_Session(idle), AgentType.CODEX, "idle")
            == "idle"
        )

    async def test_kimi_busy_label_is_running(self) -> None:
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
        running = "\n".join(
            [
                "  001 [⣿⣦⣀⣀⣀⣀⣀⣀] Let me write the first reque…",
                "  🌗 Working…  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "   ──────────────────────────────────────────────",
                "    Todo",
                "    ● 写 43 条回复 —— 6 …",
                "    … +1 more (1 done) · ctrl+t to expand",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  Ask When Needed swarm  K2.8 Preview thinking:…",
            ]
        )
        idle = "\n".join(
            [
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  Ask When Needed K3 thinking: max",
            ]
        )

        assert (
            await server._screen_hint_state(_Session(running), AgentType.KIMI, "idle")
            == "running"
        )
        assert (
            await server._screen_hint_state(_Session(idle), AgentType.KIMI, "idle")
            == "idle"
        )

    async def test_toolbelt_shown_in_every_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # w1 is key and already showing; w2 and w3 are hidden.
        app = _App({"w1": True, "w2": False, "w3": False})
        _patch_iterm(monkeypatch, app)
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]

        ensured = await server._ensure_toolbelts_visible({"w1", "w2", "w3"})

        assert ensured == {"w1", "w2", "w3"}
        assert app.shown == {"w1": True, "w2": True, "w3": True}
        # Non-key windows were made key, toggled, and focus was restored.
        assert app.activations == ["w2", "w3", "w1"]

    async def test_toolbelt_already_shown_skips_toggle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _App({"w1": True, "w2": True})
        _patch_iterm(monkeypatch, app)
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]

        ensured = await server._ensure_toolbelts_visible({"w1", "w2"})

        assert ensured == {"w1", "w2"}
        assert app.shown == {"w1": True, "w2": True}

    async def test_toolbelt_disabled_menu_stays_hidden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # iTerm2 in the background: don't activate or toggle anything.
        app = _App({"w1": False, "w2": False}, enabled=False)
        _patch_iterm(monkeypatch, app)
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]

        ensured = await server._ensure_toolbelts_visible({"w1", "w2"})

        assert ensured == set()
        assert app.activations == []
        assert app.shown == {"w1": False, "w2": False}

    async def test_toolbelt_window_that_cannot_take_key_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _App({"w1": True, "w2": False, "w3": False})
        for window in app.terminal_windows:
            if window.window_id == "w2":
                window._becomes_key = False
        _patch_iterm(monkeypatch, app)
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]

        ensured = await server._ensure_toolbelts_visible({"w2", "w3"})

        # w2 could not become key, so its menu item was never hit; w3 got it.
        assert ensured == {"w3"}
        assert app.shown == {"w1": True, "w2": False, "w3": True}
        assert app.activations == ["w2", "w3", "w1"]

    async def test_scan_ensures_new_windows_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _App({"w1": False})
        app.terminal_windows[0].tabs = [_ScanTab([_ScanSession(11)])]
        _patch_iterm(monkeypatch, app)
        monkeypatch.setattr("iterm_agents.server.detect_agents", lambda _pids: [])
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
        calls: list[set[str]] = []

        async def fake_ensure(window_ids: set[str]) -> set[str]:
            calls.append(set(window_ids))
            return set(window_ids)

        monkeypatch.setattr(server, "_ensure_toolbelts_visible", fake_ensure)

        await server._scan_sessions()
        assert calls == [{"w1"}]

        # Already-ensured windows are not requested again.
        await server._scan_sessions()
        assert calls == [{"w1"}]

        # A window opened later is requested once.
        window = _ToolbeltWindow("w2", app)
        window.tabs = [_ScanTab([_ScanSession(22)])]
        app.terminal_windows.append(window)
        await server._scan_sessions()
        assert calls == [{"w1"}, {"w2"}]

    async def test_scan_marks_each_windows_active_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _App({"w1": False})
        app.terminal_windows[0].tabs = [
            _ScanTab([_ScanSession(11), _ScanSession(22)], active_session_id="s-22")
        ]
        _patch_iterm(monkeypatch, app)
        monkeypatch.setattr("iterm_agents.server.detect_agents", lambda _pids: [])
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]

        rows = await server._scan_sessions()

        focused = {row["id"]: row["focused"] for row in rows}
        assert focused == {"s-11": False, "s-22": True}

    async def test_scan_shares_git_results_and_refreshes_expired_paths(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _App({"w1": True})
        app.terminal_windows[0].tabs = [
            _ScanTab(
                [
                    _ScanSession(11, "/repo-a"),
                    _ScanSession(22, "/repo-a"),
                    _ScanSession(33, "/repo-b"),
                    _ScanSession(44),
                ]
            )
        ]
        _patch_iterm(monkeypatch, app)
        monkeypatch.setattr("iterm_agents.server.detect_agents", lambda _pids: [])
        calls: list[str] = []
        branch = "main"

        def fake_git(path: str) -> GitInfo:
            calls.append(path)
            return GitInfo(repo=path[1:], branch=branch, root_repo=path)

        monkeypatch.setattr("iterm_agents.server.get_git_info", fake_git)
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
        server._toolbelt_ready_windows = {"w1"}

        rows = await server._scan_sessions()
        assert sorted(calls) == ["/repo-a", "/repo-b"]
        assert [r["repo"] for r in rows] == ["repo-a", "repo-a", "repo-b", ""]
        assert [r["branch"] for r in rows] == ["main", "main", "main", ""]

        await server._scan_sessions()
        assert len(calls) == 2
        branch = "feature"
        server._git_cache = {path: (0.0, info) for path, (_, info) in server._git_cache.items()}
        rows = await server._scan_sessions()
        assert sorted(calls) == ["/repo-a", "/repo-a", "/repo-b", "/repo-b"]
        assert [r["branch"] for r in rows] == ["feature", "feature", "feature", ""]

    def test_patch_focused_session_moves_the_marker(self) -> None:
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
        server._sessions_by_id = {"s-1": object(), "s-2": object()}  # type: ignore[dict-item]
        server._focused_ids = {"s-1"}
        server._scan_cache = (1.0, [{"id": "s-1"}, {"id": "s-2"}])

        assert server._patch_focused_session("s-2")

        assert server._focused_ids == {"s-2"}
        assert [row["focused"] for row in server._scan_cache[1]] == [False, True]

    def test_patch_focused_session_unknown_id_defers(self) -> None:
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]

        assert not server._patch_focused_session("ghost")

    async def test_rapid_focus_requests_coalesce_to_latest_without_overlapping(self) -> None:
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
        starts: list[str] = []
        active = [0]
        max_active = [0]
        sessions = {
            session_id: _BlockingActivateSession(session_id, starts, active, max_active)
            for session_id in ("s-1", "s-2", "s-3")
        }
        server._sessions_by_id = sessions  # type: ignore[assignment]
        server._scan_cache = (
            1.0,
            [{"id": session_id, "focused": False} for session_id in sessions],
        )

        # HTTP handlers must acknowledge clicks immediately; one worker owns
        # iTerm's activation RPC and drops intermediate targets while busy.
        await asyncio.wait_for(
            server._handle_focus(_FocusRequest("s-1")),  # type: ignore[arg-type]
            timeout=1,
        )
        await asyncio.wait_for(sessions["s-1"].started.wait(), timeout=1)
        await asyncio.wait_for(
            server._handle_focus(_FocusRequest("s-2")),  # type: ignore[arg-type]
            timeout=1,
        )
        await asyncio.wait_for(
            server._handle_focus(_FocusRequest("s-3")),  # type: ignore[arg-type]
            timeout=1,
        )

        assert starts == ["s-1"]
        assert max_active == [1]

        sessions["s-1"].release.set()
        await asyncio.wait_for(sessions["s-3"].started.wait(), timeout=1)
        assert starts == ["s-1", "s-3"]
        assert not sessions["s-2"].started.is_set()
        assert max_active == [1]

        sessions["s-3"].release.set()
        assert server._focus_worker_task is not None
        await asyncio.wait_for(server._focus_worker_task, timeout=1)
        assert server._focused_ids == {"s-3"}

    async def test_focus_is_not_queued_behind_the_whole_session_scan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        scan_saturated = asyncio.Event()
        release_scan = asyncio.Event()
        focus_started = asyncio.Event()
        sessions = [
            _GatedScanSession(
                pid,
                calls,
                scan_saturated,
                release_scan,
                focus_started,
            )
            for pid in range(20)
        ]
        app = _App({"w1": True})
        app.terminal_windows[0].tabs = [_ScanTab(sessions)]
        _patch_iterm(monkeypatch, app)
        monkeypatch.setattr("iterm_agents.server.detect_agents", lambda _pids: [])
        server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
        server._toolbelt_ready_windows = {"w1"}

        scan_task = asyncio.create_task(server._scan_sessions())
        await asyncio.wait_for(scan_saturated.wait(), timeout=1)
        await asyncio.sleep(0)
        await server._handle_focus(  # type: ignore[arg-type]
            _FocusRequest(sessions[-1].session_id)
        )
        await asyncio.wait_for(focus_started.wait(), timeout=1)

        assert calls.index("focus") <= 4

        release_scan.set()
        await asyncio.wait_for(scan_task, timeout=1)
