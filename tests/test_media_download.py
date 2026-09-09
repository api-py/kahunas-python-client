"""Tests for media download policy in the MCP server.

Photo and attachment URLs, and attachment filenames, all originate from the
Kahunas API. These are regression tests for three defects: the filename was
joined onto the output directory unsanitised, the URL scheme was never
checked, and the response body was buffered without a size limit.
"""

from __future__ import annotations

import httpx
import pytest

from kahunas_client.mcp.server import (
    _MAX_MEDIA_BYTES,
    _download_bounded,
    _is_downloadable_url,
    _media_extension,
)
from kahunas_client.safepath import safe_join


class TestDownloadableUrl:
    """Only absolute HTTP(S) URLs may be fetched."""

    @pytest.mark.parametrize(
        "url",
        ["http://example.test/a.jpg", "https://example.test/a.jpg", "https://example.test:8443/a"],
    )
    def test_accepts_http_urls(self, url: str) -> None:
        assert _is_downloadable_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "file://localhost/etc/shadow",
            "ftp://example.test/a.jpg",
            "gopher://example.test/",
            "data:text/plain;base64,aGk=",
            "javascript:alert(1)",
        ],
    )
    def test_rejects_other_schemes(self, url: str) -> None:
        """A file:// URL would make the tool read local files on request."""
        assert _is_downloadable_url(url) is False

    @pytest.mark.parametrize("url", ["", "not a url", "/relative/path.jpg", "https://"])
    def test_rejects_urls_without_a_host(self, url: str) -> None:
        assert _is_downloadable_url(url) is False


class TestMediaExtension:
    """Extension is chosen from the served content type."""

    @pytest.mark.parametrize(
        ("content_type", "expected"),
        [
            ("image/png", ".png"),
            ("image/webp", ".webp"),
            ("image/gif", ".gif"),
            ("image/jpeg", ".jpg"),
            ("image/png; charset=binary", ".png"),
            ("IMAGE/PNG", ".png"),
        ],
    )
    def test_maps_known_types(self, content_type: str, expected: str) -> None:
        assert _media_extension(content_type) == expected

    @pytest.mark.parametrize("content_type", ["", "application/octet-stream", "text/html"])
    def test_falls_back_for_unknown_types(self, content_type: str) -> None:
        assert _media_extension(content_type) == ".jpg"


class TestBoundedDownload:
    """Size capping and failure handling."""

    async def test_returns_body_and_content_type(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"data", headers={"content-type": "image/png"}
            )
        )
        async with httpx.AsyncClient(transport=transport) as http:
            result = await _download_bounded(http, "https://example.test/a.png")
        assert result == (b"data", "image/png")

    async def test_refuses_disallowed_scheme_without_fetching(self) -> None:
        def explode(request: httpx.Request) -> httpx.Response:
            raise AssertionError("must not attempt a request for a rejected scheme")

        async with httpx.AsyncClient(transport=httpx.MockTransport(explode)) as http:
            assert await _download_bounded(http, "file:///etc/passwd") is None

    async def test_returns_none_on_error_status(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(404))
        async with httpx.AsyncClient(transport=transport) as http:
            assert await _download_bounded(http, "https://example.test/missing.png") is None

    async def test_rejects_body_declared_over_the_cap(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"x", headers={"content-length": str(_MAX_MEDIA_BYTES + 1)}
            )
        )
        async with httpx.AsyncClient(transport=transport) as http:
            assert await _download_bounded(http, "https://example.test/big.png") is None

    async def test_rejects_body_that_exceeds_the_cap_while_streaming(self) -> None:
        """A lying or absent content-length must not defeat the cap."""
        oversized = b"x" * (_MAX_MEDIA_BYTES + 1024)
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=oversized))
        async with httpx.AsyncClient(transport=transport) as http:
            assert await _download_bounded(http, "https://example.test/big.png") is None

    async def test_accepts_body_at_the_cap(self) -> None:
        at_limit = b"x" * _MAX_MEDIA_BYTES
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=at_limit))
        async with httpx.AsyncClient(transport=transport) as http:
            result = await _download_bounded(http, "https://example.test/exact.png")
        assert result is not None
        assert len(result[0]) == _MAX_MEDIA_BYTES


class TestAttachmentPathContainment:
    """The attachment filename comes from the API and was joined verbatim."""

    @pytest.mark.parametrize(
        "hostile_name",
        [
            "../../../../etc/cron.d/backdoor",
            "/etc/cron.d/backdoor",
            "..\\..\\Windows\\System32\\evil.dll",
            "....//....//escape.sh",
        ],
    )
    def test_hostile_filenames_stay_inside_the_output_directory(
        self, hostile_name: str, tmp_path: object
    ) -> None:
        from pathlib import Path

        base = Path(str(tmp_path))
        resolved = safe_join(base, "attachments", "abcd1234", hostile_name)
        assert base.resolve() in resolved.parents
