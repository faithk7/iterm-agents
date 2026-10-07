from __future__ import annotations

import pytest

from iterm_agents.server import DEFAULT_HOST, AgentMonitorServer, _resolve_bound_port


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
