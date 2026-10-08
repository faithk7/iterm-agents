from __future__ import annotations

import pytest

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

        assert await server._devin_state_from_screen(_Session(running), "idle") == "running"
        assert await server._devin_state_from_screen(_Session(idle), "idle") == "idle"
