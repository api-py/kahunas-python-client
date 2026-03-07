"""Tests for the phone alignment module."""

from __future__ import annotations

from kahunas_client.phone_alignment import build_phone_alignment_report


class TestBuildPhoneAlignmentReport:
    """Tests for phone alignment reporting."""

    def test_empty_client_list(self) -> None:
        result = build_phone_alignment_report([])
        assert result["aligned"] == []
        assert result["mismatched"] == []
        assert result["missing"] == []
        assert result["summary"]["total"] == 0

    def test_aligned_e164_number(self) -> None:
        clients = [
            {"uuid": "u1", "first_name": "Alice", "last_name": "Smith", "phone": "447700900123"}
        ]
        result = build_phone_alignment_report(clients)
        assert len(result["aligned"]) == 1
        assert result["aligned"][0]["name"] == "Alice Smith"
        assert result["aligned"][0]["normalised"] == "447700900123"

    def test_mismatched_local_format(self) -> None:
        clients = [
            {"uuid": "u2", "first_name": "Bob", "last_name": "Jones", "phone": "07700 900123"}
        ]
        result = build_phone_alignment_report(clients)
        assert len(result["mismatched"]) == 1
        assert result["mismatched"][0]["normalised"] == "447700900123"
        assert result["mismatched"][0]["suggested"] == "+447700900123"

    def test_missing_phone(self) -> None:
        clients = [{"uuid": "u3", "first_name": "Charlie", "last_name": "Brown", "phone": ""}]
        result = build_phone_alignment_report(clients)
        assert len(result["missing"]) == 1
        assert result["missing"][0]["name"] == "Charlie Brown"

    def test_missing_phone_none_field(self) -> None:
        clients = [{"uuid": "u4", "first_name": "Diana", "last_name": "Prince"}]
        result = build_phone_alignment_report(clients)
        assert len(result["missing"]) == 1

    def test_whitespace_only_phone(self) -> None:
        clients = [{"uuid": "u5", "first_name": "Eve", "last_name": "Adams", "phone": "   "}]
        result = build_phone_alignment_report(clients)
        assert len(result["missing"]) == 1

    def test_custom_country_code(self) -> None:
        clients = [
            {"uuid": "u6", "first_name": "Frank", "last_name": "Miller", "phone": "0555123456"}
        ]
        result = build_phone_alignment_report(clients, country_code="1")
        assert len(result["mismatched"]) == 1
        assert result["mismatched"][0]["normalised"] == "1555123456"

    def test_international_number_with_plus(self) -> None:
        clients = [
            {"uuid": "u7", "first_name": "Grace", "last_name": "Lee", "phone": "+447700900123"}
        ]
        result = build_phone_alignment_report(clients)
        assert len(result["aligned"]) == 1
        assert result["aligned"][0]["normalised"] == "447700900123"

    def test_international_with_00_prefix(self) -> None:
        clients = [
            {
                "uuid": "u8",
                "first_name": "Hans",
                "last_name": "Schmidt",
                "phone": "0044 7700 900123",
            }
        ]
        result = build_phone_alignment_report(clients)
        assert len(result["mismatched"]) == 1
        assert result["mismatched"][0]["normalised"] == "447700900123"

    def test_summary_counts(self) -> None:
        clients = [
            {"uuid": "u1", "first_name": "A", "last_name": "B", "phone": "447700900001"},
            {"uuid": "u2", "first_name": "C", "last_name": "D", "phone": "07700 900002"},
            {"uuid": "u3", "first_name": "E", "last_name": "F", "phone": ""},
            {"uuid": "u4", "first_name": "G", "last_name": "H", "phone": "447700900004"},
        ]
        result = build_phone_alignment_report(clients)
        assert result["summary"]["total"] == 4
        assert result["summary"]["aligned"] == 2
        assert result["summary"]["mismatched"] == 1
        assert result["summary"]["missing"] == 1

    def test_mismatched_entry_has_suggested(self) -> None:
        clients = [{"uuid": "u1", "first_name": "A", "last_name": "B", "phone": "07700 900123"}]
        result = build_phone_alignment_report(clients)
        entry = result["mismatched"][0]
        assert "suggested" in entry
        assert entry["suggested"].startswith("+")

    def test_aligned_entry_has_no_suggested(self) -> None:
        clients = [{"uuid": "u1", "first_name": "A", "last_name": "B", "phone": "447700900123"}]
        result = build_phone_alignment_report(clients)
        entry = result["aligned"][0]
        assert "suggested" not in entry

    def test_preserves_uuid(self) -> None:
        clients = [
            {"uuid": "test-uuid-123", "first_name": "A", "last_name": "B", "phone": "447700900123"}
        ]
        result = build_phone_alignment_report(clients)
        assert result["aligned"][0]["uuid"] == "test-uuid-123"

    def test_name_concatenation(self) -> None:
        clients = [{"uuid": "u1", "first_name": "John", "last_name": "Doe", "phone": ""}]
        result = build_phone_alignment_report(clients)
        assert result["missing"][0]["name"] == "John Doe"

    def test_single_name(self) -> None:
        clients = [{"uuid": "u1", "first_name": "Madonna", "last_name": "", "phone": ""}]
        result = build_phone_alignment_report(clients)
        assert result["missing"][0]["name"] == "Madonna"

    def test_multiple_clients_mixed(self) -> None:
        clients = [
            {"uuid": "u1", "first_name": "Aligned", "last_name": "One", "phone": "447700900001"},
            {"uuid": "u2", "first_name": "Mismatched", "last_name": "Two", "phone": "07700 900002"},
            {"uuid": "u3", "first_name": "Missing", "last_name": "Three", "phone": ""},
        ]
        result = build_phone_alignment_report(clients)
        assert result["summary"]["total"] == 3
        assert result["summary"]["aligned"] == 1
        assert result["summary"]["mismatched"] == 1
        assert result["summary"]["missing"] == 1

    def test_us_number_with_country_code(self) -> None:
        clients = [
            {"uuid": "u1", "first_name": "US", "last_name": "Client", "phone": "15551234567"}
        ]
        result = build_phone_alignment_report(clients, country_code="1")
        assert len(result["aligned"]) == 1

    def test_parenthesised_number(self) -> None:
        clients = [{"uuid": "u1", "first_name": "A", "last_name": "B", "phone": "(07700) 900123"}]
        result = build_phone_alignment_report(clients)
        assert len(result["mismatched"]) == 1
        assert result["mismatched"][0]["normalised"] == "447700900123"
