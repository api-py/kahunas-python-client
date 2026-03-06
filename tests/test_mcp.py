"""Tests for the MCP server tool registration."""

from __future__ import annotations

from kahunas_client.mcp.server import create_server


class TestMCPServerCreation:
    def test_create_server(self) -> None:
        server = create_server()
        assert server is not None
        assert server.name == "kahunas"

    def test_server_has_tools(self) -> None:
        server = create_server()
        # FastMCP 3.x exposes tools via list_tools / get_tool
        assert callable(server.list_tools)
