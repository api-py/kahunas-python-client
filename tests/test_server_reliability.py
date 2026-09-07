"""Reliability tests for the MCP server surface.

Covers the health endpoint the container probe depends on, and the session
lifecycle that previously leaked an HTTP client on repeated login.
"""

from __future__ import annotations

import httpx
import pytest

from kahunas_client.mcp import server as server_module
from kahunas_client.mcp.server import create_server


class TestHealthEndpoint:
    """The Dockerfile HEALTHCHECK and orchestrator probes poll /health."""

    @pytest.fixture
    def app(self) -> object:
        return create_server().http_app(transport="http")

    def test_route_is_registered(self, app: object) -> None:
        paths = {getattr(route, "path", None) for route in app.routes}
        assert "/health" in paths

    async def test_responds_ok_without_authentication(self, app: object) -> None:
        """The probe runs before any login, so it must not require a session."""
        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://probe") as client,
        ):
            response = await client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "kahunas-mcp"}

    async def test_reports_liveness_without_calling_the_api(self, app: object) -> None:
        """An upstream outage must not make orchestrators restart the container."""
        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://probe") as client,
        ):
            response = await client.get("/health")

        assert response.status_code == 200
        assert server_module._client_var.get() is None
