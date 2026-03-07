"""AWS Lambda handler for Kahunas MCP Server.

Wraps the FastMCP HTTP app as an ASGI handler suitable for AWS Lambda
using Mangum. The handler is compatible with AWS Lambda container images
and Function URLs.

Environment variables:
    KAHUNAS_EMAIL       — Kahunas account email
    KAHUNAS_PASSWORD    — Kahunas account password
    KAHUNAS_MCP_TRANSPORT — Transport type (default: streamable-http)
"""

from __future__ import annotations

import os

from mangum import Mangum

from .server import create_server

_transport = os.getenv("KAHUNAS_MCP_TRANSPORT", "streamable-http")
_server = create_server()
_app = _server.http_app(transport=_transport)

handler = Mangum(_app, lifespan="off")
