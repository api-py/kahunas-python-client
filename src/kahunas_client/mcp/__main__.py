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
from .transport import parse_transport


def main() -> None:
    """Start the MCP server on the transport named by argv or the environment."""
    raw_transport = (
        sys.argv[1] if len(sys.argv) > 1 else os.getenv("KAHUNAS_MCP_TRANSPORT", "stdio")
    )
    try:
        transport = parse_transport(raw_transport)
    except ValueError as exc:
        sys.exit(str(exc))

    server = create_server()

    if transport == "stdio":
        server.run(transport=transport)
        return

    host = os.getenv("KAHUNAS_MCP_HOST", "0.0.0.0")
    raw_port = os.getenv("KAHUNAS_MCP_PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError:
        sys.exit(f"KAHUNAS_MCP_PORT must be an integer, got {raw_port!r}.")

    server.run(transport=transport, host=host, port=port)


if __name__ == "__main__":
    main()
