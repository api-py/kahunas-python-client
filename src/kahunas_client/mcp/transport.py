"""Validation of MCP transport selection.

The transport name arrives from an environment variable or a command line
argument, so it is untrusted text. FastMCP accepts only a fixed set of
literals, and passing anything else fails deep inside the library with a
message that does not name the offending value.

These helpers validate at the boundary instead, so a typo in
``KAHUNAS_MCP_TRANSPORT`` produces an immediate, actionable error.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

__all__ = [
    "HTTP_TRANSPORTS",
    "TRANSPORTS",
    "HttpTransport",
    "Transport",
    "parse_http_transport",
    "parse_transport",
]

Transport = Literal["stdio", "http", "sse", "streamable-http"]
"""Every transport FastMCP can serve."""

HttpTransport = Literal["http", "sse", "streamable-http"]
"""The subset of transports that expose an ASGI application."""

TRANSPORTS: Final[tuple[Transport, ...]] = get_args(Transport)
HTTP_TRANSPORTS: Final[tuple[HttpTransport, ...]] = get_args(HttpTransport)


def parse_transport(value: str) -> Transport:
    """Return ``value`` as a known transport name.

    Args:
        value: Raw transport name, matched case insensitively and trimmed.

    Returns:
        The validated transport literal.

    Raises:
        ValueError: If ``value`` is not a transport FastMCP supports. The
            message lists the accepted names.
    """
    normalised = value.strip().lower()
    for known in TRANSPORTS:
        if normalised == known:
            return known
    raise ValueError(f"Unknown MCP transport {value!r}. Expected one of: {', '.join(TRANSPORTS)}.")


def parse_http_transport(value: str) -> HttpTransport:
    """Return ``value`` as a transport that can serve an ASGI application.

    Args:
        value: Raw transport name, matched case insensitively and trimmed.

    Returns:
        The validated HTTP capable transport literal.

    Raises:
        ValueError: If ``value`` is not an HTTP capable transport. ``stdio``
            is rejected here because it has no ASGI application to mount.
    """
    transport = parse_transport(value)
    if transport == "stdio":
        raise ValueError(
            "The stdio transport cannot serve an HTTP application. "
            f"Expected one of: {', '.join(HTTP_TRANSPORTS)}."
        )
    return transport
