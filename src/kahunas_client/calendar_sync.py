"""Calendar synchronisation for Kahunas appointments.

Supports generating iCal (.ics) files for Apple Calendar import and
formatting events for Google Calendar API integration. Each calendar
event embeds the Kahunas appointment UUID so events can be safely
added, edited, or removed without duplicates.

Configuration:
    Set these environment variables or pass via KahunasConfig:
    - KAHUNAS_CALENDAR_PREFIX: Prefix for event titles (default: "Workout")
    - KAHUNAS_DEFAULT_GYM: Default gym/location for appointments
    - KAHUNAS_GYM_LIST: Comma-separated list of available gyms
"""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# iCal constants
_ICAL_VERSION = "2.0"
_ICAL_PRODID = "-//Kahunas//Python Client//EN"


class CalendarConfig:
    """Configuration for calendar sync features."""

    def __init__(
        self,
        prefix: str = "Workout",
        default_gym: str = "",
        gym_list: list[str] | None = None,
        default_duration_minutes: int = 60,
    ) -> None:
        self.prefix = prefix
        self.default_gym = default_gym
        self.gym_list = gym_list or []
        self.default_duration_minutes = default_duration_minutes

    def is_configured(self) -> bool:
        """Check if calendar config has meaningful settings."""
        return bool(self.prefix)


# ── Time Range Helpers ──


def parse_time_range(
    range_label: str,
    reference: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Parse a human-readable time range into (start, end) datetime pair.

    Supported range labels:
        today, next_24h, next_48h, next_7d, next_month,
        next_3m, next_6m, next_12m

    Args:
        range_label: One of the supported range strings.
        reference: Reference datetime (defaults to now UTC).

    Returns:
        Tuple of (start_dt, end_dt) in UTC.

    Raises:
        ValueError: If the range label is not recognised.
    """
    now = reference or datetime.now(UTC)
    start = now

    label = range_label.lower().strip().replace(" ", "_")
    match label:
        case "today":
            end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        case "next_24h" | "next_24_hours":
            end = now + timedelta(hours=24)
        case "next_48h" | "next_48_hours":
            end = now + timedelta(hours=48)
        case "next_7d" | "next_7_days" | "next_week":
            end = now + timedelta(days=7)
        case "next_month" | "next_30d":
            end = now + timedelta(days=30)
        case "next_3m" | "next_3_months" | "next_90d":
            end = now + timedelta(days=90)
        case "next_6m" | "next_6_months" | "next_180d":
            end = now + timedelta(days=180)
        case "next_12m" | "next_12_months" | "next_year" | "next_365d":
            end = now + timedelta(days=365)
        case _:
            raise ValueError(
                f"Unknown time range: '{range_label}'. "
                "Use: today, next_24h, next_48h, next_7d, next_month, "
                "next_3m, next_6m, next_12m"
            )
    return start, end


def filter_appointments_by_range(
    appointments: list[dict[str, Any]],
    start_dt: datetime,
    end_dt: datetime,
    date_field: str = "start_time",
) -> list[dict[str, Any]]:
    """Filter a list of appointment dicts to those within a time range.

    Args:
        appointments: List of appointment dicts.
        start_dt: Start of the range (inclusive).
        end_dt: End of the range (inclusive).
        date_field: Key in each dict holding the datetime string.

    Returns:
        Filtered list of appointments.
    """
    filtered = []
    for appt in appointments:
        raw_dt = appt.get(date_field, "")
        if not raw_dt:
            continue
        try:
            dt = _parse_datetime(raw_dt)
        except (ValueError, TypeError):
            continue
        if start_dt <= dt <= end_dt:
            filtered.append(appt)
    return filtered


# ── Title Formatting ──


def format_appointment_title(
    client_name: str,
    start_time: datetime | str | None = None,
    prefix: str = "Workout",
) -> str:
    """Format an appointment title with the standard naming convention.

    Format: ``<prefix>: <client name>`` or
    ``<prefix>: <client name> on <date and time>`` if start_time provided.

    Args:
        client_name: Full name of the client.
        start_time: Optional start datetime for the appointment.
        prefix: Title prefix (e.g. "Workout", "PT Session").

    Returns:
        Formatted title string.

    Examples:
        >>> format_appointment_title("John Doe")
        'Workout: John Doe'
        >>> format_appointment_title("Jane Smith", prefix="PT Session")
        'PT Session: Jane Smith'
    """
    title = f"{prefix}: {client_name}"
    if start_time:
        if isinstance(start_time, str):
            try:
                start_time = _parse_datetime(start_time)
            except (ValueError, TypeError):
                return title
        formatted = start_time.strftime("%a %d %b %Y %H:%M")
        title = f"{title} on {formatted}"
    return title


# ── Kahunas UUID Embedding ──

_KAHUNAS_UUID_PREFIX = "[kahunas:"
_KAHUNAS_UUID_SUFFIX = "]"


def embed_kahunas_uuid(description: str, kahunas_uuid: str) -> str:
    """Embed a Kahunas UUID in the event description for tracking.

    The UUID is appended as a machine-readable tag that can be parsed
    later for safe add/edit/remove operations.

    Args:
        description: Existing event description text.
        kahunas_uuid: The Kahunas appointment UUID.

    Returns:
        Description with embedded UUID tag.
    """
    tag = f"{_KAHUNAS_UUID_PREFIX}{kahunas_uuid}{_KAHUNAS_UUID_SUFFIX}"
    if tag in description:
        return description
    if description:
        return f"{description}\n\n{tag}"
    return tag


def extract_kahunas_uuid(description: str) -> str | None:
    """Extract a Kahunas UUID from an event description.

    Args:
        description: Event description text.

    Returns:
        The Kahunas UUID if found, or None.
    """
    if not description:
        return None
    start = description.find(_KAHUNAS_UUID_PREFIX)
    if start == -1:
        return None
    start += len(_KAHUNAS_UUID_PREFIX)
    end = description.find(_KAHUNAS_UUID_SUFFIX, start)
    if end == -1:
        return None
    return description[start:end]


# ── iCal (.ics) Generation for Apple Calendar ──


def generate_ics(
    appointments: list[dict[str, Any]],
    config: CalendarConfig | None = None,
) -> str:
    """Generate an iCal (.ics) file from a list of Kahunas appointments.

    Each appointment dict should have:
        - uuid: Kahunas appointment UUID
        - client_name: Client full name
        - start_time: ISO datetime string or datetime object
        - end_time: Optional ISO datetime string or datetime object
        - duration_minutes: Optional duration in minutes (default: 60)
        - notes: Optional notes/description
        - location: Optional location/gym name

    Args:
        appointments: List of appointment dicts.
        config: Calendar configuration.

    Returns:
        iCal file content as a string.
    """
    cfg = config or CalendarConfig()
    lines = [
        "BEGIN:VCALENDAR",
        f"VERSION:{_ICAL_VERSION}",
        f"PRODID:{_ICAL_PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Kahunas Appointments",
    ]

    for appt in appointments:
        vevent = _appointment_to_vevent(appt, cfg)
        lines.extend(vevent)

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def _appointment_to_vevent(
    appt: dict[str, Any],
    config: CalendarConfig,
) -> list[str]:
    """Convert a single appointment dict to VEVENT lines."""
    kahunas_uuid = appt.get("uuid", str(_uuid.uuid4()))
    client_name = appt.get("client_name", "Unknown Client")
    notes = appt.get("notes", "")
    location = appt.get("location", "") or config.default_gym

    # Parse start time
    raw_start = appt.get("start_time", "")
    if isinstance(raw_start, datetime):
        start_dt = raw_start
    else:
        try:
            start_dt = _parse_datetime(str(raw_start))
        except (ValueError, TypeError):
            start_dt = datetime.now(UTC)

    # Parse end time or calculate from duration
    raw_end = appt.get("end_time", "")
    if raw_end:
        if isinstance(raw_end, datetime):
            end_dt = raw_end
        else:
            try:
                end_dt = _parse_datetime(str(raw_end))
            except (ValueError, TypeError):
                duration = appt.get("duration_minutes", config.default_duration_minutes)
                end_dt = start_dt + timedelta(minutes=duration)
    else:
        duration = appt.get("duration_minutes", config.default_duration_minutes)
        end_dt = start_dt + timedelta(minutes=duration)

    # Format title
    title = format_appointment_title(client_name, prefix=config.prefix)

    # Build description with embedded UUID
    desc = embed_kahunas_uuid(notes, kahunas_uuid)

    # Format datetimes for iCal (UTC)
    dtstart = _dt_to_ical(start_dt)
    dtend = _dt_to_ical(end_dt)
    dtstamp = _dt_to_ical(datetime.now(UTC))

    lines = [
        "BEGIN:VEVENT",
        f"UID:kahunas-{kahunas_uuid}@kahunas.io",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{_ical_escape(title)}",
    ]
    if desc:
        lines.append(f"DESCRIPTION:{_ical_escape(desc)}")
    if location:
        lines.append(f"LOCATION:{_ical_escape(location)}")
    lines.append(f"X-KAHUNAS-UUID:{kahunas_uuid}")
    lines.append("STATUS:CONFIRMED")
    lines.append("END:VEVENT")
    return lines


# ── Google Calendar Formatting ──


def format_for_google_calendar(
    appointments: list[dict[str, Any]],
    config: CalendarConfig | None = None,
    calendar_id: str = "primary",
) -> list[dict[str, Any]]:
    """Format Kahunas appointments as Google Calendar API event objects.

    Returns a list of event dicts ready for the Google Calendar API
    ``events.insert()`` or ``events.update()`` method.

    Each event includes the Kahunas UUID in the description and
    extendedProperties for programmatic tracking.

    Args:
        appointments: List of appointment dicts.
        config: Calendar configuration.
        calendar_id: Google Calendar ID to target.

    Returns:
        List of Google Calendar event objects.
    """
    cfg = config or CalendarConfig()
    events = []

    for appt in appointments:
        event = _appointment_to_gcal_event(appt, cfg)
        event["calendar_id"] = calendar_id
        events.append(event)

    return events


def _appointment_to_gcal_event(
    appt: dict[str, Any],
    config: CalendarConfig,
) -> dict[str, Any]:
    """Convert a single appointment to a Google Calendar event dict."""
    kahunas_uuid = appt.get("uuid", str(_uuid.uuid4()))
    client_name = appt.get("client_name", "Unknown Client")
    notes = appt.get("notes", "")
    location = appt.get("location", "") or config.default_gym

    # Parse start time
    raw_start = appt.get("start_time", "")
    if isinstance(raw_start, datetime):
        start_dt = raw_start
    else:
        try:
            start_dt = _parse_datetime(str(raw_start))
        except (ValueError, TypeError):
            start_dt = datetime.now(UTC)

    # Parse end time or calculate from duration
    raw_end = appt.get("end_time", "")
    if raw_end:
        if isinstance(raw_end, datetime):
            end_dt = raw_end
        else:
            try:
                end_dt = _parse_datetime(str(raw_end))
            except (ValueError, TypeError):
                duration = appt.get("duration_minutes", config.default_duration_minutes)
                end_dt = start_dt + timedelta(minutes=duration)
    else:
        duration = appt.get("duration_minutes", config.default_duration_minutes)
        end_dt = start_dt + timedelta(minutes=duration)

    # Build title
    title = format_appointment_title(client_name, prefix=config.prefix)

    # Build description with embedded UUID
    desc = embed_kahunas_uuid(notes, kahunas_uuid)

    event: dict[str, Any] = {
        "summary": title,
        "description": desc,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "UTC",
        },
        "extendedProperties": {
            "private": {
                "kahunas_uuid": kahunas_uuid,
                "kahunas_client": client_name,
            }
        },
    }

    if location:
        event["location"] = location

    return event


# ── Client Removal ──


def build_removal_summary(
    client_name: str,
    client_uuid: str,
    appointments_found: int,
    appointments_removed: int,
    kahunas_removed: bool,
) -> dict[str, Any]:
    """Build a summary dict of a client removal operation.

    Args:
        client_name: Full name of the client.
        client_uuid: Kahunas UUID of the client.
        appointments_found: Number of calendar appointments found.
        appointments_removed: Number of calendar appointments removed.
        kahunas_removed: Whether the client was removed from Kahunas.

    Returns:
        Summary dict.
    """
    return {
        "client": client_name,
        "uuid": client_uuid,
        "kahunas_removed": kahunas_removed,
        "calendar_appointments_found": appointments_found,
        "calendar_appointments_removed": appointments_removed,
    }


# ── Internal Helpers ──


def _parse_datetime(raw: str) -> datetime:
    """Parse various datetime formats from Kahunas API responses.

    Handles:
        - ISO 8601: 2024-03-15T10:00:00Z, 2024-03-15T10:00:00+00:00
        - Date + time: 2024-03-15 10:00:00, 2024-03-15 10:00
        - Date only: 2024-03-15
        - UK format: 15/03/2024 10:00
    """
    if not raw:
        raise ValueError("Empty datetime string")

    raw = raw.strip()

    # Try ISO 8601 first
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        pass

    # Try common formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue

    raise ValueError(f"Cannot parse datetime: '{raw}'")


def _dt_to_ical(dt: datetime) -> str:
    """Format a datetime as an iCal UTC timestamp (YYYYMMDDTHHMMSSZ)."""
    utc_dt = dt.astimezone(UTC) if dt.tzinfo is not None else dt
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")


def _ical_escape(text: str) -> str:
    """Escape special characters for iCal text fields."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
