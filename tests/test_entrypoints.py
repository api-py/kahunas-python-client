"""Tests for the process entry points.

Covers the module runner and the AWS Lambda handler, which select a
transport from untrusted environment input before the server starts.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from kahunas_client.mcp import __main__ as entry


@pytest.fixture
def fake_server(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace create_server so nothing binds a socket."""
    server = MagicMock()
    monkeypatch.setattr(entry, "create_server", lambda: server)
    return server


class TestTransportSelection:
    """argv wins over the environment, and both are validated."""

    def test_defaults_to_stdio(
        self, fake_server: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["kahunas-mcp"])
        monkeypatch.delenv("KAHUNAS_MCP_TRANSPORT", raising=False)
        entry.main()
        fake_server.run.assert_called_once_with(transport="stdio")

    def test_environment_selects_the_transport(
        self, fake_server: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["kahunas-mcp"])
        monkeypatch.setenv("KAHUNAS_MCP_TRANSPORT", "http")
        monkeypatch.delenv("KAHUNAS_MCP_HOST", raising=False)
        monkeypatch.delenv("KAHUNAS_MCP_PORT", raising=False)
        entry.main()
        kwargs = fake_server.run.call_args.kwargs
        assert kwargs["transport"] == "http"

    def test_argv_overrides_the_environment(
        self, fake_server: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["kahunas-mcp", "sse"])
        monkeypatch.setenv("KAHUNAS_MCP_TRANSPORT", "stdio")
        entry.main()
        assert fake_server.run.call_args.kwargs["transport"] == "sse"

    def test_unknown_transport_exits_with_a_named_reason(
        self, fake_server: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo previously failed deep inside FastMCP without naming the value."""
        monkeypatch.setattr(sys, "argv", ["kahunas-mcp", "htpp"])
        with pytest.raises(SystemExit) as excinfo:
            entry.main()
        assert "htpp" in str(excinfo.value)
        fake_server.run.assert_not_called()


class TestHttpBinding:
    """Host and port handling for the HTTP transports."""

    def test_binds_loopback_by_default(
        self, fake_server: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The transport has no authentication, so it must not default to 0.0.0.0."""
        monkeypatch.setattr(sys, "argv", ["kahunas-mcp", "http"])
        monkeypatch.delenv("KAHUNAS_MCP_HOST", raising=False)
        monkeypatch.delenv("KAHUNAS_MCP_PORT", raising=False)
        entry.main()
        kwargs = fake_server.run.call_args.kwargs
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 8000

    def test_host_and_port_are_configurable(
        self, fake_server: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["kahunas-mcp", "http"])
        monkeypatch.setenv("KAHUNAS_MCP_HOST", "0.0.0.0")  # noqa: S104 - explicit opt in
        monkeypatch.setenv("KAHUNAS_MCP_PORT", "9001")
        entry.main()
        kwargs = fake_server.run.call_args.kwargs
        assert kwargs["host"] == "0.0.0.0"  # noqa: S104 - asserting the opt in took effect
        assert kwargs["port"] == 9001

    def test_non_numeric_port_exits_with_a_clear_message(
        self, fake_server: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["kahunas-mcp", "http"])
        monkeypatch.setenv("KAHUNAS_MCP_PORT", "eight thousand")
        with pytest.raises(SystemExit) as excinfo:
            entry.main()
        assert "KAHUNAS_MCP_PORT" in str(excinfo.value)
        fake_server.run.assert_not_called()


class TestLambdaHandler:
    """The Lambda entry point builds an ASGI app at import time."""

    def test_builds_a_handler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("mangum")
        monkeypatch.setenv("KAHUNAS_MCP_TRANSPORT", "streamable-http")
        for module in [m for m in sys.modules if m.endswith("mcp.lambda_handler")]:
            del sys.modules[module]

        from kahunas_client.mcp import lambda_handler

        assert lambda_handler.handler is not None

    def test_rejects_stdio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """stdio has no ASGI application, so it cannot serve Lambda requests."""
        pytest.importorskip("mangum")
        monkeypatch.setenv("KAHUNAS_MCP_TRANSPORT", "stdio")
        for module in [m for m in sys.modules if m.endswith("mcp.lambda_handler")]:
            del sys.modules[module]

        with pytest.raises(ValueError, match="stdio transport cannot serve"):
            import kahunas_client.mcp.lambda_handler  # noqa: F401


def test_module_is_runnable_as_a_script() -> None:
    """python -m kahunas_client.mcp must reach main()."""
    assert callable(entry.main)
    assert entry.__name__.endswith("__main__")
