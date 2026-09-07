"""Tests for MCP transport name validation."""

from __future__ import annotations

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
