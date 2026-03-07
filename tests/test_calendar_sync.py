"""Tests for the calendar sync module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kahunas_client.calendar_sync import (
    CalendarConfig,
    build_removal_summary,
    embed_kahunas_uuid,
    extract_kahunas_uuid,
    filter_appointments_by_range,
    format_appointment_title,
    format_for_google_calendar,
    generate_ics,
    parse_time_range,
)

# ── CalendarConfig Tests ──


class TestCalendarConfig:
    def test_default_values(self) -> None:
        cfg = CalendarConfig()
        assert cfg.prefix == "Workout"
        assert cfg.default_gym == ""
        assert cfg.gym_list == []
        assert cfg.default_duration_minutes == 60

    def test_custom_values(self) -> None:
        cfg = CalendarConfig(
            prefix="PT Session",
            default_gym="Iron Paradise",
            gym_list=["Iron Paradise", "Home Gym", "Park"],
            default_duration_minutes=45,
        )
        assert cfg.prefix == "PT Session"
        assert cfg.default_gym == "Iron Paradise"
        assert len(cfg.gym_list) == 3
        assert cfg.default_duration_minutes == 45

    def test_is_configured_default(self) -> None:
        cfg = CalendarConfig()
        assert cfg.is_configured() is True  # has default prefix

    def test_is_configured_empty_prefix(self) -> None:
        cfg = CalendarConfig(prefix="")
        assert cfg.is_configured() is False


# ── Time Range Parsing ──


class TestParseTimeRange:
    def test_today(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("today", ref)
        assert start == ref
        assert end.hour == 23
        assert end.minute == 59
        assert end.day == 15

    def test_next_24h(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("next_24h", ref)
        assert (end - start) == timedelta(hours=24)

    def test_next_48h(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("next_48h", ref)
        assert (end - start) == timedelta(hours=48)

    def test_next_7d(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("next_7d", ref)
        assert (end - start) == timedelta(days=7)

    def test_next_week_alias(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("next_week", ref)
        assert (end - start) == timedelta(days=7)

    def test_next_month(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("next_month", ref)
        assert (end - start) == timedelta(days=30)

    def test_next_3m(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("next_3m", ref)
        assert (end - start) == timedelta(days=90)

    def test_next_6m(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("next_6m", ref)
        assert (end - start) == timedelta(days=180)

    def test_next_12m(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("next_12m", ref)
        assert (end - start) == timedelta(days=365)

    def test_next_year_alias(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("next_year", ref)
        assert (end - start) == timedelta(days=365)

    def test_case_insensitive(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("Next_7D", ref)
        assert (end - start) == timedelta(days=7)

    def test_with_spaces(self) -> None:
        ref = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        start, end = parse_time_range("next 7d", ref)
        assert (end - start) == timedelta(days=7)

    def test_unknown_range_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown time range"):
            parse_time_range("next_100_years")


# ── Appointment Filtering ──


class TestFilterAppointments:
    def test_filters_within_range(self) -> None:
        now = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        appointments = [
            {"start_time": "2024-03-15T12:00:00Z", "title": "In range"},
            {"start_time": "2024-03-20T12:00:00Z", "title": "Out of range"},
            {"start_time": "2024-03-16T09:00:00Z", "title": "Also in range"},
        ]
        end = now + timedelta(days=2)
        result = filter_appointments_by_range(appointments, now, end)
        assert len(result) == 2
        assert result[0]["title"] == "In range"
        assert result[1]["title"] == "Also in range"

    def test_handles_empty_list(self) -> None:
        now = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        result = filter_appointments_by_range([], now, now + timedelta(days=7))
        assert result == []

    def test_handles_missing_date_field(self) -> None:
        now = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        appointments = [{"title": "No date"}, {"start_time": "", "title": "Empty date"}]
        result = filter_appointments_by_range(appointments, now, now + timedelta(days=7))
        assert result == []

    def test_custom_date_field(self) -> None:
        now = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        appointments = [
            {"start": "2024-03-15T12:00:00Z", "title": "Custom field"},
        ]
        end = now + timedelta(days=2)
        result = filter_appointments_by_range(appointments, now, end, date_field="start")
        assert len(result) == 1

    def test_handles_invalid_date(self) -> None:
        now = datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)
        appointments = [{"start_time": "not-a-date", "title": "Bad date"}]
        result = filter_appointments_by_range(appointments, now, now + timedelta(days=7))
        assert result == []


# ── Title Formatting ──


class TestFormatAppointmentTitle:
    def test_default_prefix(self) -> None:
        title = format_appointment_title("John Doe")
        assert title == "Workout: John Doe"

    def test_custom_prefix(self) -> None:
        title = format_appointment_title("Jane Smith", prefix="PT Session")
        assert title == "PT Session: Jane Smith"

    def test_with_datetime_string(self) -> None:
        title = format_appointment_title("John Doe", start_time="2024-03-15T10:00:00Z")
        assert "Workout: John Doe on" in title
        assert "Fri" in title  # 2024-03-15 is a Friday
        assert "10:00" in title

    def test_with_datetime_object(self) -> None:
        dt = datetime(2024, 3, 15, 14, 30, tzinfo=UTC)
        title = format_appointment_title("Jane", start_time=dt)
        assert "Workout: Jane on" in title
        assert "14:30" in title

    def test_with_invalid_datetime_string(self) -> None:
        title = format_appointment_title("John", start_time="not-a-date")
        assert title == "Workout: John"  # Falls back to no-time format

    def test_empty_prefix(self) -> None:
        title = format_appointment_title("John Doe", prefix="")
        assert title == ": John Doe"


# ── UUID Embedding / Extraction ──


class TestKahunasUuidTracking:
    def test_embed_uuid_empty_description(self) -> None:
        result = embed_kahunas_uuid("", "abc-123")
        assert result == "[kahunas:abc-123]"

    def test_embed_uuid_with_existing_description(self) -> None:
        result = embed_kahunas_uuid("Session notes here", "abc-123")
        assert "Session notes here" in result
        assert "[kahunas:abc-123]" in result
        assert "\n\n" in result

    def test_embed_uuid_no_duplicate(self) -> None:
        desc = "Notes\n\n[kahunas:abc-123]"
        result = embed_kahunas_uuid(desc, "abc-123")
        assert result == desc  # No change

    def test_extract_uuid(self) -> None:
        desc = "Session notes\n\n[kahunas:abc-123-def]"
        result = extract_kahunas_uuid(desc)
        assert result == "abc-123-def"

    def test_extract_uuid_only_tag(self) -> None:
        result = extract_kahunas_uuid("[kahunas:uuid-here]")
        assert result == "uuid-here"

    def test_extract_uuid_not_found(self) -> None:
        result = extract_kahunas_uuid("No UUID here")
        assert result is None

    def test_extract_uuid_empty_string(self) -> None:
        result = extract_kahunas_uuid("")
        assert result is None

    def test_extract_uuid_none(self) -> None:
        result = extract_kahunas_uuid("")
        assert result is None

    def test_roundtrip_embed_extract(self) -> None:
        original_uuid = "be4be785-001c-4795-8088-7ca0a4e23b64"
        desc = embed_kahunas_uuid("Workout session", original_uuid)
        extracted = extract_kahunas_uuid(desc)
        assert extracted == original_uuid


# ── iCal (.ics) Generation ──


class TestGenerateIcs:
    def test_generates_valid_ical(self) -> None:
        appointments = [
            {
                "uuid": "appt-001",
                "client_name": "John Doe",
                "start_time": "2024-03-15T10:00:00Z",
                "end_time": "2024-03-15T11:00:00Z",
                "notes": "Leg day",
            }
        ]
        ics = generate_ics(appointments)
        assert "BEGIN:VCALENDAR" in ics
        assert "END:VCALENDAR" in ics
        assert "BEGIN:VEVENT" in ics
        assert "END:VEVENT" in ics
        assert "VERSION:2.0" in ics

    def test_contains_appointment_details(self) -> None:
        appointments = [
            {
                "uuid": "appt-001",
                "client_name": "John Doe",
                "start_time": "2024-03-15T10:00:00Z",
                "end_time": "2024-03-15T11:00:00Z",
            }
        ]
        ics = generate_ics(appointments)
        assert "Workout: John Doe" in ics
        assert "kahunas-appt-001@kahunas.io" in ics
        assert "X-KAHUNAS-UUID:appt-001" in ics

    def test_embeds_uuid_in_description(self) -> None:
        appointments = [
            {
                "uuid": "appt-002",
                "client_name": "Jane Smith",
                "start_time": "2024-03-16T14:00:00Z",
                "notes": "Upper body",
            }
        ]
        ics = generate_ics(appointments)
        assert "[kahunas:appt-002]" in ics

    def test_custom_prefix(self) -> None:
        cfg = CalendarConfig(prefix="PT Session")
        appointments = [
            {
                "uuid": "appt-003",
                "client_name": "Alice",
                "start_time": "2024-03-17T09:00:00Z",
            }
        ]
        ics = generate_ics(appointments, cfg)
        assert "PT Session: Alice" in ics

    def test_default_duration_when_no_end(self) -> None:
        appointments = [
            {
                "uuid": "appt-004",
                "client_name": "Bob",
                "start_time": "2024-03-15T10:00:00Z",
                # No end_time
            }
        ]
        ics = generate_ics(appointments)
        # Should use default 60 min duration
        assert "DTSTART:20240315T100000Z" in ics
        assert "DTEND:20240315T110000Z" in ics

    def test_custom_duration(self) -> None:
        cfg = CalendarConfig(default_duration_minutes=45)
        appointments = [
            {
                "uuid": "appt-005",
                "client_name": "Carol",
                "start_time": "2024-03-15T10:00:00Z",
            }
        ]
        ics = generate_ics(appointments, cfg)
        assert "DTSTART:20240315T100000Z" in ics
        assert "DTEND:20240315T104500Z" in ics

    def test_location_from_appointment(self) -> None:
        appointments = [
            {
                "uuid": "appt-006",
                "client_name": "Dave",
                "start_time": "2024-03-15T10:00:00Z",
                "location": "Iron Paradise",
            }
        ]
        ics = generate_ics(appointments)
        assert "LOCATION:Iron Paradise" in ics

    def test_location_from_default_gym(self) -> None:
        cfg = CalendarConfig(default_gym="Gold's Gym")
        appointments = [
            {
                "uuid": "appt-007",
                "client_name": "Eve",
                "start_time": "2024-03-15T10:00:00Z",
            }
        ]
        ics = generate_ics(appointments, cfg)
        assert "Gold's Gym" in ics

    def test_empty_appointments_list(self) -> None:
        ics = generate_ics([])
        assert "BEGIN:VCALENDAR" in ics
        assert "END:VCALENDAR" in ics
        assert "BEGIN:VEVENT" not in ics

    def test_multiple_appointments(self) -> None:
        appointments = [
            {
                "uuid": f"appt-{i}",
                "client_name": f"Client {i}",
                "start_time": f"2024-03-{15 + i}T10:00:00Z",
            }
            for i in range(5)
        ]
        ics = generate_ics(appointments)
        assert ics.count("BEGIN:VEVENT") == 5
        assert ics.count("END:VEVENT") == 5

    def test_ical_escapes_special_chars(self) -> None:
        appointments = [
            {
                "uuid": "appt-esc",
                "client_name": "John, Jr.",
                "start_time": "2024-03-15T10:00:00Z",
                "notes": "Notes; with special, chars\nand newlines",
            }
        ]
        ics = generate_ics(appointments)
        # Commas and semicolons should be escaped
        assert "John\\, Jr." in ics
        assert "\\;" in ics
        assert "\\n" in ics


# ── Google Calendar Formatting ──


class TestFormatForGoogleCalendar:
    def test_basic_event_format(self) -> None:
        appointments = [
            {
                "uuid": "gcal-001",
                "client_name": "John Doe",
                "start_time": "2024-03-15T10:00:00+00:00",
                "end_time": "2024-03-15T11:00:00+00:00",
            }
        ]
        events = format_for_google_calendar(appointments)
        assert len(events) == 1
        event = events[0]
        assert event["summary"] == "Workout: John Doe"
        assert "dateTime" in event["start"]
        assert "dateTime" in event["end"]
        assert event["calendar_id"] == "primary"

    def test_extended_properties_contain_uuid(self) -> None:
        appointments = [
            {
                "uuid": "gcal-002",
                "client_name": "Jane",
                "start_time": "2024-03-15T10:00:00Z",
            }
        ]
        events = format_for_google_calendar(appointments)
        props = events[0]["extendedProperties"]["private"]
        assert props["kahunas_uuid"] == "gcal-002"
        assert props["kahunas_client"] == "Jane"

    def test_description_contains_uuid(self) -> None:
        appointments = [
            {
                "uuid": "gcal-003",
                "client_name": "Alice",
                "start_time": "2024-03-15T10:00:00Z",
                "notes": "Chest and triceps",
            }
        ]
        events = format_for_google_calendar(appointments)
        desc = events[0]["description"]
        assert "[kahunas:gcal-003]" in desc
        assert "Chest and triceps" in desc

    def test_custom_calendar_id(self) -> None:
        appointments = [
            {
                "uuid": "gcal-004",
                "client_name": "Bob",
                "start_time": "2024-03-15T10:00:00Z",
            }
        ]
        events = format_for_google_calendar(appointments, calendar_id="work@example.com")
        assert events[0]["calendar_id"] == "work@example.com"

    def test_location_from_appointment(self) -> None:
        appointments = [
            {
                "uuid": "gcal-005",
                "client_name": "Carol",
                "start_time": "2024-03-15T10:00:00Z",
                "location": "Fitness First",
            }
        ]
        events = format_for_google_calendar(appointments)
        assert events[0]["location"] == "Fitness First"

    def test_location_from_default_gym(self) -> None:
        cfg = CalendarConfig(default_gym="The Gym")
        appointments = [
            {
                "uuid": "gcal-006",
                "client_name": "Dave",
                "start_time": "2024-03-15T10:00:00Z",
            }
        ]
        events = format_for_google_calendar(appointments, cfg)
        assert events[0]["location"] == "The Gym"

    def test_no_location_when_none(self) -> None:
        cfg = CalendarConfig(default_gym="")
        appointments = [
            {
                "uuid": "gcal-007",
                "client_name": "Eve",
                "start_time": "2024-03-15T10:00:00Z",
            }
        ]
        events = format_for_google_calendar(appointments, cfg)
        assert "location" not in events[0]

    def test_custom_prefix(self) -> None:
        cfg = CalendarConfig(prefix="Training")
        appointments = [
            {
                "uuid": "gcal-008",
                "client_name": "Frank",
                "start_time": "2024-03-15T10:00:00Z",
            }
        ]
        events = format_for_google_calendar(appointments, cfg)
        assert events[0]["summary"] == "Training: Frank"

    def test_multiple_events(self) -> None:
        appointments = [
            {
                "uuid": f"gcal-multi-{i}",
                "client_name": f"Client {i}",
                "start_time": f"2024-03-{15 + i}T10:00:00Z",
            }
            for i in range(3)
        ]
        events = format_for_google_calendar(appointments)
        assert len(events) == 3


# ── Client Removal Summary ──


class TestBuildRemovalSummary:
    def test_full_removal(self) -> None:
        summary = build_removal_summary(
            client_name="John Doe",
            client_uuid="uuid-123",
            appointments_found=5,
            appointments_removed=5,
            kahunas_removed=True,
        )
        assert summary["client"] == "John Doe"
        assert summary["uuid"] == "uuid-123"
        assert summary["kahunas_removed"] is True
        assert summary["calendar_appointments_found"] == 5
        assert summary["calendar_appointments_removed"] == 5

    def test_calendar_only_removal(self) -> None:
        summary = build_removal_summary(
            client_name="Jane",
            client_uuid="uuid-456",
            appointments_found=3,
            appointments_removed=3,
            kahunas_removed=False,
        )
        assert summary["kahunas_removed"] is False
        assert summary["calendar_appointments_removed"] == 3

    def test_no_appointments(self) -> None:
        summary = build_removal_summary(
            client_name="Bob",
            client_uuid="uuid-789",
            appointments_found=0,
            appointments_removed=0,
            kahunas_removed=True,
        )
        assert summary["calendar_appointments_found"] == 0


# ── Datetime Parsing ──


class TestDatetimeParsing:
    """Test the internal _parse_datetime via public functions that use it."""

    def test_iso8601_with_z(self) -> None:
        title = format_appointment_title("John", start_time="2024-03-15T10:00:00Z")
        assert "10:00" in title

    def test_iso8601_with_offset(self) -> None:
        title = format_appointment_title("John", start_time="2024-03-15T10:00:00+00:00")
        assert "10:00" in title

    def test_date_and_time(self) -> None:
        title = format_appointment_title("John", start_time="2024-03-15 14:30:00")
        assert "14:30" in title

    def test_date_and_time_no_seconds(self) -> None:
        title = format_appointment_title("John", start_time="2024-03-15 14:30")
        assert "14:30" in title

    def test_date_only(self) -> None:
        title = format_appointment_title("John", start_time="2024-03-15")
        assert "Fri" in title  # 2024-03-15 is Friday

    def test_uk_format(self) -> None:
        title = format_appointment_title("John", start_time="15/03/2024 10:00")
        assert "10:00" in title


# ── Config Integration ──


class TestKahunasConfigCalendar:
    def test_default_calendar_config(self) -> None:
        """Verify KahunasConfig has calendar fields with defaults."""
        from kahunas_client.config import KahunasConfig

        cfg = KahunasConfig()
        assert cfg.calendar_prefix == "Workout"
        assert cfg.default_gym == ""
        assert cfg.gym_list == ""
        assert cfg.calendar_default_duration == 60

    def test_custom_calendar_config(self) -> None:
        from kahunas_client.config import KahunasConfig

        cfg = KahunasConfig(
            calendar_prefix="PT",
            default_gym="Iron Paradise",
            gym_list="Iron Paradise,Home Gym,Park",
            calendar_default_duration=45,
        )
        assert cfg.calendar_prefix == "PT"
        assert cfg.default_gym == "Iron Paradise"
        assert cfg.gym_list == "Iron Paradise,Home Gym,Park"
        assert cfg.calendar_default_duration == 45

    def test_gym_list_parsing(self) -> None:
        from kahunas_client.config import KahunasConfig

        cfg = KahunasConfig(gym_list="Gym A, Gym B, Home")
        gyms = [g.strip() for g in cfg.gym_list.split(",") if g.strip()]
        assert len(gyms) == 3
        assert gyms[0] == "Gym A"
        assert gyms[1] == "Gym B"
        assert gyms[2] == "Home"
