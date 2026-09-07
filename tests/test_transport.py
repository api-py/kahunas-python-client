"""Tests for MCP transport name validation."""

from __future__ import annotations

from typing import get_args

import pytest

from kahunas_client.mcp.transport import (
    HTTP_TRANSPORTS,
    TRANSPORTS,
    parse_http_transport,
    parse_transport,
)


class TestTransportSets:
    """The exported literal sets stay in step with FastMCP."""

    def test_all_transports_listed(self) -> None:
        assert set(TRANSPORTS) == {"stdio", "http", "sse", "streamable-http"}

    def test_http_transports_exclude_stdio(self) -> None:
        assert set(HTTP_TRANSPORTS) == {"http", "sse", "streamable-http"}
        assert "stdio" not in HTTP_TRANSPORTS

    def test_matches_the_transports_fastmcp_accepts(self) -> None:
        """Our literal set is a copy of FastMCP's, so it can drift on upgrade.

        Catching that here fails the build on a FastMCP release that adds or
        removes a transport, rather than letting a valid transport be
        rejected at the process boundary.
        """
        from fastmcp.server.server import Transport as FastMCPTransport

        assert set(TRANSPORTS) == set(get_args(FastMCPTransport))

    @pytest.mark.parametrize("name", HTTP_TRANSPORTS)
    def test_every_http_transport_really_builds_an_app(self, name: str) -> None:
        """Behavioural check: each one must actually mount an ASGI app.

        Asserting against FastMCP's type annotation would only compare
        strings; building the app proves the transport is still supported.
        """
        from kahunas_client.mcp.server import create_server

        app = create_server().http_app(transport=name)
        assert any(getattr(route, "path", None) == "/health" for route in app.routes)

    def test_stdio_is_not_an_http_transport(self) -> None:
        assert "stdio" not in HTTP_TRANSPORTS
        assert set(TRANSPORTS) - set(HTTP_TRANSPORTS) == {"stdio"}


class TestParseTransport:
    """Accepting every supported transport and rejecting the rest."""

    @pytest.mark.parametrize("name", TRANSPORTS)
    def test_accepts_every_known_transport(self, name: str) -> None:
        assert parse_transport(name) == name

    @pytest.mark.parametrize(("raw", "expected"), [("  HTTP ", "http"), ("SSE", "sse")])
    def test_normalises_case_and_whitespace(self, raw: str, expected: str) -> None:
        assert parse_transport(raw) == expected

    def test_rejects_unknown_name(self) -> None:
        with pytest.raises(ValueError, match="Unknown MCP transport"):
            parse_transport("grpc")

    def test_error_names_the_offending_value_and_the_alternatives(self) -> None:
        """The whole point of validating here is an actionable message."""
        with pytest.raises(ValueError) as excinfo:
            parse_transport("htpp")
        message = str(excinfo.value)
        assert "'htpp'" in message
        for name in TRANSPORTS:
            assert name in message

    def test_rejects_empty_value(self) -> None:
        with pytest.raises(ValueError, match="Unknown MCP transport"):
            parse_transport("")


class TestParseHttpTransport:
    """The ASGI capable subset."""

    @pytest.mark.parametrize("name", HTTP_TRANSPORTS)
    def test_accepts_http_capable_transports(self, name: str) -> None:
        assert parse_http_transport(name) == name

    def test_rejects_stdio_with_a_specific_reason(self) -> None:
        with pytest.raises(ValueError, match="stdio transport cannot serve"):
            parse_http_transport("stdio")

    def test_rejects_unknown_name(self) -> None:
        with pytest.raises(ValueError, match="Unknown MCP transport"):
            parse_http_transport("websocket")
