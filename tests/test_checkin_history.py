"""Tests for check-in history parsing, formatting, and appointment overview."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kahunas_client.checkin_history import (
    CHECKIN_FIELDS,
    _calculate_trends,
    _filter_events_by_time,
    _parse_dt,
    _parse_numeric,
    _summarise_events,
    build_appointment_overview,
    build_client_appointment_counts,
    format_checkin_summary,
    normalise_field_name,
    parse_appointment_time_range,
    parse_checkin_record,
)

# ── Field Name Normalisation ──


class TestNormaliseFieldName:
    """Test normalise_field_name with various API formats."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("weight", "weight"),
            ("Weight", "weight"),
            ("Weight - Lbs", "weight"),
            ("Weight - Kg", "weight"),
            ("body_weight", "weight"),
            ("waist", "waist"),
            ("Waist Measurement - Inches", "waist"),
            ("waist_measurement", "waist"),
            ("hips", "hips"),
            ("Hip Measurement - Inches", "hips"),
            ("hip_measurement", "hips"),
            ("hip", "hips"),
            ("biceps", "biceps"),
            ("Biceps - Inches", "biceps"),
            ("bicep", "biceps"),
            ("bicep_measurement", "biceps"),
            ("thighs", "thighs"),
            ("Thighs - Inches", "thighs"),
            ("thigh", "thighs"),
            ("thigh_measurement", "thighs"),
            ("sleep_quality", "sleep_quality"),
            ("Sleep Quality? (1-10)", "sleep_quality"),
            ("sleep", "sleep_quality"),
            ("sleep_quality_1_10", "sleep_quality"),
            ("nutrition_adherence", "nutrition_adherence"),
            ("How closely did you stick to your nutritional plan? (1-10)", "nutrition_adherence"),
            ("nutritional_plan", "nutrition_adherence"),
            ("stick_to_nutritional_plan", "nutrition_adherence"),
            ("water_intake", "water_intake"),
            ("Average Water Intake per Day? (liters)", "water_intake"),
            ("average_water_intake", "water_intake"),
            ("water", "water_intake"),
            ("workout_rating", "workout_rating"),
            ("Rate Your Workouts (1-10)", "workout_rating"),
            ("workout", "workout_rating"),
            ("rate_your_workouts", "workout_rating"),
            ("stress_level", "stress_level"),
            ("Average Stress Level This Week (1-10)", "stress_level"),
            ("stress", "stress_level"),
            ("average_stress_level", "stress_level"),
            ("energy_level", "energy_level"),
            ("Average Daily Energy Levels (1-10)", "energy_level"),
            ("energy", "energy_level"),
            ("daily_energy", "energy_level"),
            ("energy_levels", "energy_level"),
            ("mood_wellbeing", "mood_wellbeing"),
            ("Mood and Overall Well-being (1-10)", "mood_wellbeing"),
            ("mood", "mood_wellbeing"),
            ("wellbeing", "mood_wellbeing"),
            ("overall_wellbeing", "mood_wellbeing"),
        ],
        ids=lambda x: x.replace(" ", "_")[:40],
    )
    def test_normalise(self, raw: str, expected: str) -> None:
        assert normalise_field_name(raw) == expected

    def test_unknown_field_passthrough(self) -> None:
        """Unknown fields are returned as cleaned snake_case."""
        result = normalise_field_name("Some Custom Field")
        assert result == "some_custom_field"

    def test_whitespace_handling(self) -> None:
        assert normalise_field_name("  weight  ") == "weight"

    def test_empty_string(self) -> None:
        result = normalise_field_name("")
        assert isinstance(result, str)


# ── Check-in Field Definitions ──


_EXPECTED_FIELDS = [
    ("weight", "Weight", "body", 1),
    ("waist", "Waist", "body", 2),
    ("hips", "Hips", "body", 3),
    ("biceps", "Biceps", "body", 4),
    ("thighs", "Thighs", "body", 5),
    ("sleep_quality", "Sleep (1-10)", "lifestyle", 6),
    ("nutrition_adherence", "Nutrition Adherence (1-10)", "lifestyle", 7),
    ("water_intake", "Water Intake", "lifestyle", 8),
    ("workout_rating", "Workout Rating (1-10)", "lifestyle", 9),
    ("stress_level", "Stress Level (1-10)", "lifestyle", 10),
    ("energy_level", "Energy Level (1-10)", "lifestyle", 11),
    ("mood_wellbeing", "Mood & Wellbeing (1-10)", "lifestyle", 12),
]


class TestCheckinFieldDefinitions:
    """Ensure all expected check-in fields are defined."""

    def test_all_fields_present(self) -> None:
        for name, _label, _cat, _order in _EXPECTED_FIELDS:
            assert name in CHECKIN_FIELDS, f"Missing field: {name}"

    @pytest.mark.parametrize(
        ("name", "label", "category", "order"),
        _EXPECTED_FIELDS,
        ids=[f[0] for f in _EXPECTED_FIELDS],
    )
    def test_field_metadata(self, name: str, label: str, category: str, order: int) -> None:
        field = CHECKIN_FIELDS[name]
        assert field["label"] == label
        assert field["category"] == category
        assert field["order"] == order

    def test_field_count(self) -> None:
        assert len(CHECKIN_FIELDS) == 12


# ── Parse Checkin Record ──


# Sample check-in data matching the Kahunas dashboard format
_SAMPLE_CHECKIN_FLAT = {
    "uuid": "ci-001",
    "check_in_number": 4,
    "submitted_at": "2026-02-24",
    "check_in_day": "Tuesday",
    "weight": 207,
    "waist": 30.5,
    "hips": 38.5,
    "biceps": 17.5,
    "thighs": 24.5,
    "sleep_quality": 8,
    "nutrition_adherence": 9,
    "water_intake": 3.5,
    "workout_rating": 9,
    "stress_level": 6,
    "energy_level": 8,
    "mood_wellbeing": 8,
}

_SAMPLE_CHECKIN_NESTED = {
    "uuid": "ci-002",
    "check_in_number": 3,
    "submitted_at": "2026-02-17",
    "check_in_day": "Tuesday",
    "data": {
        "Weight - Lbs": 208,
        "Waist Measurement - Inches": 37,
        "Hip Measurement - Inches": 39,
        "Biceps - Inches": 17.8,
        "Thighs - Inches": 25,
        "Sleep Quality? (1-10)": 8,
        "How closely did you stick to your nutritional plan? (1-10)": 8,
        "Average Water Intake per Day? (liters)": 3.5,
        "Rate Your Workouts (1-10)": 8,
        "Average Stress Level This Week (1-10)": 7,
        "Average Daily Energy Levels (1-10)": 7,
        "Mood and Overall Well-being (1-10)": 7,
    },
}

_SAMPLE_CHECKIN_ARRAY = {
    "uuid": "ci-003",
    "check_in_number": 2,
    "date": "2026-02-10",
    "day": "Tuesday",
    "data": [
        {"name": "Weight", "value": 209},
        {"name": "Waist", "value": 31.5},
        {"name": "Hips", "value": 39.5},
        {"name": "Biceps", "value": 18},
        {"name": "Thighs", "value": 25.5},
        {"name": "Sleep Quality? (1-10)", "value": 7},
        {"name": "nutrition_adherence", "value": 9},
        {"name": "water_intake", "value": 3.2},
        {"name": "workout_rating", "value": 8},
        {"name": "stress_level", "value": 7},
        {"name": "energy_level", "value": 8},
        {"name": "mood_wellbeing", "value": 8},
    ],
}


class TestParseCheckinRecord:
    """Test parsing raw check-in records into structured dicts."""

    def test_parse_flat_record(self) -> None:
        record = parse_checkin_record(_SAMPLE_CHECKIN_FLAT)
        assert record["number"] == 4
        assert record["date"] == "2026-02-24"
        assert record["uuid"] == "ci-001"
        assert record["day"] == "Tuesday"
        assert record["fields"]["weight"] == 207.0
        assert record["fields"]["waist"] == 30.5
        assert record["fields"]["hips"] == 38.5
        assert record["fields"]["biceps"] == 17.5
        assert record["fields"]["thighs"] == 24.5
        assert record["fields"]["sleep_quality"] == 8.0
        assert record["fields"]["nutrition_adherence"] == 9.0
        assert record["fields"]["water_intake"] == 3.5
        assert record["fields"]["workout_rating"] == 9.0
        assert record["fields"]["stress_level"] == 6.0
        assert record["fields"]["energy_level"] == 8.0
        assert record["fields"]["mood_wellbeing"] == 8.0

    def test_parse_nested_data_record(self) -> None:
        record = parse_checkin_record(_SAMPLE_CHECKIN_NESTED)
        assert record["number"] == 3
        assert record["date"] == "2026-02-17"
        assert record["fields"]["weight"] == 208.0
        assert record["fields"]["waist"] == 37.0
        assert record["fields"]["hips"] == 39.0
        assert record["fields"]["biceps"] == 17.8
        assert record["fields"]["sleep_quality"] == 8.0
        assert record["fields"]["nutrition_adherence"] == 8.0
        assert record["fields"]["water_intake"] == 3.5

    def test_parse_array_data_record(self) -> None:
        record = parse_checkin_record(_SAMPLE_CHECKIN_ARRAY)
        assert record["number"] == 2
        assert record["date"] == "2026-02-10"
        assert record["fields"]["weight"] == 209.0
        assert record["fields"]["waist"] == 31.5
        assert record["fields"]["hips"] == 39.5
        assert record["fields"]["biceps"] == 18.0
        assert record["fields"]["thighs"] == 25.5
        assert record["fields"]["sleep_quality"] == 7.0

    def test_parse_with_notes(self) -> None:
        raw = {**_SAMPLE_CHECKIN_FLAT, "notes": "Feeling great this week!"}
        record = parse_checkin_record(raw)
        assert record["notes"] == "Feeling great this week!"

    def test_parse_with_photos(self) -> None:
        raw = {**_SAMPLE_CHECKIN_FLAT, "photos": ["url1.jpg", "url2.jpg"]}
        record = parse_checkin_record(raw)
        assert record["photo_count"] == 2

    def test_parse_empty_record(self) -> None:
        record = parse_checkin_record({})
        assert record["number"] == 0
        assert record["date"] == ""
        assert record["fields"] == {}

    def test_parse_preserves_uuid(self) -> None:
        raw = {"id": "alt-uuid-123", "weight": 80}
        record = parse_checkin_record(raw)
        assert record["uuid"] == "alt-uuid-123"

    def test_parse_handles_non_numeric_values(self) -> None:
        raw = {"weight": "not_a_number", "waist": 30}
        record = parse_checkin_record(raw)
        assert record["fields"].get("weight") is None
        assert record["fields"]["waist"] == 30.0


# ── Format Checkin Summary ──


class TestFormatCheckinSummary:
    """Test the full checkin summary formatting pipeline."""

    def test_summary_with_multiple_checkins(self) -> None:
        checkins = [_SAMPLE_CHECKIN_FLAT, _SAMPLE_CHECKIN_NESTED, _SAMPLE_CHECKIN_ARRAY]
        summary = format_checkin_summary(checkins, client_name="Bruce Wayne")

        assert summary["client_name"] == "Bruce Wayne"
        assert summary["total_checkins"] == 3
        assert len(summary["rows"]) == 3
        assert len(summary["columns"]) > 0
        # Most recent first
        assert summary["rows"][0]["number"] == 4
        assert summary["rows"][1]["number"] == 3
        assert summary["rows"][2]["number"] == 2

    def test_summary_includes_trends(self) -> None:
        checkins = [_SAMPLE_CHECKIN_FLAT, _SAMPLE_CHECKIN_NESTED]
        summary = format_checkin_summary(checkins)

        assert "trends" in summary
        trends = summary["trends"]
        # Weight went from 208 to 207 (check-in 3→4)
        assert trends["weight"]["change"] == -1.0
        assert trends["weight"]["direction"] == "down"

    def test_summary_date_range(self) -> None:
        checkins = [_SAMPLE_CHECKIN_FLAT, _SAMPLE_CHECKIN_NESTED, _SAMPLE_CHECKIN_ARRAY]
        summary = format_checkin_summary(checkins)

        assert summary["latest_checkin"] == "2026-02-24"
        assert summary["first_checkin"] == "2026-02-10"

    def test_summary_with_units_kg_cm(self) -> None:
        checkins = [_SAMPLE_CHECKIN_FLAT]
        summary = format_checkin_summary(checkins, weight_unit="kg", measurement_unit="cm")
        # Check column labels include units
        labels = {c["label"] for c in summary["columns"]}
        assert any("kg" in label for label in labels)
        assert any("cm" in label for label in labels)

    def test_summary_with_units_lbs_inches(self) -> None:
        checkins = [_SAMPLE_CHECKIN_FLAT]
        summary = format_checkin_summary(checkins, weight_unit="lbs", measurement_unit="inches")
        labels = {c["label"] for c in summary["columns"]}
        assert any("lbs" in label for label in labels)
        assert any("inches" in label for label in labels)

    def test_summary_empty_checkins(self) -> None:
        summary = format_checkin_summary([])
        assert summary["total_checkins"] == 0
        assert summary["rows"] == []

    def test_summary_single_checkin_no_trends(self) -> None:
        summary = format_checkin_summary([_SAMPLE_CHECKIN_FLAT])
        assert summary["total_checkins"] == 1
        # No trends with single data point
        assert summary.get("trends") is None

    def test_summary_columns_sorted_by_order(self) -> None:
        checkins = [_SAMPLE_CHECKIN_FLAT]
        summary = format_checkin_summary(checkins)
        column_keys = [c["key"] for c in summary["columns"]]
        # Weight should come before waist, which comes before sleep_quality
        if "weight" in column_keys and "waist" in column_keys:
            assert column_keys.index("weight") < column_keys.index("waist")
        if "waist" in column_keys and "sleep_quality" in column_keys:
            assert column_keys.index("waist") < column_keys.index("sleep_quality")

    def test_summary_row_includes_field_values(self) -> None:
        checkins = [_SAMPLE_CHECKIN_FLAT]
        summary = format_checkin_summary(checkins)
        row = summary["rows"][0]
        assert row["weight"] == 207.0
        assert row["waist"] == 30.5
        assert row["sleep_quality"] == 8.0


# ── Calculate Trends ──


class TestCalculateTrends:
    """Test trend calculation between check-ins."""

    def test_trends_weight_decrease(self) -> None:
        parsed = [
            {"fields": {"weight": 207.0, "waist": 30.5}},
            {"fields": {"weight": 208.0, "waist": 37.0}},
        ]
        trends = _calculate_trends(parsed)
        assert trends is not None
        assert trends["weight"]["change"] == -1.0
        assert trends["weight"]["direction"] == "down"

    def test_trends_weight_increase(self) -> None:
        parsed = [
            {"fields": {"weight": 210.0}},
            {"fields": {"weight": 208.0}},
        ]
        trends = _calculate_trends(parsed)
        assert trends["weight"]["change"] == 2.0
        assert trends["weight"]["direction"] == "up"

    def test_trends_no_change(self) -> None:
        parsed = [
            {"fields": {"weight": 207.0}},
            {"fields": {"weight": 207.0}},
        ]
        trends = _calculate_trends(parsed)
        assert trends["weight"]["change"] == 0.0
        assert trends["weight"]["direction"] == "same"

    def test_trends_single_record_returns_none(self) -> None:
        parsed = [{"fields": {"weight": 207.0}}]
        trends = _calculate_trends(parsed)
        assert trends is None

    def test_trends_empty_returns_none(self) -> None:
        assert _calculate_trends([]) is None

    def test_trends_handles_missing_fields(self) -> None:
        parsed = [
            {"fields": {"weight": 207.0, "waist": 30.5}},
            {"fields": {"weight": 208.0}},  # No waist
        ]
        trends = _calculate_trends(parsed)
        assert "weight" in trends
        assert "waist" not in trends

    def test_trends_handles_none_values(self) -> None:
        parsed = [
            {"fields": {"weight": 207.0, "waist": None}},
            {"fields": {"weight": 208.0, "waist": 30.0}},
        ]
        trends = _calculate_trends(parsed)
        assert "weight" in trends
        assert "waist" not in trends


# ── Parse Numeric ──


class TestParseNumeric:
    def test_integer(self) -> None:
        assert _parse_numeric(207) == 207.0

    def test_float(self) -> None:
        assert _parse_numeric(30.5) == 30.5

    def test_string_number(self) -> None:
        assert _parse_numeric("3.5") == 3.5

    def test_none(self) -> None:
        assert _parse_numeric(None) is None

    def test_invalid_string(self) -> None:
        assert _parse_numeric("not_a_number") is None

    def test_empty_string(self) -> None:
        assert _parse_numeric("") is None

    def test_boolean(self) -> None:
        assert _parse_numeric(True) == 1.0


# ── Parse Datetime ──


class TestParseDatetime:
    def test_iso_format(self) -> None:
        dt = _parse_dt("2026-02-24T10:00:00Z")
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.day == 24
        assert dt.tzinfo is not None

    def test_iso_with_offset(self) -> None:
        dt = _parse_dt("2026-02-24T10:00:00+00:00")
        assert dt.year == 2026

    def test_date_and_time(self) -> None:
        dt = _parse_dt("2026-02-24 10:00:00")
        assert dt.hour == 10

    def test_date_only(self) -> None:
        dt = _parse_dt("2026-02-24")
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.day == 24

    def test_uk_format(self) -> None:
        dt = _parse_dt("24/02/2026 10:00")
        assert dt.day == 24
        assert dt.month == 2

    def test_kahunas_display_format(self) -> None:
        dt = _parse_dt("24 Feb, 2026")
        assert dt.day == 24
        assert dt.month == 2
        assert dt.year == 2026

    def test_datetime_passthrough(self) -> None:
        original = datetime(2026, 2, 24, tzinfo=UTC)
        dt = _parse_dt(original)
        assert dt == original

    def test_naive_datetime_gets_utc(self) -> None:
        original = datetime(2026, 2, 24)
        dt = _parse_dt(original)
        assert dt.tzinfo == UTC

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty datetime"):
            _parse_dt("")

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            _parse_dt("not-a-date")


# ── Appointment Time Range Parsing ──


class TestParseAppointmentTimeRange:
    """Test forward-looking and backward-looking time range parsing."""

    _REF = datetime(2026, 3, 7, 14, 30, 0, tzinfo=UTC)  # Saturday

    def test_rest_of_today(self) -> None:
        start, end = parse_appointment_time_range("rest_of_today", self._REF)
        assert start == self._REF
        assert end.hour == 23
        assert end.minute == 59
        assert end.day == 7

    def test_tomorrow(self) -> None:
        start, end = parse_appointment_time_range("tomorrow", self._REF)
        assert start.day == 8
        assert start.hour == 0
        assert end.day == 8
        assert end.hour == 23

    def test_rest_of_week(self) -> None:
        start, end = parse_appointment_time_range("rest_of_week", self._REF)
        assert start == self._REF
        # Saturday (weekday=5), Sunday is weekday=6
        assert end.weekday() == 6  # Sunday
        assert end.hour == 23

    def test_rest_of_month(self) -> None:
        start, end = parse_appointment_time_range("rest_of_month", self._REF)
        assert start == self._REF
        assert end.month == 3
        assert end.day == 31

    def test_last_week(self) -> None:
        start, end = parse_appointment_time_range("last_week", self._REF)
        assert (end - start).days == 7
        assert end == self._REF

    def test_last_1m(self) -> None:
        start, end = parse_appointment_time_range("last_1m", self._REF)
        assert (end - start).days == 30

    def test_last_3m(self) -> None:
        start, end = parse_appointment_time_range("last_3m", self._REF)
        assert (end - start).days == 90

    def test_last_6m(self) -> None:
        start, end = parse_appointment_time_range("last_6m", self._REF)
        assert (end - start).days == 180

    def test_last_year(self) -> None:
        start, end = parse_appointment_time_range("last_year", self._REF)
        assert (end - start).days == 365

    def test_all_time(self) -> None:
        start, end = parse_appointment_time_range("all_time", self._REF)
        assert start.year == 2000
        assert end > self._REF

    def test_aliases_work(self) -> None:
        """Various aliases should resolve correctly."""
        s1, e1 = parse_appointment_time_range("today", self._REF)
        s2, e2 = parse_appointment_time_range("today_remaining", self._REF)
        assert s1 == s2
        assert e1 == e2

        s3, _e3 = parse_appointment_time_range("past_week", self._REF)
        s4, _e4 = parse_appointment_time_range("last_7d", self._REF)
        assert s3 == s4

    def test_unknown_range_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown time range"):
            parse_appointment_time_range("next_century", self._REF)

    def test_hyphen_and_space_normalisation(self) -> None:
        s1, _ = parse_appointment_time_range("rest-of-today", self._REF)
        s2, _ = parse_appointment_time_range("rest of today", self._REF)
        assert s1 == s2

    def test_rest_of_month_december(self) -> None:
        """December should end on Dec 31."""
        dec_ref = datetime(2026, 12, 15, 10, 0, 0, tzinfo=UTC)
        _, end = parse_appointment_time_range("rest_of_month", dec_ref)
        assert end.month == 12
        assert end.day == 31

    def test_rest_of_week_on_sunday(self) -> None:
        """On Sunday (weekday=6), rest of week should end on the same day."""
        sunday_ref = datetime(2026, 3, 8, 10, 0, 0, tzinfo=UTC)  # Sunday
        _, end = parse_appointment_time_range("rest_of_week", sunday_ref)
        assert end.day == sunday_ref.day


# ── Filter Events By Time ──


_SAMPLE_EVENTS = [
    {"title": "Client A", "start": "2026-03-07T09:00:00Z", "client_name": "Alice"},
    {"title": "Client B", "start": "2026-03-07T14:00:00Z", "client_name": "Bob"},
    {"title": "Client C", "start": "2026-03-08T10:00:00Z", "client_name": "Carol"},
    {"title": "Client D", "start": "2026-03-10T11:00:00Z", "client_name": "Dave"},
    {"title": "Client E", "start": "2026-02-15T09:00:00Z", "client_name": "Eve"},
    {"title": "Client F", "start": "2025-12-01T09:00:00Z", "client_name": "Frank"},
]


class TestFilterEventsByTime:
    def test_filter_today(self) -> None:
        start = datetime(2026, 3, 7, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 7, 23, 59, 59, tzinfo=UTC)
        result = _filter_events_by_time(_SAMPLE_EVENTS, start, end)
        assert len(result) == 2
        names = {e["client_name"] for e in result}
        assert names == {"Alice", "Bob"}

    def test_filter_tomorrow(self) -> None:
        start = datetime(2026, 3, 8, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 8, 23, 59, 59, tzinfo=UTC)
        result = _filter_events_by_time(_SAMPLE_EVENTS, start, end)
        assert len(result) == 1
        assert result[0]["client_name"] == "Carol"

    def test_filter_all(self) -> None:
        start = datetime(2000, 1, 1, tzinfo=UTC)
        end = datetime(2030, 1, 1, tzinfo=UTC)
        result = _filter_events_by_time(_SAMPLE_EVENTS, start, end)
        assert len(result) == 6

    def test_filter_no_matches(self) -> None:
        start = datetime(2027, 1, 1, tzinfo=UTC)
        end = datetime(2027, 12, 31, tzinfo=UTC)
        result = _filter_events_by_time(_SAMPLE_EVENTS, start, end)
        assert len(result) == 0

    def test_filter_skips_missing_dates(self) -> None:
        events = [{"title": "No date"}, {"title": "Has date", "start": "2026-03-07T10:00:00Z"}]
        start = datetime(2026, 3, 7, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 7, 23, 59, 59, tzinfo=UTC)
        result = _filter_events_by_time(events, start, end)
        assert len(result) == 1

    def test_filter_skips_invalid_dates(self) -> None:
        events = [
            {"title": "Bad", "start": "not-a-date"},
            {"title": "Good", "start": "2026-03-07T10:00:00Z"},
        ]
        start = datetime(2026, 3, 7, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 7, 23, 59, 59, tzinfo=UTC)
        result = _filter_events_by_time(events, start, end)
        assert len(result) == 1


# ── Summarise Events ──


class TestSummariseEvents:
    def test_summarise(self) -> None:
        summaries = _summarise_events(_SAMPLE_EVENTS[:2])
        assert len(summaries) == 2
        assert summaries[0]["title"] == "Client A"
        assert summaries[1]["title"] == "Client B"

    def test_summarise_empty(self) -> None:
        assert _summarise_events([]) == []

    def test_summarise_uses_client_name_fallback(self) -> None:
        events = [{"client_name": "Alice", "start": "2026-03-07T09:00:00Z"}]
        summaries = _summarise_events(events)
        assert summaries[0]["title"] == "Alice"


# ── Build Appointment Overview ──


class TestBuildAppointmentOverview:
    _REF = datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC)  # Saturday noon

    def test_overview_structure(self) -> None:
        overview = build_appointment_overview(_SAMPLE_EVENTS, self._REF)
        assert "upcoming" in overview
        assert "historical" in overview
        assert "total_events" in overview
        assert "clients" in overview
        assert overview["total_events"] == 6

    def test_upcoming_windows(self) -> None:
        overview = build_appointment_overview(_SAMPLE_EVENTS, self._REF)
        upcoming = overview["upcoming"]
        assert "rest_of_today" in upcoming
        assert "tomorrow" in upcoming
        assert "rest_of_week" in upcoming
        assert "rest_of_month" in upcoming

    def test_upcoming_rest_of_today_count(self) -> None:
        overview = build_appointment_overview(_SAMPLE_EVENTS, self._REF)
        # At noon on Mar 7, only the 14:00 appointment is upcoming
        today = overview["upcoming"]["rest_of_today"]
        assert today["count"] == 1
        assert today["appointments"][0]["title"] == "Client B"

    def test_upcoming_tomorrow_count(self) -> None:
        overview = build_appointment_overview(_SAMPLE_EVENTS, self._REF)
        assert overview["upcoming"]["tomorrow"]["count"] == 1

    def test_historical_windows(self) -> None:
        overview = build_appointment_overview(_SAMPLE_EVENTS, self._REF)
        historical = overview["historical"]
        assert "last_week" in historical
        assert "last_1m" in historical
        assert "last_3m" in historical
        assert "last_6m" in historical
        assert "last_year" in historical
        assert "all_time" in historical

    def test_historical_all_time_count(self) -> None:
        overview = build_appointment_overview(_SAMPLE_EVENTS, self._REF)
        assert overview["historical"]["all_time"]["count"] == 6

    def test_per_client_counts(self) -> None:
        overview = build_appointment_overview(_SAMPLE_EVENTS, self._REF)
        clients = overview["clients"]
        assert len(clients) == 6
        # Each client has 1 appointment in the sample
        assert all(c["appointments"] == 1 for c in clients)

    def test_per_client_sorted_by_count(self) -> None:
        # Add duplicate events for one client
        extra = {
            "title": "Alice Extra",
            "start": "2026-03-09T10:00:00Z",
            "client_name": "Alice",
        }
        events = [*_SAMPLE_EVENTS, extra]
        overview = build_appointment_overview(events, self._REF)
        # Alice should be first (2 appointments)
        assert overview["clients"][0]["name"] == "Alice"
        assert overview["clients"][0]["appointments"] == 2

    def test_overview_empty_events(self) -> None:
        overview = build_appointment_overview([], self._REF)
        assert overview["total_events"] == 0
        assert overview["clients"] == []
        assert overview["upcoming"]["rest_of_today"]["count"] == 0


# ── Build Client Appointment Counts ──


_CLIENT_EVENTS = [
    {
        "title": "PT Alice",
        "start": "2026-03-01T10:00:00Z",
        "client_uuid": "alice-uuid",
        "client_name": "Alice",
    },
    {
        "title": "PT Alice",
        "start": "2026-03-05T10:00:00Z",
        "client_uuid": "alice-uuid",
        "client_name": "Alice",
    },
    {
        "title": "PT Alice",
        "start": "2026-02-01T10:00:00Z",
        "client_uuid": "alice-uuid",
        "client_name": "Alice",
    },
    {
        "title": "PT Alice",
        "start": "2025-06-15T10:00:00Z",
        "client_uuid": "alice-uuid",
        "client_name": "Alice",
    },
    {
        "title": "PT Bob",
        "start": "2026-03-05T11:00:00Z",
        "client_uuid": "bob-uuid",
        "client_name": "Bob",
    },
]


class TestBuildClientAppointmentCounts:
    _REF = datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC)

    def test_counts_by_uuid(self) -> None:
        counts = build_client_appointment_counts(_CLIENT_EVENTS, "alice-uuid", reference=self._REF)
        assert counts["client_uuid"] == "alice-uuid"
        assert counts["total"] == 4
        assert counts["counts"]["last_week"] == 2  # Mar 1 + Mar 5
        assert counts["counts"]["last_1m"] == 2  # Mar 1 + Mar 5
        assert counts["counts"]["last_3m"] == 3  # Mar 1 + Mar 5 + Feb 1
        assert counts["counts"]["all_time"] == 4

    def test_counts_by_name(self) -> None:
        counts = build_client_appointment_counts(
            _CLIENT_EVENTS, "unknown-uuid", client_name="alice", reference=self._REF
        )
        assert counts["total"] == 4

    def test_counts_zero_for_unknown_client(self) -> None:
        counts = build_client_appointment_counts(
            _CLIENT_EVENTS, "nonexistent-uuid", reference=self._REF
        )
        assert counts["total"] == 0
        assert counts["counts"]["all_time"] == 0

    def test_counts_excludes_other_clients(self) -> None:
        counts = build_client_appointment_counts(_CLIENT_EVENTS, "bob-uuid", reference=self._REF)
        assert counts["total"] == 1
        assert counts["counts"]["last_week"] == 1

    def test_counts_structure(self) -> None:
        counts = build_client_appointment_counts(
            _CLIENT_EVENTS, "alice-uuid", client_name="Alice", reference=self._REF
        )
        assert counts["client_name"] == "Alice"
        assert "counts" in counts
        assert set(counts["counts"].keys()) == {
            "last_week",
            "last_1m",
            "last_3m",
            "last_6m",
            "last_year",
            "all_time",
        }


# ── Integration: Full Pipeline ──


class TestFullPipeline:
    """Test the complete pipeline: raw data → parsed → formatted summary."""

    def test_bruce_wayne_checkin_history(self) -> None:
        """Replicate the exact check-in data from the Kahunas dashboard screenshot."""
        checkins = [
            {
                "check_in_number": 4,
                "submitted_at": "2026-02-24",
                "check_in_day": "Tuesday",
                "weight": 207,
                "waist": 30.5,
                "hips": 38.5,
                "biceps": 17.5,
                "thighs": 24.5,
                "sleep_quality": 8,
                "nutrition_adherence": 9,
                "water_intake": 3.5,
                "workout_rating": 9,
                "stress_level": 6,
                "energy_level": 8,
                "mood_wellbeing": 8,
            },
            {
                "check_in_number": 3,
                "submitted_at": "2026-02-17",
                "check_in_day": "Tuesday",
                "weight": 208,
                "waist": 37,
                "hips": 39,
                "biceps": 17.8,
                "thighs": 25,
                "sleep_quality": 8,
                "nutrition_adherence": 8,
                "water_intake": 3.5,
                "workout_rating": 8,
                "stress_level": 7,
                "energy_level": 7,
                "mood_wellbeing": 7,
            },
            {
                "check_in_number": 2,
                "submitted_at": "2026-02-10",
                "check_in_day": "Tuesday",
                "weight": 209,
                "waist": 31.5,
                "hips": 39.5,
                "biceps": 18,
                "thighs": 25.5,
                "sleep_quality": 7,
                "nutrition_adherence": 9,
                "water_intake": 3.2,
                "workout_rating": 8,
                "stress_level": 7,
                "energy_level": 8,
                "mood_wellbeing": 8,
            },
            {
                "check_in_number": 1,
                "submitted_at": "2026-02-03",
                "check_in_day": "Tuesday",
                "weight": 210,
                "waist": 32,
                "hips": 40,
                "biceps": 17,
                "thighs": 24,
                "sleep_quality": 6,
                "nutrition_adherence": 9,
                "water_intake": 3,
                "workout_rating": 10,
                "stress_level": 7,
                "energy_level": 8,
                "mood_wellbeing": 7,
            },
        ]

        summary = format_checkin_summary(
            checkins,
            client_name="Bruce Wayne",
            weight_unit="lbs",
            measurement_unit="inches",
        )

        # Verify structure
        assert summary["client_name"] == "Bruce Wayne"
        assert summary["total_checkins"] == 4
        assert summary["first_checkin"] == "2026-02-03"
        assert summary["latest_checkin"] == "2026-02-24"

        # Verify row ordering (most recent first)
        assert summary["rows"][0]["number"] == 4
        assert summary["rows"][0]["weight"] == 207.0
        assert summary["rows"][3]["number"] == 1
        assert summary["rows"][3]["weight"] == 210.0

        # Verify trends (check-in 3 → 4)
        trends = summary["trends"]
        assert trends["weight"]["change"] == -1.0
        assert trends["weight"]["direction"] == "down"
        assert trends["waist"]["change"] == -6.5
        assert trends["waist"]["direction"] == "down"
        assert trends["sleep_quality"]["change"] == 0.0
        assert trends["sleep_quality"]["direction"] == "same"

        # Verify columns include correct units
        col_labels = {c["key"]: c["label"] for c in summary["columns"]}
        assert "lbs" in col_labels["weight"]
        assert "inches" in col_labels["waist"]
        assert "inches" in col_labels["hips"]
        assert "inches" in col_labels["biceps"]
        assert "inches" in col_labels["thighs"]

        # All 12 fields should be present in columns
        assert len(summary["columns"]) == 12

    def test_mixed_format_checkins(self) -> None:
        """Test mixing different API response formats."""
        checkins = [
            _SAMPLE_CHECKIN_FLAT,
            _SAMPLE_CHECKIN_NESTED,
            _SAMPLE_CHECKIN_ARRAY,
        ]
        summary = format_checkin_summary(checkins, client_name="Mixed Format")
        assert summary["total_checkins"] == 3
        # All rows should have weight data
        for row in summary["rows"]:
            assert row.get("weight") is not None
