"""Shared test fixtures."""

from __future__ import annotations

import pytest
import respx

from kahunas_client.config import KahunasConfig


@pytest.fixture
def config() -> KahunasConfig:
    """Test config with a pre-set token (skips login flow)."""
    return KahunasConfig(
        api_base_url="https://api.kahunas.io/api",
        web_base_url="https://kahunas.io",
        auth_token="test-token-abc123",
        email="test@example.com",
        password="testpass",
    )


@pytest.fixture
def mock_api() -> respx.MockRouter:
    """Provide a respx mock router for the Kahunas API."""
    with respx.mock(base_url="https://api.kahunas.io/api") as router:
        yield router


@pytest.fixture
def mock_web() -> respx.MockRouter:
    """Provide a respx mock router for the Kahunas web app."""
    with respx.mock(base_url="https://kahunas.io") as router:
        yield router
