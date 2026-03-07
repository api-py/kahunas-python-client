"""Tests for the check-in reminders module."""

from __future__ import annotations

from datetime import UTC, datetime

from kahunas_client.checkin_reminders import (
    build_reminder_message,
    find_overdue_clients,
)
from kahunas_client.persona import PersonaConfig

# ── find_overdue_clients ──


class TestFindOverdueClients:
    """Tests for identifying overdue clients."""

    def _make_client(self, uuid: str, first: str, last: str = "") -> dict:
        return {"uuid": uuid, "first_name": first, "last_name": last}

    def _ref(self, days_ago: int = 0) -> datetime:
        return datetime(2025, 3, 15, 12, 0, 0, tzinfo=UTC)

    def test_finds_overdue_client(self) -> None:
        clients = [self._make_client("u1", "Alice")]
        checkins = {"u1": [{"date": "2025-03-01"}]}  # 14 days ago
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert len(result) == 1
        assert result[0]["uuid"] == "u1"
        assert result[0]["days_overdue"] == 14

    def test_respects_threshold(self) -> None:
        clients = [self._make_client("u1", "Alice")]
        checkins = {"u1": [{"date": "2025-03-12"}]}  # 3 days ago
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert result == []

    def test_client_with_no_checkins(self) -> None:
        clients = [self._make_client("u1", "Bob")]
        checkins: dict = {}
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert len(result) == 1
        assert result[0]["last_checkin"] is None

    def test_no_overdue_clients(self) -> None:
        clients = [self._make_client("u1", "Alice")]
        checkins = {"u1": [{"date": "2025-03-14"}]}  # 1 day ago
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert result == []

    def test_sorts_by_days_overdue_desc(self) -> None:
        clients = [
            self._make_client("u1", "Alice"),
            self._make_client("u2", "Bob"),
            self._make_client("u3", "Charlie"),
        ]
        checkins = {
            "u1": [{"date": "2025-03-05"}],  # 10 days
            "u2": [{"date": "2025-02-15"}],  # 28 days
            "u3": [{"date": "2025-03-01"}],  # 14 days
        }
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert len(result) == 3
        assert result[0]["uuid"] == "u2"  # Most overdue
        assert result[1]["uuid"] == "u3"
        assert result[2]["uuid"] == "u1"

    def test_custom_reference_date(self) -> None:
        clients = [self._make_client("u1", "Alice")]
        checkins = {"u1": [{"date": "2025-01-01"}]}
        ref = datetime(2025, 1, 10, 12, 0, 0, tzinfo=UTC)
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=ref)
        assert len(result) == 1
        assert result[0]["days_overdue"] == 9

    def test_checked_in_today(self) -> None:
        clients = [self._make_client("u1", "Alice")]
        checkins = {"u1": [{"date": "2025-03-15"}]}
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert result == []

    def test_exactly_at_threshold(self) -> None:
        clients = [self._make_client("u1", "Alice")]
        checkins = {"u1": [{"date": "2025-03-08"}]}  # Exactly 7 days ago
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert len(result) == 1

    def test_multiple_checkins_uses_latest(self) -> None:
        clients = [self._make_client("u1", "Alice")]
        checkins = {
            "u1": [
                {"date": "2025-01-01"},  # Old
                {"date": "2025-03-14"},  # Recent
                {"date": "2025-02-01"},  # Also old
            ]
        }
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert result == []  # Latest is only 1 day ago

    def test_submitted_at_key(self) -> None:
        clients = [self._make_client("u1", "Alice")]
        checkins = {"u1": [{"submitted_at": "2025-03-01"}]}
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert len(result) == 1

    def test_result_includes_first_name(self) -> None:
        clients = [self._make_client("u1", "Alice", "Smith")]
        checkins = {"u1": [{"date": "2025-03-01"}]}
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert result[0]["first_name"] == "Alice"
        assert result[0]["name"] == "Alice Smith"

    def test_result_includes_last_checkin_date(self) -> None:
        clients = [self._make_client("u1", "Alice")]
        checkins = {"u1": [{"date": "2025-03-01"}]}
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        assert result[0]["last_checkin"] == "2025-03-01"

    def test_empty_clients_list(self) -> None:
        result = find_overdue_clients([], {}, days_threshold=7, reference=self._ref())
        assert result == []

    def test_invalid_date_format_treated_as_no_checkin(self) -> None:
        clients = [self._make_client("u1", "Alice")]
        checkins = {"u1": [{"date": "not-a-date"}]}
        result = find_overdue_clients(clients, checkins, days_threshold=7, reference=self._ref())
        # Invalid date → no valid checkin found → treated as no check-ins
        assert len(result) == 1


# ── build_reminder_message ──


class TestBuildReminderMessage:
    """Tests for reminder message generation."""

    def test_default_message_contains_name(self) -> None:
        msg = build_reminder_message("Alice", 7)
        assert "Alice" in msg

    def test_default_message_contains_days(self) -> None:
        msg = build_reminder_message("Bob", 14)
        assert "14" in msg

    def test_custom_message_substitution(self) -> None:
        custom = "Hi {name}, it's been {days} days. Please check in!"
        msg = build_reminder_message("Charlie", 10, custom_message=custom)
        assert "Charlie" in msg
        assert "10" in msg

    def test_custom_message_takes_priority(self) -> None:
        custom = "Custom: {name}"
        msg = build_reminder_message("Diana", 5, custom_message=custom)
        assert msg == "Custom: Diana"

    def test_with_persona_config(self) -> None:
        persona = PersonaConfig(
            weight_deviation_pct=10.0,
            sleep_minimum=6.0,
            step_minimum=8000,
        )
        msg = build_reminder_message("Eve", 7, persona_config=persona)
        assert "Eve" in msg
        assert "7" in msg

    def test_message_includes_check_in_request(self) -> None:
        msg = build_reminder_message("Frank", 7)
        assert "check-in" in msg.lower()

    def test_message_has_coach_sign_off(self) -> None:
        msg = build_reminder_message("Grace", 7)
        assert "Your Coach" in msg
