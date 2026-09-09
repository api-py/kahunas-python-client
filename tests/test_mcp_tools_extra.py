"""Coverage for the remaining MCP tool groups.

Exercises the web app passthrough tools, WhatsApp messaging, charting,
export, anomaly and reminder tools, and the local sync tools, all against
a fake Kahunas client so nothing reaches the network.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from kahunas_client.config import KahunasConfig
from kahunas_client.mcp import server as server_module
from kahunas_client.mcp.server import create_server


def _json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


@pytest.fixture
def config(tmp_path: Any) -> KahunasConfig:
    return KahunasConfig(
        whatsapp_token="wa-token",
        whatsapp_phone_number_id="123456",
        whatsapp_default_country_code="44",
        checkin_reminder_days=7,
    )


@pytest.fixture
def fake_client(config: KahunasConfig) -> MagicMock:
    client = MagicMock()
    client._config = config
    for name in (
        "list_clients",
        "get_client_action",
        "create_client",
        "list_client_checkins",
        "get_checkin",
        "delete_checkin",
        "compare_checkins",
        "create_habit",
        "complete_habit",
        "list_habits",
        "get_chat_clients",
        "get_chat_messages",
        "send_chat_message",
        "package_action",
        "diet_plan_action",
        "supplement_plan_action",
        "delete_calendar_event",
        "update_configuration",
        "get_chart_data",
        "get_chart_by_exercise",
        "get_workout_log",
        "notify_client",
        "web_get",
        "web_post",
    ):
        setattr(client, name, AsyncMock(return_value=_json_response({"data": []})))
    client.api_get = AsyncMock(return_value={"data": {}})
    client.api_post = AsyncMock(return_value={"data": {}})
    return client


@pytest.fixture
def server(config: KahunasConfig, fake_client: MagicMock, tmp_path: Any, monkeypatch: Any) -> Any:
    monkeypatch.setenv("KAHUNAS_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("KAHUNAS_SYNC_DB", str(tmp_path / "sync.db"))
    monkeypatch.setenv("KAHUNAS_OUTPUT_DIR", str(tmp_path / "output"))
    server_module._metrics_var.set(None)
    server_module._sync_var.set(None)

    instance = create_server(config)
    token = server_module._client_var.set(fake_client)
    export_token = server_module._export_var.set(MagicMock())
    yield instance
    server_module._client_var.reset(token)
    server_module._export_var.reset(export_token)


async def call(server: Any, name: str, **kwargs: Any) -> Any:
    result = await server.call_tool(name, kwargs)
    return json.loads(result.content[0].text)


class TestWebPassthroughTools:
    """Tools that relay a web app response."""

    @pytest.mark.parametrize(
        ("tool", "kwargs"),
        [
            ("get_client", {"client_uuid": "c1"}),
            ("manage_diet_plan", {"action": "list"}),
            ("manage_supplement_plan", {"action": "list"}),
            ("view_checkin", {"checkin_uuid": "ci1"}),
            ("delete_checkin", {"checkin_uuid": "ci1"}),
            ("compare_checkins", {"checkin_uuid": "ci1"}),
            ("create_habit", {"client_uuid": "c1", "title": "Walk"}),
            ("complete_habit", {"habit_uuid": "h1"}),
            ("list_habits", {"client_uuid": "c1"}),
            ("list_chat_contacts", {}),
            ("get_chat_messages", {"client_uuid": "c1"}),
            ("send_chat_message", {"receiver_uuid": "c1", "message": "Hello"}),
            ("manage_package", {"action": "list"}),
            ("delete_calendar_event", {"event_id": "e1"}),
            ("notify_client", {"client_uuid": "c1", "action": "remind"}),
            ("get_workout_log", {"exercise_id": "e1", "client_uuid": "c1"}),
        ],
    )
    async def test_json_response_is_relayed(
        self, server: Any, tool: str, kwargs: dict[str, Any]
    ) -> None:
        payload = await call(server, tool, **kwargs)
        assert payload == {"data": []}

    @pytest.mark.parametrize(
        ("tool", "kwargs"),
        [
            ("get_client", {"client_uuid": "c1"}),
            ("list_habits", {"client_uuid": "c1"}),
            ("get_chat_messages", {"client_uuid": "c1"}),
        ],
    )
    async def test_expired_session_is_reported_not_relayed(
        self, server: Any, fake_client: MagicMock, tool: str, kwargs: dict[str, Any]
    ) -> None:
        """An HTML login page must not be handed back as if it were data."""
        html = "<html><body>Sign in</body></html>"
        for name in ("get_client_action", "list_habits", "get_chat_messages"):
            setattr(fake_client, name, AsyncMock(return_value=httpx.Response(200, text=html)))

        payload = await call(server, tool, **kwargs)
        assert "error" in payload
        assert "login" in payload["error"]

    async def test_update_coach_settings_forwards_the_section(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        await call(server, "update_coach_settings", section="units", settings={"weight": "kg"})
        fake_client.update_configuration.assert_awaited()


class TestWhatsAppTools:
    """Messaging is refused when the integration is unconfigured."""

    async def test_send_message_requires_configuration(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client._config = KahunasConfig()
        payload = await call(server, "whatsapp_send_message", phone="07700900123", message="Hello")
        assert "error" in payload

    async def test_send_message_rejects_an_unusable_number(self, server: Any) -> None:
        """Free text in a client's phone field must not become a recipient."""
        payload = await call(server, "whatsapp_send_message", phone="ask client", message="Hi")
        assert "error" in payload
        assert "Invalid phone" in payload["error"]

    async def test_send_image_rejects_an_unusable_number(self, server: Any) -> None:
        payload = await call(
            server, "whatsapp_send_image", phone="n/a", image_url="https://e.test/a.png"
        )
        assert "error" in payload

    async def test_validate_clients_annotates_readiness(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.list_clients = AsyncMock(
            return_value=_json_response(
                {
                    "data": [
                        {"uuid": "c1", "first_name": "Jane", "phone": "07700 900123"},
                        {"uuid": "c2", "first_name": "John", "phone": "n/a"},
                    ]
                }
            )
        )
        payload = await call(server, "whatsapp_validate_clients")
        body = json.dumps(payload)
        assert "447700900123" in body

    async def test_validate_clients_reports_a_fetch_failure(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.list_clients = AsyncMock(return_value=httpx.Response(200, text="<html>"))
        payload = await call(server, "whatsapp_validate_clients")
        assert "error" in payload


class TestChartTools:
    """Chart generation writes to the private output directory."""

    @staticmethod
    def _points() -> list[dict[str, Any]]:
        return [
            {"date": "2024-01-15", "value": 85.0},
            {"date": "2024-02-15", "value": 83.5},
            {"date": "2024-03-15", "value": 82.0},
        ]

    async def test_generate_progress_chart_returns_a_path(
        self, server: Any, fake_client: MagicMock, tmp_path: Any
    ) -> None:
        fake_client.get_chart_data = AsyncMock(
            return_value=_json_response({"data": self._points()})
        )
        payload = await call(server, "generate_progress_chart", client_uuid="c1", metric="weight")
        assert payload["path"].endswith(".png")
        assert payload["points"] == 3

    async def test_chart_output_is_not_written_to_shared_tmp(
        self, server: Any, fake_client: MagicMock, tmp_path: Any
    ) -> None:
        """Charts carry client names, so the default path must be private."""
        fake_client.get_chart_data = AsyncMock(
            return_value=_json_response({"data": self._points()})
        )
        payload = await call(
            server,
            "generate_progress_chart",
            client_uuid="c1",
            metric="weight",
            client_name="Jane Smith",
        )
        assert "/tmp/kahunas_" not in json.dumps(payload)  # noqa: S108 - asserting absence

    async def test_chart_handles_a_non_json_response(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.get_chart_data = AsyncMock(return_value=httpx.Response(200, text="<html>"))
        payload = await call(server, "generate_progress_chart", client_uuid="c1", metric="weight")
        assert isinstance(payload, dict)

    async def test_exercise_progress_is_relayed(self, server: Any, fake_client: MagicMock) -> None:
        payload = await call(
            server, "get_exercise_progress", exercise_name="Squat", client_uuid="c1"
        )
        assert isinstance(payload, dict)

    async def test_client_progress_is_relayed(self, server: Any) -> None:
        payload = await call(server, "get_client_progress", client_uuid="c1", metric="weight")
        assert isinstance(payload, dict)


class TestExportTools:
    """Export tools delegate to the export manager."""

    async def test_export_client_data(self, server: Any, tmp_path: Any) -> None:
        export = MagicMock()
        export.export_client = AsyncMock(return_value=tmp_path / "Jane Smith")
        server_module._export_var.set(export)
        payload = await call(server, "export_client_data", client_uuid="c1")
        assert "Jane Smith" in json.dumps(payload)
        export.export_client.assert_awaited()

    async def test_export_all_clients(self, server: Any, tmp_path: Any) -> None:
        export = MagicMock()
        export.export_all_clients = AsyncMock(return_value=tmp_path / "all")
        server_module._export_var.set(export)
        await call(server, "export_all_clients")
        export.export_all_clients.assert_awaited()

    async def test_export_exercises(self, server: Any, tmp_path: Any) -> None:
        export = MagicMock()
        export.export_exercise_library = AsyncMock(return_value=tmp_path / "lib.xlsx")
        server_module._export_var.set(export)
        await call(server, "export_exercises")
        export.export_exercise_library.assert_awaited()

    async def test_export_workout_programs(self, server: Any, tmp_path: Any) -> None:
        export = MagicMock()
        export.export_workout_programs = AsyncMock(return_value=tmp_path / "programs")
        server_module._export_var.set(export)
        await call(server, "export_workout_programs")
        export.export_workout_programs.assert_awaited()


class TestReminderAndAnomalyTools:
    """Overdue detection and anomaly scanning."""

    async def test_find_overdue_checkins_with_no_clients(self, server: Any) -> None:
        payload = await call(server, "find_overdue_checkins", days=7)
        assert isinstance(payload, dict)

    async def test_find_overdue_checkins_reports_a_fetch_failure(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.list_clients = AsyncMock(return_value=httpx.Response(200, text="<html>"))
        payload = await call(server, "find_overdue_checkins")
        assert "error" in payload

    async def test_detect_client_anomalies_with_no_checkins(self, server: Any) -> None:
        payload = await call(server, "detect_client_anomalies", client_uuid="c1")
        assert isinstance(payload, dict)

    async def test_scan_all_client_anomalies_reports_a_fetch_failure(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.list_clients = AsyncMock(return_value=httpx.Response(200, text="<html>"))
        payload = await call(server, "scan_all_client_anomalies")
        assert "error" in payload


class TestPhoneAlignmentTools:
    """Comparing Kahunas phone numbers against E.164."""

    async def test_alignment_report(self, server: Any, fake_client: MagicMock) -> None:
        fake_client.list_clients = AsyncMock(
            return_value=_json_response(
                {"data": [{"uuid": "c1", "first_name": "Jane", "phone": "07700 900123"}]}
            )
        )
        payload = await call(server, "phone_alignment_report")
        assert isinstance(payload, dict)

    async def test_alignment_report_reports_a_fetch_failure(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.list_clients = AsyncMock(return_value=httpx.Response(200, text="<html>"))
        payload = await call(server, "phone_alignment_report")
        assert "error" in payload


class TestSyncTools:
    """Local mirror status and queries."""

    async def test_sync_status_on_an_empty_database(self, server: Any) -> None:
        payload = await call(server, "get_sync_status")
        assert isinstance(payload, dict)

    async def test_sync_client_data_records_a_result(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.get_client_action = AsyncMock(
            return_value=_json_response({"data": {"uuid": "c1", "first_name": "Jane"}})
        )
        fake_client.list_client_checkins = AsyncMock(return_value=_json_response({"checkins": []}))
        payload = await call(server, "sync_client_data", client_uuid="c1")
        assert payload["client_uuid"] == "c1"

    async def test_download_pending_media_with_nothing_pending(
        self, server: Any, tmp_path: Any
    ) -> None:
        payload = await call(server, "download_pending_media", output_dir=str(tmp_path / "media"))
        assert payload["photos_downloaded"] == 0 or "photos_downloaded" not in payload
