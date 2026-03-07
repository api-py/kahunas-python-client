"""Check-in reminder system for Kahunas coaching clients.

Identifies clients who have not submitted a check-in within a
configurable number of days and generates personalised reminder
messages using the persona template system.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .persona import PersonaConfig, build_checkin_reminder

logger = logging.getLogger(__name__)


def find_overdue_clients(
    clients: list[dict[str, Any]],
    checkins_by_client: dict[str, list[dict[str, Any]]],
    days_threshold: int = 7,
    reference: datetime | None = None,
) -> list[dict[str, Any]]:
    """Find clients who haven't checked in within the threshold period.

    Args:
        clients: List of client dicts with 'uuid', 'first_name', 'last_name'.
        checkins_by_client: Dict mapping client UUID to their check-in list.
                           Each check-in should have a 'date' or 'submitted_at' key.
        days_threshold: Number of days since last check-in to consider overdue.
        reference: Reference datetime for comparison (defaults to now UTC).

    Returns:
        List of overdue client dicts sorted by days_overdue (descending), each with:
            uuid, name, last_checkin, days_overdue
    """
    if reference is None:
        reference = datetime.now(UTC)

    overdue: list[dict[str, Any]] = []

    for client in clients:
        uuid = client.get("uuid", "")
        first_name = client.get("first_name", "")
        last_name = client.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip()

        checkins = checkins_by_client.get(uuid, [])
        last_checkin_date = _get_latest_checkin_date(checkins)

        if last_checkin_date is None:
            # No check-ins at all — always overdue
            overdue.append(
                {
                    "uuid": uuid,
                    "name": full_name,
                    "first_name": first_name,
                    "last_checkin": None,
                    "days_overdue": days_threshold,  # At least threshold days
                }
            )
            continue

        days_since = (reference - last_checkin_date).days
        if days_since >= days_threshold:
            overdue.append(
                {
                    "uuid": uuid,
                    "name": full_name,
                    "first_name": first_name,
                    "last_checkin": last_checkin_date.strftime("%Y-%m-%d"),
                    "days_overdue": days_since,
                }
            )

    # Sort by most overdue first
    overdue.sort(key=lambda x: x["days_overdue"], reverse=True)
    return overdue


def build_reminder_message(
    client_name: str,
    days_overdue: int,
    persona_config: PersonaConfig | None = None,
    custom_message: str = "",
) -> str:
    """Generate a personalised check-in reminder message.

    Args:
        client_name: The client's first name.
        days_overdue: Number of days since last check-in.
        persona_config: Optional persona config for tone customisation.
        custom_message: Optional custom message to include.

    Returns:
        Formatted reminder message string.
    """
    if custom_message:
        return custom_message.replace("{name}", client_name).replace("{days}", str(days_overdue))

    return build_checkin_reminder(
        client_name=client_name,
        days_overdue=days_overdue,
        persona=persona_config,
    )


def _get_latest_checkin_date(checkins: list[dict[str, Any]]) -> datetime | None:
    """Extract the most recent check-in date from a list of check-ins.

    Args:
        checkins: List of check-in dicts with 'date' or 'submitted_at' key.

    Returns:
        The latest check-in datetime, or None if no valid dates found.
    """
    latest: datetime | None = None

    for checkin in checkins:
        date_str = checkin.get("date") or checkin.get("submitted_at") or ""
        parsed = _parse_checkin_date(str(date_str))
        if parsed is not None and (latest is None or parsed > latest):
            latest = parsed

    return latest


def _parse_checkin_date(date_str: str) -> datetime | None:
    """Parse a check-in date string to datetime."""
    if not date_str or not date_str.strip():
        return None

    date_str = date_str.strip()
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue

    return None
