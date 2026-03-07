"""Tests for WhatsApp Business API integration."""

from __future__ import annotations

import pytest

from kahunas_client.whatsapp import (
    WhatsAppClient,
    WhatsAppConfig,
    WhatsAppError,
    match_clients_to_whatsapp,
    normalise_phone,
    phones_match,
)


class TestNormalisePhone:
    """Test phone number normalisation for WhatsApp matching."""

    def test_uk_mobile_with_leading_zero(self) -> None:
        assert normalise_phone("07700900123") == "447700900123"

    def test_uk_mobile_with_spaces(self) -> None:
        assert normalise_phone("07700 900 123") == "447700900123"

    def test_uk_with_country_code_plus(self) -> None:
        assert normalise_phone("+447700900123") == "447700900123"

    def test_uk_with_country_code_plus_spaces(self) -> None:
        assert normalise_phone("+44 7700 900123") == "447700900123"

    def test_uk_with_double_zero_prefix(self) -> None:
        assert normalise_phone("00447700900123") == "447700900123"

    def test_uk_with_double_zero_and_spaces(self) -> None:
        assert normalise_phone("0044 7700 900 123") == "447700900123"

    def test_uk_mobile_without_prefix(self) -> None:
        # 10-digit UK number starting with 7 (mobile)
        assert normalise_phone("7700900123") == "447700900123"

    def test_us_number(self) -> None:
        assert normalise_phone("+1 (555) 123-4567") == "15551234567"

    def test_number_with_dashes(self) -> None:
        assert normalise_phone("07700-900-123") == "447700900123"

    def test_number_with_dots(self) -> None:
        assert normalise_phone("07700.900.123") == "447700900123"

    def test_number_with_parentheses(self) -> None:
        assert normalise_phone("(07700) 900123") == "447700900123"

    def test_empty_string(self) -> None:
        assert normalise_phone("") == ""

    def test_whitespace_only(self) -> None:
        assert normalise_phone("   ") == ""

    def test_already_normalised(self) -> None:
        assert normalise_phone("447700900123") == "447700900123"

    def test_non_uk_default_country(self) -> None:
        # US as default country code
        assert normalise_phone("0555123456", default_country_code="1") == "1555123456"

    def test_international_number_keeps_prefix(self) -> None:
        assert normalise_phone("+33612345678") == "33612345678"

    def test_short_number_passthrough(self) -> None:
        # Very short numbers pass through unchanged
        assert normalise_phone("12345") == "12345"


class TestPhonesMatch:
    """Test phone number matching."""

    def test_same_number_different_format(self) -> None:
        assert phones_match("+447700900123", "07700 900 123")

    def test_same_normalised(self) -> None:
        assert phones_match("447700900123", "447700900123")

    def test_different_numbers(self) -> None:
        assert not phones_match("+447700900123", "+447700900456")

    def test_empty_number_no_match(self) -> None:
        assert not phones_match("", "+447700900123")
        assert not phones_match("+447700900123", "")

    def test_both_empty(self) -> None:
        assert not phones_match("", "")

    def test_local_vs_international(self) -> None:
        assert phones_match("07700900123", "00447700900123")


class TestWhatsAppConfig:
    """Test WhatsApp configuration."""

    def test_is_configured_when_both_set(self) -> None:
        config = WhatsAppConfig(access_token="tok", phone_number_id="123")
        assert config.is_configured()

    def test_not_configured_when_missing_token(self) -> None:
        config = WhatsAppConfig(phone_number_id="123")
        assert not config.is_configured()

    def test_not_configured_when_missing_phone_id(self) -> None:
        config = WhatsAppConfig(access_token="tok")
        assert not config.is_configured()

    def test_default_country_code_uk(self) -> None:
        config = WhatsAppConfig()
        assert config.default_country_code == "44"

    def test_messages_url(self) -> None:
        config = WhatsAppConfig(phone_number_id="12345")
        assert config.messages_url == "https://graph.facebook.com/v21.0/12345/messages"


class TestMatchClientsToWhatsapp:
    """Test client-to-WhatsApp matching."""

    def test_annotates_clients_with_valid_phone(self) -> None:
        clients = [
            {"first_name": "John", "last_name": "Doe", "phone": "07700900123"},
            {"first_name": "Jane", "last_name": "Smith", "phone": "+447700900456"},
        ]
        result = match_clients_to_whatsapp(clients)
        assert result[0]["whatsapp_number"] == "447700900123"
        assert result[0]["whatsapp_ready"] is True
        assert result[1]["whatsapp_number"] == "447700900456"
        assert result[1]["whatsapp_ready"] is True

    def test_client_without_phone(self) -> None:
        clients = [{"first_name": "No", "last_name": "Phone", "phone": ""}]
        result = match_clients_to_whatsapp(clients)
        assert result[0]["whatsapp_number"] == ""
        assert result[0]["whatsapp_ready"] is False

    def test_client_with_short_number(self) -> None:
        clients = [{"first_name": "Short", "last_name": "Number", "phone": "123"}]
        result = match_clients_to_whatsapp(clients)
        assert result[0]["whatsapp_ready"] is False

    def test_custom_country_code(self) -> None:
        clients = [{"first_name": "US", "last_name": "Client", "phone": "0555123456"}]
        result = match_clients_to_whatsapp(clients, default_country_code="1")
        assert result[0]["whatsapp_number"] == "1555123456"

    def test_missing_phone_key(self) -> None:
        clients = [{"first_name": "No", "last_name": "Key"}]
        result = match_clients_to_whatsapp(clients)
        assert result[0]["whatsapp_number"] == ""
        assert result[0]["whatsapp_ready"] is False


class TestWhatsAppClient:
    """Test WhatsApp client message formatting."""

    @pytest.mark.asyncio
    async def test_send_text_requires_context_manager(self) -> None:
        config = WhatsAppConfig(access_token="tok", phone_number_id="123")
        client = WhatsAppClient(config)
        with pytest.raises(RuntimeError, match="not initialized"):
            await client.send_text("447700900123", "Hello")

    def test_handle_response_error(self) -> None:
        """Test that error responses raise WhatsAppError."""
        import httpx

        resp = httpx.Response(
            400,
            json={"error": {"message": "Invalid token", "code": 190}},
            request=httpx.Request("POST", "https://example.com"),
        )
        with pytest.raises(WhatsAppError, match="Invalid token"):
            WhatsAppClient._handle_response(resp)

    def test_handle_response_success(self) -> None:
        """Test that success responses return parsed data."""
        import httpx

        resp = httpx.Response(
            200,
            json={"messages": [{"id": "wamid.123"}]},
            request=httpx.Request("POST", "https://example.com"),
        )
        result = WhatsAppClient._handle_response(resp)
        assert result["messages"][0]["id"] == "wamid.123"
