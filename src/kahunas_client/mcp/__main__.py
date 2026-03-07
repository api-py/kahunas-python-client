"""Entry point for running the MCP server: python -m kahunas_client.mcp

Transport modes:
    stdio (default)  — single-session, used by Claude Desktop / IDE integrations
    http             — multi-session HTTP + SSE, used for remote hosting (e.g. Azure)
    sse              — legacy SSE-only transport

Environment variables for HTTP mode:
    KAHUNAS_MCP_HOST  — bind address (default: 0.0.0.0)
    KAHUNAS_MCP_PORT  — port number  (default: 8000)
"""

from __future__ import annotations

import os
import sys

from .server import create_server


def main() -> None:
    transport = os.getenv("KAHUNAS_MCP_TRANSPORT", "stdio").lower()
    if len(sys.argv) > 1 and sys.argv[1] in ("http", "sse", "streamable-http", "stdio"):
        transport = sys.argv[1]

    server = create_server()

    if transport in ("http", "sse", "streamable-http"):
        host = os.getenv("KAHUNAS_MCP_HOST", "0.0.0.0")
        port = int(os.getenv("KAHUNAS_MCP_PORT", "8000"))
        server.run(
            transport=transport,
            host=host,
            port=port,
        )
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
