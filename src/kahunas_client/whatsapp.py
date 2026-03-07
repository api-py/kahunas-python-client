"""WhatsApp Business API integration for Kahunas.

Enables sending messages (text and attachments) to coaching clients
via the WhatsApp Business Cloud API. Matches Kahunas clients to
WhatsApp contacts by normalised phone number.

Configuration:
    Set these environment variables or pass via KahunasConfig/WhatsAppConfig:
    - WHATSAPP_TOKEN: Meta Cloud API access token
    - WHATSAPP_PHONE_NUMBER_ID: Your WhatsApp Business phone number ID
    - WHATSAPP_DEFAULT_COUNTRY_CODE: Default country code (default: "44" for UK)
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_GRAPH_API = "https://graph.facebook.com/v21.0"

# Chars to strip when normalising a phone number
_STRIP_RE = re.compile(r"[\s\-\(\)\.]+")


class WhatsAppConfig:
    """Configuration for WhatsApp Business API."""

    def __init__(
        self,
        access_token: str = "",
        phone_number_id: str = "",
        default_country_code: str = "44",
        api_version: str = "v21.0",
    ) -> None:
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.default_country_code = default_country_code
        self.api_version = api_version

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    @property
    def messages_url(self) -> str:
        return f"{self.base_url}/{self.phone_number_id}/messages"

    def is_configured(self) -> bool:
        return bool(self.access_token and self.phone_number_id)


def normalise_phone(phone: str, default_country_code: str = "44") -> str:
    """Normalise a phone number to E.164 format for WhatsApp matching.

    Handles UK numbers (+44), international formats, and common variations.
    Returns the number without the leading '+' (WhatsApp API format).

    Examples:
        "07700 900123"       -> "447700900123"
        "+44 7700 900123"    -> "447700900123"
        "0044 7700 900123"   -> "447700900123"
        "+1 (555) 123-4567"  -> "15551234567"
        "7700900123"         -> "447700900123"  (assumes UK)
        ""                   -> ""
    """
    if not phone:
        return ""

    # Strip whitespace, dashes, parentheses, dots
    clean = _STRIP_RE.sub("", phone.strip())

    if not clean:
        return ""

    # Handle + prefix
    if clean.startswith("+"):
        return clean[1:]  # remove the + for WhatsApp API format

    # Handle 00 international prefix (e.g., 0044...)
    if clean.startswith("00"):
        return clean[2:]

    # Handle leading 0 (local number, e.g., UK 07700...)
    if clean.startswith("0"):
        return default_country_code + clean[1:]

    # If it already looks international (starts with country code digits)
    # For UK, numbers without leading 0 that start with 7 are mobile
    if default_country_code == "44" and clean.startswith("7") and len(clean) == 10:
        return "44" + clean

    # Already normalised or unknown format — return as-is
    return clean


def phones_match(phone_a: str, phone_b: str, default_country_code: str = "44") -> bool:
    """Check if two phone numbers refer to the same WhatsApp contact.

    Normalises both numbers and compares. Resilient to formatting differences.
    """
    norm_a = normalise_phone(phone_a, default_country_code)
    norm_b = normalise_phone(phone_b, default_country_code)
    if not norm_a or not norm_b:
        return False
    return norm_a == norm_b


class WhatsAppClient:
    """Client for the WhatsApp Business Cloud API.

    Usage::

        wa = WhatsAppClient(config)
        await wa.send_text("447700900123", "Hello from your coach!")
    """

    def __init__(self, config: WhatsAppConfig) -> None:
        self._config = config
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> WhatsAppClient:
        self._http = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self._config.access_token}",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    def _ensure_http(self) -> httpx.AsyncClient:
        if not self._http:
            raise RuntimeError("WhatsAppClient not initialized. Use 'async with' context manager.")
        return self._http

    async def send_text(self, to: str, body: str) -> dict[str, Any]:
        """Send a text message to a WhatsApp number.

        Args:
            to: Recipient phone in E.164 without '+' (e.g., "447700900123").
            body: Message text.

        Returns:
            WhatsApp API response dict with message ID.
        """
        http = self._ensure_http()
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        resp = await http.post(self._config.messages_url, json=payload)
        return self._handle_response(resp)

    async def send_image(self, to: str, image_url: str, caption: str = "") -> dict[str, Any]:
        """Send an image message via URL.

        Args:
            to: Recipient phone in E.164 without '+'.
            image_url: Public URL of the image.
            caption: Optional image caption.
        """
        http = self._ensure_http()
        image_obj: dict[str, Any] = {"link": image_url}
        if caption:
            image_obj["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "image",
            "image": image_obj,
        }
        resp = await http.post(self._config.messages_url, json=payload)
        return self._handle_response(resp)

    async def send_document(
        self,
        to: str,
        document_url: str,
        filename: str = "document",
        caption: str = "",
    ) -> dict[str, Any]:
        """Send a document/file via URL.

        Args:
            to: Recipient phone in E.164 without '+'.
            document_url: Public URL of the document.
            filename: Display filename.
            caption: Optional caption.
        """
        http = self._ensure_http()
        doc_obj: dict[str, Any] = {"link": document_url, "filename": filename}
        if caption:
            doc_obj["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "document",
            "document": doc_obj,
        }
        resp = await http.post(self._config.messages_url, json=payload)
        return self._handle_response(resp)

    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str = "en_GB",
        components: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a pre-approved template message.

        Args:
            to: Recipient phone in E.164 without '+'.
            template_name: Approved template name.
            language_code: Template language (default: en_GB).
            components: Template variable components.
        """
        http = self._ensure_http()
        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template["components"] = components
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": template,
        }
        resp = await http.post(self._config.messages_url, json=payload)
        return self._handle_response(resp)

    @staticmethod
    def _handle_response(resp: httpx.Response) -> dict[str, Any]:
        """Parse WhatsApp API response, raising on errors."""
        try:
            data = resp.json()
        except Exception:
            data = {"error": {"message": resp.text[:300], "code": resp.status_code}}

        if resp.status_code >= 400:
            err = data.get("error", {})
            msg = err.get("message", f"HTTP {resp.status_code}")
            code = err.get("code", resp.status_code)
            raise WhatsAppError(f"WhatsApp API error ({code}): {msg}")

        return data


class WhatsAppError(Exception):
    """Raised when the WhatsApp Business API returns an error."""


def match_clients_to_whatsapp(
    clients: list[dict[str, Any]],
    default_country_code: str = "44",
) -> list[dict[str, Any]]:
    """Annotate a list of Kahunas clients with normalised WhatsApp numbers.

    Adds 'whatsapp_number' (normalised E.164) and 'whatsapp_ready' (bool)
    to each client dict. A client is WhatsApp-ready if they have a
    valid-looking mobile number.

    Args:
        clients: List of client dicts with 'phone' field.
        default_country_code: Country code for numbers without prefix.

    Returns:
        Same list with added whatsapp_number and whatsapp_ready fields.
    """
    for client in clients:
        phone = client.get("phone", "")
        normalised = normalise_phone(phone, default_country_code)
        client["whatsapp_number"] = normalised
        # A valid mobile number should be at least 10 digits
        client["whatsapp_ready"] = len(normalised) >= 10
    return clients
