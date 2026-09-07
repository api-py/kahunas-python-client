"""Tests for the defensive JSON narrowing helpers."""

from __future__ import annotations

import pytest

from kahunas_client.jsonutil import (
    as_dict,
    as_dict_list,
    as_float,
    as_list,
    as_str,
    first_list,
)


class TestAsDict:
    """Narrowing an arbitrary payload to a JSON object."""

    def test_returns_dict_unchanged(self) -> None:
        assert as_dict({"a": 1}) == {"a": 1}

    @pytest.mark.parametrize("value", [None, [], "text", 3, 4.5, True])
    def test_returns_empty_dict_for_non_objects(self, value: object) -> None:
        assert as_dict(value) == {}


class TestAsList:
    """Narrowing an arbitrary payload to a JSON array."""

    def test_returns_list_unchanged(self) -> None:
        assert as_list([1, 2]) == [1, 2]

    @pytest.mark.parametrize("value", [None, {}, "text", 3])
    def test_returns_empty_list_for_non_arrays(self, value: object) -> None:
        assert as_list(value) == []


class TestAsDictList:
    """Narrowing to a list of JSON objects."""

    def test_keeps_only_objects(self) -> None:
        assert as_dict_list([{"a": 1}, "skip", None, {"b": 2}]) == [{"a": 1}, {"b": 2}]

    def test_returns_empty_for_non_array(self) -> None:
        assert as_dict_list({"a": 1}) == []


class TestAsStr:
    """Narrowing to a string without silent coercion."""

    def test_returns_string_unchanged(self) -> None:
        assert as_str("hello") == "hello"

    def test_uses_default_for_non_strings(self) -> None:
        assert as_str(None) == ""
        assert as_str(12, default="fallback") == "fallback"

    def test_does_not_coerce_numbers(self) -> None:
        """A number must not become its string form, which would hide schema drift."""
        assert as_str(42) == ""


class TestAsFloat:
    """Numeric narrowing for inconsistently typed measurements."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(1, 1.0), (2.5, 2.5), ("3.5", 3.5), ("  4 ", 4.0)],
    )
    def test_parses_numeric_values(self, value: object, expected: float) -> None:
        assert as_float(value) == expected

    @pytest.mark.parametrize("value", [None, "abc", "", {}, []])
    def test_returns_default_for_non_numeric(self, value: object) -> None:
        assert as_float(value) is None
        assert as_float(value, default=0.0) == 0.0

    def test_rejects_booleans(self) -> None:
        """bool subclasses int, so a flag must not be read as a measurement."""
        assert as_float(True) is None
        assert as_float(False) is None


class TestFirstList:
    """Locating a collection across the shapes the API returns."""

    def test_returns_bare_array_unchanged(self) -> None:
        assert first_list([1, 2], "data") == [1, 2]

    def test_finds_first_matching_key(self) -> None:
        source = {"check_ins": [1], "checkins": [2]}
        assert first_list(source, "checkins", "check_ins") == [2]

    def test_falls_through_to_later_key(self) -> None:
        assert first_list({"data": [3]}, "checkins", "data") == [3]

    def test_searches_one_level_of_wrapping(self) -> None:
        source = {"data": {"checkins": [4]}}
        assert first_list(source, "checkins", "data") == [4]

    def test_skips_key_holding_null(self) -> None:
        """A present but null key must not shadow a later key that holds data."""
        assert first_list({"checkins": None, "data": [5]}, "checkins", "data") == [5]

    def test_skips_key_holding_a_string(self) -> None:
        """An error string under the expected key yields no rows, not a crash."""
        assert first_list({"checkins": "no records", "data": [6]}, "checkins", "data") == [6]

    @pytest.mark.parametrize("source", [None, "text", 7])
    def test_returns_empty_for_unusable_source(self, source: object) -> None:
        assert first_list(source, "data") == []

    def test_returns_empty_when_no_key_matches(self) -> None:
        assert first_list({"other": [1]}, "data", "checkins") == []
