"""Check-in history parsing and formatting for Kahunas clients.

Parses raw check-in data from the Kahunas API and formats it into
structured summaries suitable for MCP tool responses. Supports the
full set of check-in fields visible on the Kahunas coach dashboard.

Typical check-in fields:
    - Body measurements: weight, waist, hips, biceps, thighs
    - Lifestyle ratings (1-10): sleep, nutrition adherence, workout rating,
      stress, energy, mood/wellbeing
    - Water intake (litres)
    - Photos, notes
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Standard check-in field mapping.
# Keys are normalised field names → (display_label, category, sort_order).
CHECKIN_FIELDS: dict[str, dict[str, str | int]] = {
    "weight": {"label": "Weight", "category": "body", "order": 1},
    "waist": {"label": "Waist", "category": "body", "order": 2},
    "hips": {"label": "Hips", "category": "body", "order": 3},
    "biceps": {"label": "Biceps", "category": "body", "order": 4},
    "thighs": {"label": "Thighs", "category": "body", "order": 5},
    "sleep_quality": {"label": "Sleep (1-10)", "category": "lifestyle", "order": 6},
    "nutrition_adherence": {
        "label": "Nutrition Adherence (1-10)",
        "category": "lifestyle",
        "order": 7,
    },
    "water_intake": {"label": "Water Intake", "category": "lifestyle", "order": 8},
    "workout_rating": {
        "label": "Workout Rating (1-10)",
        "category": "lifestyle",
        "order": 9,
    },
    "stress_level": {
        "label": "Stress Level (1-10)",
        "category": "lifestyle",
        "order": 10,
    },
    "energy_level": {
        "label": "Energy Level (1-10)",
        "category": "lifestyle",
        "order": 11,
    },
    "mood_wellbeing": {
        "label": "Mood & Wellbeing (1-10)",
        "category": "lifestyle",
        "order": 12,
    },
}

# Aliases used in different API responses / form labels
_FIELD_ALIASES: dict[str, str] = {
    "body_weight": "weight",
    "waist_measurement": "waist",
    "hip_measurement": "hips",
    "hip": "hips",
    "bicep": "biceps",
    "bicep_measurement": "biceps",
    "thigh": "thighs",
    "thigh_measurement": "thighs",
    "sleep": "sleep_quality",
    "sleep_quality_1_10": "sleep_quality",
    "nutrition": "nutrition_adherence",
    "nutritional_plan": "nutrition_adherence",
    "stick_to_nutritional_plan": "nutrition_adherence",
    "water": "water_intake",
    "average_water_intake": "water_intake",
    "water_intake_per_day": "water_intake",
    "workout": "workout_rating",
    "rate_your_workouts": "workout_rating",
    "workout_rate": "workout_rating",
    "stress": "stress_level",
    "average_stress_level": "stress_level",
    "stress_level_this_week": "stress_level",
    "energy": "energy_level",
    "daily_energy": "energy_level",
    "average_daily_energy": "energy_level",
    "energy_levels": "energy_level",
    "mood": "mood_wellbeing",
    "wellbeing": "mood_wellbeing",
    "overall_wellbeing": "mood_wellbeing",
    "mood_and_overall_wellbeing": "mood_wellbeing",
    "mood_overall_wellbeing": "mood_wellbeing",
}


def normalise_field_name(raw_name: str) -> str:
    """Normalise a check-in field name to a canonical key.

    Handles various formats from the Kahunas API:
    - CamelCase / Title Case with spaces
    - snake_case
    - Field names with units or question marks

    Args:
        raw_name: Raw field name from the API.

    Returns:
        Normalised field key (e.g. 'weight', 'sleep_quality').
    """
    # Lowercase and strip whitespace
    name = raw_name.strip().lower()

    # Remove common suffixes/noise (order matters: longer patterns first)
    for noise in (
        "(1-10)",
        "(liters)",
        "(litres)",
        "(lbs)",
        "(kg)",
        "(inches)",
        "(cm)",
        "?",
        " - lbs",
        " - kg",
        " - inches",
        " - cm",
        "- lbs",
        "- kg",
        "- inches",
        "- cm",
        " lbs",
        " kg",
        " inches",
        " cm",
        " - ",
    ):
        name = name.replace(noise, "")

    # Replace non-alphanumeric with underscores
    cleaned = ""
    for ch in name.strip():
        cleaned += ch if ch.isalnum() else "_"

    # Collapse multiple underscores and strip
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.strip("_")

    # Check aliases
    if cleaned in _FIELD_ALIASES:
        return _FIELD_ALIASES[cleaned]

    # Check if it's already a known field
    if cleaned in CHECKIN_FIELDS:
        return cleaned

    # Try partial matching for aliases
    for alias, canonical in _FIELD_ALIASES.items():
        if alias in cleaned or cleaned in alias:
            return canonical

    return cleaned


# Metadata keys to skip when parsing check-in fields
_METADATA_KEYS = frozenset(
    {
        "uuid",
        "id",
        "check_in_number",
        "number",
        "submitted_at",
        "date",
        "when",
        "created_at",
        "check_in_day",
        "day",
        "status",
        "client_uuid",
        "client_name",
        "photos",
        "images",
        "notes",
        "data",
        "fields",
    }
)


def _extract_fields_from_list(data_source: list[Any]) -> dict[str, Any]:
    """Extract fields from an array of {name, value} pairs."""
    fields: dict[str, Any] = {}
    for item in data_source:
        if isinstance(item, dict) and "name" in item:
            key = normalise_field_name(str(item["name"]))
            fields[key] = _parse_numeric(item.get("value"))
    return fields


def _extract_fields_from_dict(data_source: dict[str, Any]) -> dict[str, Any]:
    """Extract fields from a flat or nested dict, skipping metadata keys."""
    fields: dict[str, Any] = {}
    for raw_key, raw_val in data_source.items():
        if raw_key in _METADATA_KEYS:
            continue
        key = normalise_field_name(raw_key)
        if key in CHECKIN_FIELDS:
            fields[key] = _parse_numeric(raw_val)
    return fields


def parse_checkin_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse a raw check-in record into a structured dict.

    Handles multiple response formats from the Kahunas API:
    - Flat dict with field names as keys
    - Nested 'data' or 'fields' dict
    - Array of {name, value} pairs

    Args:
        raw: Raw check-in record from the API.

    Returns:
        Structured dict with normalised field names and metadata.
    """
    record: dict[str, Any] = {
        "number": raw.get("check_in_number", raw.get("number", raw.get("#", 0))),
        "date": raw.get(
            "submitted_at",
            raw.get("date", raw.get("when", raw.get("created_at", ""))),
        ),
        "uuid": raw.get("uuid", raw.get("id", "")),
        "day": raw.get("check_in_day", raw.get("day", "")),
        "status": raw.get("status", "submitted"),
    }

    # Extract measurement/lifestyle fields
    data_source = raw.get("data", raw.get("fields", raw))
    if isinstance(data_source, list):
        fields = _extract_fields_from_list(data_source)
    elif isinstance(data_source, dict):
        fields = _extract_fields_from_dict(data_source)
    else:
        fields = {}

    # Also check top-level for known fields
    for raw_key, raw_val in raw.items():
        key = normalise_field_name(raw_key)
        if key in CHECKIN_FIELDS and key not in fields:
            fields[key] = _parse_numeric(raw_val)

    record["fields"] = fields

    # Extract notes/photos if present
    notes = raw.get("notes", raw.get("note", ""))
    if notes:
        record["notes"] = notes

    photos = raw.get("photos", raw.get("images", []))
    if photos:
        record["photo_count"] = len(photos) if isinstance(photos, list) else 0

    return record


def format_checkin_summary(
    checkins: list[dict[str, Any]],
    client_name: str = "",
    weight_unit: str = "kg",
    measurement_unit: str = "cm",
) -> dict[str, Any]:
    """Format a list of check-in records into a structured summary.

    Produces a compact summary suitable for MCP tool responses, including:
    - Tabular data with all check-in fields
    - Trend analysis (direction arrows for improving/declining metrics)
    - Latest vs first check-in comparison

    Args:
        checkins: List of raw check-in dicts from the API.
        client_name: Client display name.
        weight_unit: Weight unit (kg or lbs).
        measurement_unit: Body measurement unit (cm or inches).

    Returns:
        Structured summary dict.
    """
    parsed = [parse_checkin_record(ci) for ci in checkins]

    # Sort by number (most recent first)
    parsed.sort(key=lambda x: x.get("number", 0), reverse=True)

    # Build unit labels for body measurement fields
    units = {
        "weight": weight_unit,
        "waist": measurement_unit,
        "hips": measurement_unit,
        "biceps": measurement_unit,
        "thighs": measurement_unit,
        "water_intake": "L",
    }

    # Build column definitions (only include fields that have data)
    all_field_keys: set[str] = set()
    for rec in parsed:
        all_field_keys.update(rec.get("fields", {}).keys())

    # Sort by defined order
    sorted_fields = sorted(
        all_field_keys,
        key=lambda k: CHECKIN_FIELDS.get(k, {}).get("order", 99),
    )

    columns = []
    for key in sorted_fields:
        meta = CHECKIN_FIELDS.get(key, {"label": key.replace("_", " ").title()})
        unit = units.get(key, "")
        label = str(meta.get("label", key))
        if unit:
            label = f"{label} ({unit})"
        columns.append({"key": key, "label": label})

    # Build rows
    rows = []
    for rec in parsed:
        row: dict[str, Any] = {
            "number": rec["number"],
            "date": rec["date"],
            "day": rec.get("day", ""),
        }
        for col in columns:
            row[col["key"]] = rec.get("fields", {}).get(col["key"])
        if rec.get("notes"):
            row["notes"] = rec["notes"]
        if rec.get("photo_count"):
            row["photo_count"] = rec["photo_count"]
        rows.append(row)

    # Calculate trends (latest vs previous)
    trends = _calculate_trends(parsed)

    result: dict[str, Any] = {
        "client_name": client_name or None,
        "total_checkins": len(parsed),
        "columns": columns,
        "rows": rows,
    }
    if trends:
        result["trends"] = trends

    # Date range
    dates = [r["date"] for r in parsed if r.get("date")]
    if dates:
        result["first_checkin"] = dates[-1] if dates else None
        result["latest_checkin"] = dates[0] if dates else None

    return result


def _calculate_trends(parsed_checkins: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Calculate trends between latest and previous check-in.

    Args:
        parsed_checkins: Sorted list (most recent first) of parsed records.

    Returns:
        Dict of field → {change, direction} or None if insufficient data.
    """
    if len(parsed_checkins) < 2:
        return None

    latest = parsed_checkins[0].get("fields", {})
    previous = parsed_checkins[1].get("fields", {})

    trends: dict[str, Any] = {}
    for key in latest:
        curr = latest.get(key)
        prev = previous.get(key)
        if curr is not None and prev is not None:
            try:
                diff = round(float(curr) - float(prev), 2)
                if diff > 0:
                    direction = "up"
                elif diff < 0:
                    direction = "down"
                else:
                    direction = "same"
                trends[key] = {"change": diff, "direction": direction}
            except (TypeError, ValueError):
                continue

    return trends if trends else None


# ── Appointment Overview Helpers ──


def parse_appointment_time_range(
    range_label: str,
    reference: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Parse time range labels for appointment overview.

    Supports both forward-looking (upcoming) and backward-looking (historical)
    time ranges.

    Forward ranges:
        rest_of_today, tomorrow, rest_of_week, rest_of_month

    Backward ranges:
        last_week, last_1m, last_3m, last_6m, last_year, all_time

    Args:
        range_label: Time range descriptor.
        reference: Reference datetime (defaults to now UTC).

    Returns:
        Tuple of (start_dt, end_dt) in UTC.

    Raises:
        ValueError: If the range label is not recognised.
    """
    now = reference or datetime.now(UTC)
    label = range_label.lower().strip().replace(" ", "_").replace("-", "_")

    # Forward-looking (upcoming)
    if label in ("rest_of_today", "today_remaining", "today"):
        return now, now.replace(hour=23, minute=59, second=59, microsecond=0)

    if label == "tomorrow":
        tomorrow_start = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        tomorrow_end = tomorrow_start.replace(hour=23, minute=59, second=59, microsecond=0)
        return tomorrow_start, tomorrow_end

    if label in ("rest_of_week", "this_week", "rest_of_calendar_week"):
        # Rest of the current ISO calendar week (Mon-Sun)
        days_until_sunday = 6 - now.weekday()
        if days_until_sunday < 0:
            days_until_sunday = 0
        week_end = (now + timedelta(days=days_until_sunday)).replace(
            hour=23, minute=59, second=59, microsecond=0
        )
        return now, week_end

    if label in ("rest_of_month", "this_month", "rest_of_calendar_month"):
        # Rest of the current calendar month
        if now.month == 12:
            month_end = now.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=0)
        else:
            month_end = now.replace(
                month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(seconds=1)
        return now, month_end

    # Backward-looking (historical) — use lookup to reduce cognitive complexity
    _backward_days: dict[str, int] = {
        "last_week": 7,
        "last_7d": 7,
        "past_week": 7,
        "last_1m": 30,
        "last_month": 30,
        "last_30d": 30,
        "past_month": 30,
        "last_3m": 90,
        "last_3_months": 90,
        "last_90d": 90,
        "past_3_months": 90,
        "last_6m": 180,
        "last_6_months": 180,
        "last_180d": 180,
        "past_6_months": 180,
        "last_year": 365,
        "last_12m": 365,
        "last_365d": 365,
        "past_year": 365,
    }
    if label in _backward_days:
        return now - timedelta(days=_backward_days[label]), now

    if label in ("all_time", "all"):
        return datetime(2000, 1, 1, tzinfo=UTC), now + timedelta(days=365 * 10)

    raise ValueError(
        f"Unknown time range: '{range_label}'. "
        "Forward: rest_of_today, tomorrow, rest_of_week, rest_of_month. "
        "Backward: last_week, last_1m, last_3m, last_6m, last_year, all_time."
    )


def build_appointment_overview(
    events: list[dict[str, Any]],
    reference: datetime | None = None,
) -> dict[str, Any]:
    """Build a comprehensive appointment overview with multiple time windows.

    Partitions events into upcoming (forward-looking) and historical
    (backward-looking) counts.

    Args:
        events: List of calendar event dicts with 'start' datetime strings.
        reference: Reference datetime (defaults to now UTC).

    Returns:
        Dict with upcoming/historical sections and per-client counts.
    """
    now = reference or datetime.now(UTC)

    # Define time windows
    upcoming_ranges = ["rest_of_today", "tomorrow", "rest_of_week", "rest_of_month"]
    historical_ranges = ["last_week", "last_1m", "last_3m", "last_6m", "last_year", "all_time"]

    upcoming: dict[str, Any] = {}
    for label in upcoming_ranges:
        start_dt, end_dt = parse_appointment_time_range(label, now)
        matched = _filter_events_by_time(events, start_dt, end_dt)
        upcoming[label] = {
            "count": len(matched),
            "appointments": _summarise_events(matched),
        }

    historical: dict[str, Any] = {}
    for label in historical_ranges:
        start_dt, end_dt = parse_appointment_time_range(label, now)
        matched = _filter_events_by_time(events, start_dt, end_dt)
        historical[label] = {"count": len(matched)}

    # Per-client breakdown
    client_counts: dict[str, int] = {}
    for evt in events:
        name = evt.get("client_name", evt.get("title", "Unknown"))
        client_counts[name] = client_counts.get(name, 0) + 1

    # Sort by count descending
    sorted_clients = sorted(client_counts.items(), key=lambda x: x[1], reverse=True)

    return {
        "upcoming": upcoming,
        "historical": historical,
        "total_events": len(events),
        "clients": [{"name": n, "appointments": c} for n, c in sorted_clients],
    }


def build_client_appointment_counts(
    events: list[dict[str, Any]],
    client_uuid: str,
    client_name: str = "",
    reference: datetime | None = None,
) -> dict[str, Any]:
    """Build appointment counts for a specific client across time windows.

    Args:
        events: List of all calendar events.
        client_uuid: Client UUID to filter by.
        client_name: Client name for fallback matching.
        reference: Reference datetime (defaults to now UTC).

    Returns:
        Dict with counts per time window for the specified client.
    """
    now = reference or datetime.now(UTC)

    # Filter to this client's events
    search_name = client_name.lower()
    client_events = []
    for evt in events:
        evt_client = evt.get("client_uuid", evt.get("client_id", ""))
        evt_title = (evt.get("title", "") or "").lower()
        evt_name = (evt.get("client_name", "") or "").lower()

        if (
            evt_client == client_uuid
            or (search_name and search_name in evt_title)
            or (search_name and search_name in evt_name)
        ):
            client_events.append(evt)

    ranges = [
        "last_week",
        "last_1m",
        "last_3m",
        "last_6m",
        "last_year",
        "all_time",
    ]

    counts: dict[str, int] = {}
    for label in ranges:
        start_dt, end_dt = parse_appointment_time_range(label, now)
        matched = _filter_events_by_time(client_events, start_dt, end_dt)
        counts[label] = len(matched)

    return {
        "client_uuid": client_uuid,
        "client_name": client_name or None,
        "total": len(client_events),
        "counts": counts,
    }


def _filter_events_by_time(
    events: list[dict[str, Any]],
    start_dt: datetime,
    end_dt: datetime,
) -> list[dict[str, Any]]:
    """Filter events to those within a time range."""
    matched = []
    for evt in events:
        raw_dt = evt.get("start", evt.get("start_time", ""))
        if not raw_dt:
            continue
        try:
            dt = _parse_dt(raw_dt)
        except (ValueError, TypeError):
            continue
        if start_dt <= dt <= end_dt:
            matched.append(evt)
    return matched


def _summarise_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create compact summaries of events."""
    summaries = []
    for evt in events:
        summaries.append(
            {
                "title": evt.get("title", evt.get("client_name", "")),
                "start": evt.get("start", evt.get("start_time", "")),
                "end": evt.get("end", evt.get("end_time", "")),
            }
        )
    return summaries


def _parse_dt(raw: str | datetime) -> datetime:
    """Parse a datetime string or return the datetime as-is."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)

    raw_str = str(raw).strip()
    if not raw_str:
        raise ValueError("Empty datetime string")

    # Try ISO 8601
    try:
        dt = datetime.fromisoformat(raw_str.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        pass

    # Common formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d %b, %Y",
        "%d %b %Y",
    ):
        try:
            dt = datetime.strptime(raw_str, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue

    raise ValueError(f"Cannot parse datetime: '{raw_str}'")


def _parse_numeric(value: Any) -> float | None:
    """Try to parse a value as a float, return None if not numeric."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
