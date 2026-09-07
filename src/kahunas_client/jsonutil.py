"""Defensive accessors for loosely typed JSON payloads.

The Kahunas API returns the same logical field under several different
shapes depending on the endpoint: a bare array, an object wrapping an
array, a null, or an error string. Callers therefore have to narrow a
decoded payload before using it.

These helpers centralise that narrowing. Each one returns a safe empty
default instead of raising, so a caller gets a statically known type
without scattering ``isinstance`` chains through request handling code.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "as_dict",
    "as_dict_list",
    "as_float",
    "as_list",
    "as_str",
    "first_list",
]


def as_dict(value: Any) -> dict[str, Any]:
    """Return ``value`` when it is a JSON object, otherwise an empty dict."""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    """Return ``value`` when it is a JSON array, otherwise an empty list."""
    return value if isinstance(value, list) else []


def as_dict_list(value: Any) -> list[dict[str, Any]]:
    """Return ``value`` as a list of JSON objects, dropping non object items."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def as_str(value: Any, default: str = "") -> str:
    """Return ``value`` when it is a string, otherwise ``default``.

    Numbers and booleans are deliberately not coerced, because the API
    uses them for genuinely different fields and a silent coercion would
    hide a schema change rather than surface it.
    """
    return value if isinstance(value, str) else default


def as_float(value: Any, default: float | None = None) -> float | None:
    """Return ``value`` as a float, or ``default`` when it is not numeric.

    Accepts ints, floats and numeric strings, since the API returns
    measurements inconsistently as either. Booleans are rejected because
    ``bool`` is a subclass of ``int`` and coercing them would turn a flag
    into a measurement.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def first_list(source: Any, *keys: str) -> list[Any]:
    """Return the first of ``keys`` in ``source`` that holds a JSON array.

    ``source`` may be a JSON object to look the keys up in, or a bare
    array, which is returned unchanged. When a key holds a nested object,
    that object is searched for the same keys, which matches how the API
    wraps collections one level deep on some endpoints.

    Returns an empty list when ``source`` is neither an object nor an
    array, or when no key resolves to an array. This is deliberately
    stricter than ``dict.get`` chaining: a key that exists but holds
    ``null`` or a string yields an empty list rather than propagating a
    value the caller cannot iterate.
    """
    if isinstance(source, list):
        return source
    if not isinstance(source, dict):
        return []
    for key in keys:
        found = source.get(key)
        if isinstance(found, list):
            return found
        if isinstance(found, dict):
            nested = first_list(found, *keys)
            if nested:
                return nested
    return []
