"""Phone number alignment between Kahunas client data and WhatsApp format.

Compares phone numbers stored in Kahunas with their normalised WhatsApp
E.164 equivalents to identify mismatches, missing numbers, and correctly
aligned entries. Helps coaches ensure all clients are reachable via WhatsApp.
"""

from __future__ import annotations

import logging
from typing import Any

from .whatsapp import normalise_phone

logger = logging.getLogger(__name__)


def build_phone_alignment_report(
    clients: list[dict[str, Any]],
    country_code: str = "44",
) -> dict[str, Any]:
    """Build a phone alignment report comparing Kahunas vs WhatsApp format.

    For each client, normalises their stored phone number to E.164 and
    categorises it as aligned, mismatched, or missing.

    Args:
        clients: List of client dicts with 'uuid', 'first_name', 'last_name', 'phone' keys.
        country_code: Default country code for normalisation (default: "44" for UK).

    Returns:
        Report dict with:
            aligned: Clients whose stored phone matches normalised format.
            mismatched: Clients whose phone differs from normalised format.
            missing: Clients with no phone number.
            summary: Counts of each category.
    """
    aligned: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for client in clients:
        uuid = client.get("uuid", "")
        first_name = client.get("first_name", "")
        last_name = client.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip()
        raw_phone = client.get("phone", "")

        if not raw_phone or not raw_phone.strip():
            missing.append(
                {
                    "uuid": uuid,
                    "name": full_name,
                    "phone": "",
                    "normalised": "",
                }
            )
            continue

        normalised = normalise_phone(raw_phone, country_code)

        # A phone is "aligned" if the raw value (stripped of common prefixes)
        # already matches the normalised E.164 format
        raw_clean = raw_phone.strip().lstrip("+")
        is_aligned = raw_clean == normalised

        entry = {
            "uuid": uuid,
            "name": full_name,
            "phone": raw_phone,
            "normalised": normalised,
        }

        if is_aligned:
            aligned.append(entry)
        else:
            entry["suggested"] = f"+{normalised}" if normalised else ""
            mismatched.append(entry)

    total = len(clients)
    return {
        "aligned": aligned,
        "mismatched": mismatched,
        "missing": missing,
        "summary": {
            "total": total,
            "aligned": len(aligned),
            "mismatched": len(mismatched),
            "missing": len(missing),
        },
    }
