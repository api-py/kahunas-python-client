"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
import respx

from kahunas_client.config import KahunasConfig
from kahunas_client.data_sync import SyncStore
from kahunas_client.mcp import server as server_module
from kahunas_client.metrics_store import MetricsStore


@pytest.fixture(autouse=True)
def close_session_stores(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Close every local store a test opened.

    The server caches a MetricsStore and a SyncStore per session in context
    variables, but those are set inside the tool's own task, so its context
    is not visible from a fixture. Every instance is therefore tracked as it
    is constructed and closed here, which leaves no SQLite connection to be
    reported as a ResourceWarning when it is collected.
    """
    opened: list[MetricsStore | SyncStore] = []

    def track(cls: type) -> Callable[..., Any]:
        def build(*args: Any, **kwargs: Any) -> Any:
            store = cls(*args, **kwargs)
            opened.append(store)
            return store

        return build

    monkeypatch.setattr(server_module, "MetricsStore", track(MetricsStore))
    monkeypatch.setattr(server_module, "SyncStore", track(SyncStore))

    yield

    for store in opened:
        store.close()
    for var in (server_module._metrics_var, server_module._sync_var):
        var.set(None)


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
