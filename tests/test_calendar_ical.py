"""RFC 5545 conformance and injection tests for generated iCal files.

Appointment fields come from the Kahunas API. These are regression tests
for an incomplete text escape, unescaped identifier properties, missing
line folding, and a naive datetime being labelled UTC without conversion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from kahunas_client.calendar_sync import (
    _dt_to_ical,
    _fold_line,
    _ical_escape,
    _ical_identifier,
    generate_ics,
)

_MAX_LINE_OCTETS = 75


def _content_lines(ics: str) -> list[str]:
    """Unfold an iCal document back into logical content lines."""
    logical: list[str] = []
    for raw in ics.split("\r\n"):
        if raw.startswith(" ") and logical:
            logical[-1] += raw[1:]
        else:
            logical.append(raw)
    return logical


class TestIcalEscape:
    """TEXT value escaping per RFC 5545 section 3.3.11."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("a;b", "a\\;b"),
            ("a,b", "a\\,b"),
            ("a\\b", "a\\\\b"),
            ("a\nb", "a\\nb"),
        ],
    )
    def test_escapes_special_characters(self, raw: str, expected: str) -> None:
        assert _ical_escape(raw) == expected

    def test_escapes_carriage_return(self) -> None:
        """An unescaped CR terminates the content line and injects properties."""
        assert "\r" not in _ical_escape("a\rb")
        assert _ical_escape("a\rb") == "a\\nb"

    def test_collapses_crlf_to_one_newline(self) -> None:
        assert _ical_escape("a\r\nb") == "a\\nb"

    def test_backslash_is_escaped_before_other_characters(self) -> None:
        """Escaping order must not double process an inserted backslash."""
        assert _ical_escape("a\\;b") == "a\\\\\\;b"


class TestIcalIdentifier:
    """UID and X- properties are not TEXT typed and cannot be escaped."""

    @pytest.mark.parametrize(
        "hostile",
        [
            "abc\r\nSUMMARY:Injected",
            "abc\nDTSTART:20200101T000000Z",
            "abc\rX-EVIL:1",
        ],
    )
    def test_strips_line_breaks(self, hostile: str) -> None:
        cleaned = _ical_identifier(hostile)
        assert "\r" not in cleaned
        assert "\n" not in cleaned

    def test_keeps_ordinary_uuid_characters(self) -> None:
        value = "550e8400-e29b-41d4-a716-446655440000"
        assert _ical_identifier(value) == value

    def test_truncates_overlong_identifiers(self) -> None:
        assert len(_ical_identifier("a" * 500)) == 200


class TestLineFolding:
    """RFC 5545 section 3.1 caps a content line at 75 octets."""

    def test_short_line_is_untouched(self) -> None:
        assert _fold_line("SUMMARY:short") == "SUMMARY:short"

    def test_long_line_is_folded(self) -> None:
        folded = _fold_line("SUMMARY:" + "x" * 200)
        assert "\r\n " in folded
        for segment in folded.split("\r\n"):
            assert len(segment.encode("utf-8")) <= _MAX_LINE_OCTETS

    def test_folding_is_reversible(self) -> None:
        original = "DESCRIPTION:" + "y" * 300
        assert _fold_line(original).replace("\r\n ", "") == original

    def test_multibyte_characters_are_never_split(self) -> None:
        """Folding counts octets, so a 3 byte character must stay intact."""
        folded = _fold_line("SUMMARY:" + "中" * 60)
        for segment in folded.split("\r\n"):
            segment.encode("utf-8").decode("utf-8")
            assert len(segment.encode("utf-8")) <= _MAX_LINE_OCTETS


class TestDatetimeStamping:
    """UTC conversion before stamping the Z suffix."""

    def test_aware_datetime_is_converted(self) -> None:
        aware = datetime(2024, 3, 15, 12, 0, tzinfo=timezone(timedelta(hours=5)))
        assert _dt_to_ical(aware) == "20240315T070000Z"

    def test_utc_datetime_is_unchanged(self) -> None:
        assert _dt_to_ical(datetime(2024, 3, 15, 12, 0, tzinfo=UTC)) == "20240315T120000Z"

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        """Previously the Z was appended without converting, shifting the time."""
        assert _dt_to_ical(datetime(2024, 3, 15, 12, 0)) == "20240315T120000Z"


class TestGeneratedDocument:
    """End to end properties of the produced file."""

    def _appointment(self, **overrides: object) -> dict[str, object]:
        appointment = {
            "uuid": "550e8400-e29b-41d4-a716-446655440000",
            "client_name": "Jane Smith",
            "start_time": "2024-03-15T10:00:00Z",
            "notes": "Leg day",
            "location": "PureGym London",
        }
        appointment.update(overrides)
        return appointment

    def test_every_line_is_within_the_octet_limit(self) -> None:
        ics = generate_ics([self._appointment(notes="n" * 400)])
        for line in ics.split("\r\n"):
            assert len(line.encode("utf-8")) <= _MAX_LINE_OCTETS

    def test_injected_uuid_cannot_add_properties(self) -> None:
        hostile = "abc\r\nSUMMARY:Injected\r\nX-EVIL:1"
        ics = generate_ics([self._appointment(uuid=hostile)])
        assert "SUMMARY:Injected" not in _content_lines(ics)
        assert "X-EVIL:1" not in _content_lines(ics)

    def test_injected_notes_cannot_add_properties(self) -> None:
        hostile = "note\r\nDTSTART:19700101T000000Z\r\nSUMMARY:Injected"
        ics = generate_ics([self._appointment(notes=hostile)])
        assert "SUMMARY:Injected" not in _content_lines(ics)
        assert sum(1 for line in _content_lines(ics) if line.startswith("DTSTART:")) == 1

    def test_injected_client_name_cannot_add_properties(self) -> None:
        hostile = "Jane\r\nSUMMARY:Injected"
        ics = generate_ics([self._appointment(client_name=hostile)])
        assert "SUMMARY:Injected" not in _content_lines(ics)

    def test_structure_remains_balanced_under_injection(self) -> None:
        ics = generate_ics([self._appointment(uuid="a\r\nEND:VEVENT\r\nBEGIN:VEVENT")])
        lines = _content_lines(ics)
        assert lines.count("BEGIN:VEVENT") == 1
        assert lines.count("END:VEVENT") == 1

    def test_ordinary_appointment_still_renders(self) -> None:
        ics = generate_ics([self._appointment()])
        lines = _content_lines(ics)
        assert "BEGIN:VCALENDAR" in lines
        assert "END:VCALENDAR" in lines
        assert any(line.startswith("SUMMARY:") and "Jane Smith" in line for line in lines)
        assert any(line.startswith("LOCATION:") for line in lines)
