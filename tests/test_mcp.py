"""Tests for the MCP server tool registration."""

from __future__ import annotations

import json

from kahunas_client.mcp.server import _compact, _strip_empty, create_server


class TestMCPServerCreation:
    def test_create_server(self) -> None:
        server = create_server()
        assert server is not None
        assert server.name == "kahunas"

    def test_server_has_tools(self) -> None:
        server = create_server()
        # FastMCP 3.x exposes tools via list_tools / get_tool
        assert callable(server.list_tools)


class TestCompactSerialization:
    """Test JSON payload minimization for LLM context."""

    def test_strips_null_values(self) -> None:
        result = _strip_empty({"name": "test", "notes": None, "uuid": "abc"})
        assert result == {"name": "test", "uuid": "abc"}

    def test_strips_empty_strings(self) -> None:
        result = _strip_empty({"name": "test", "desc": ""})
        assert result == {"name": "test"}

    def test_strips_empty_lists(self) -> None:
        result = _strip_empty({"name": "test", "tags": [], "media": []})
        assert result == {"name": "test"}

    def test_strips_empty_dicts(self) -> None:
        result = _strip_empty({"name": "test", "data": {}})
        assert result == {"name": "test"}

    def test_keeps_non_empty_values(self) -> None:
        result = _strip_empty({"name": "test", "tags": ["a"], "count": 5})
        assert result == {"name": "test", "tags": ["a"], "count": 5}

    def test_keeps_false_boolean(self) -> None:
        result = _strip_empty({"active": False, "name": "test"})
        assert result == {"active": False, "name": "test"}

    def test_keeps_zero_number(self) -> None:
        result = _strip_empty({"count": 0, "name": "test"})
        assert result == {"count": 0, "name": "test"}

    def test_strips_pagination_internals(self) -> None:
        result = _strip_empty(
            {
                "total": 10,
                "showeachside": 5,
                "eitherside": 60,
                "num": 5,
                "data_range": [12, 24],
            }
        )
        assert result == {"total": 10}

    def test_recursive_stripping(self) -> None:
        result = _strip_empty(
            {
                "exercises": [
                    {"name": "Bench", "notes": None, "tags": []},
                    {"name": "Squat", "reps": "5"},
                ]
            }
        )
        assert result == {
            "exercises": [
                {"name": "Bench"},
                {"name": "Squat", "reps": "5"},
            ]
        }

    def test_compact_no_indent(self) -> None:
        """Verify _compact produces compact JSON without indentation."""
        data = {"name": "test", "value": 42}
        result = _compact(data)
        # No spaces after colons/commas
        assert " " not in result.replace("test", "x")
        parsed = json.loads(result)
        assert parsed == {"name": "test", "value": 42}

    def test_compact_with_pydantic_model(self) -> None:
        """Verify _compact handles Pydantic models."""
        from kahunas_client.models import MediaItem

        item = MediaItem(uuid="abc", file_url="http://example.com/img.jpg")
        result = _compact(item)
        parsed = json.loads(result)
        assert parsed["uuid"] == "abc"
        assert parsed["file_url"] == "http://example.com/img.jpg"
        # Null/empty fields should be stripped
        assert "parent_type" not in parsed
        assert "source" not in parsed

    def test_compact_with_list_of_models(self) -> None:
        """Verify _compact handles list of Pydantic models."""
        from kahunas_client.models import MediaItem

        items = [
            MediaItem(uuid="a", file_url="http://a.jpg"),
            MediaItem(uuid="b", file_url="http://b.jpg"),
        ]
        result = _compact(items)
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["uuid"] == "a"
