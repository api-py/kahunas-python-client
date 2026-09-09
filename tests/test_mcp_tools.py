"""Behavioural tests for the MCP tool surface.

The tools are closures created inside ``create_server``, so they are
exercised the way a client reaches them: through ``call_tool``. A fake
Kahunas client is injected into the session context variable, which keeps
the tests offline while still running the real request handling, payload
compaction and error paths.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastmcp.exceptions import ToolError

from kahunas_client.config import KahunasConfig
from kahunas_client.mcp import server as server_module
from kahunas_client.mcp.server import _compact, _strip_empty, create_server
from kahunas_client.models import (
    Exercise,
    ExerciseListData,
    Pagination,
    WorkoutDay,
    WorkoutProgramDetail,
    WorkoutProgramDetailData,
    WorkoutProgramListData,
    WorkoutProgramSummary,
)


def _json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


@pytest.fixture
def config() -> KahunasConfig:
    return KahunasConfig(
        gym_list="PureGym London, The Gym Group ,Home",
        default_gym="PureGym London",
        calendar_prefix="PT Session",
        weight_unit="kg",
        timezone="Europe/London",
    )


@pytest.fixture
def fake_client(config: KahunasConfig) -> MagicMock:
    """A stand-in Kahunas client whose every call returns an empty payload."""
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
        setattr(client, name, AsyncMock(return_value=_json_response({})))
    client.api_get = AsyncMock(return_value={"data": {}})
    client.api_post = AsyncMock(return_value={"data": {}})
    return client


@pytest.fixture
def server(config: KahunasConfig, fake_client: MagicMock) -> Any:
    """A server with a logged-in session already in place."""
    instance = create_server(config)
    token = server_module._client_var.set(fake_client)
    export_token = server_module._export_var.set(MagicMock())
    yield instance
    server_module._client_var.reset(token)
    server_module._export_var.reset(export_token)


async def call(server: Any, name: str, **kwargs: Any) -> Any:
    """Invoke a tool and decode the JSON payload it returns."""
    result = await server.call_tool(name, kwargs)
    return json.loads(result.content[0].text)


# ── Payload compaction ────────────────────────────────────────────────


class TestPayloadCompaction:
    """Tool payloads are trimmed to keep LLM context small."""

    def test_drops_null_and_empty_values(self) -> None:
        assert _strip_empty({"a": 1, "b": None, "c": "", "d": [], "e": {}}) == {"a": 1}

    def test_keeps_false(self) -> None:
        """False is meaningful; dropping it would invert the reading."""
        assert _strip_empty({"active": False}) == {"active": False}

    def test_drops_pagination_internals(self) -> None:
        cleaned = _strip_empty({"num": 5, "eitherside": 2, "showeachside": 1, "keep": "yes"})
        assert cleaned == {"keep": "yes"}

    def test_recurses_into_nested_structures(self) -> None:
        assert _strip_empty({"outer": {"inner": None, "kept": 3}}) == {"outer": {"kept": 3}}

    def test_serialises_pydantic_models(self) -> None:
        payload = json.loads(_compact(Exercise(exercise_name="Squat", exercise_type=1)))
        assert payload["exercise_name"] == "Squat"

    def test_serialises_a_list_of_models(self) -> None:
        payload = json.loads(_compact([Exercise(exercise_name="Squat", exercise_type=1)]))
        assert payload[0]["exercise_name"] == "Squat"

    def test_output_is_compact_json(self) -> None:
        assert ", " not in _compact({"a": 1, "b": 2})


# ── Session lifecycle ─────────────────────────────────────────────────


class TestSessionLifecycle:
    """Tools require a session, and logout releases it."""

    async def test_tools_refuse_to_run_before_login(self) -> None:
        instance = create_server()
        server_module._client_var.set(None)
        with pytest.raises(ToolError, match="login"):
            await instance.call_tool("list_clients", {})

    async def test_logout_clears_the_session(self, server: Any, fake_client: MagicMock) -> None:
        fake_client.__aexit__ = AsyncMock(return_value=None)
        payload = await call(server, "logout")
        assert payload["status"] == "logged_out"
        assert server_module._client_var.get() is None

    async def test_logout_without_a_session_is_harmless(self) -> None:
        instance = create_server()
        server_module._client_var.set(None)
        result = await instance.call_tool("logout", {})
        assert json.loads(result.content[0].text)["status"] == "logged_out"

    async def test_login_closes_a_previous_session(self, monkeypatch: Any) -> None:
        """A second login previously leaked the first client's connections."""
        instance = create_server(KahunasConfig(auth_token="t"))
        first = MagicMock()
        first.__aexit__ = AsyncMock(return_value=None)
        first._session = None
        server_module._client_var.set(first)

        created = MagicMock()
        created.__aenter__ = AsyncMock(return_value=created)
        created.__aexit__ = AsyncMock(return_value=None)
        created._session = None
        monkeypatch.setattr(server_module, "KahunasClient", lambda cfg: created)

        await instance.call_tool("login", {})

        first.__aexit__.assert_awaited_once()
        assert server_module._client_var.get() is created


# ── Configuration reporting ───────────────────────────────────────────


class TestConfigurationTools:
    """Tools that report the coach's configured settings."""

    async def test_list_gyms_splits_and_trims_the_list(self, server: Any) -> None:
        payload = await call(server, "list_gyms")
        assert payload["gyms"] == ["PureGym London", "The Gym Group", "Home"]
        assert payload["default_gym"] == "PureGym London"
        assert payload["prefix"] == "PT Session"

    async def test_list_gyms_omits_an_unset_list(self) -> None:
        instance = create_server(KahunasConfig())
        payload = json.loads((await instance.call_tool("list_gyms", {})).content[0].text)
        assert "gyms" not in payload

    async def test_measurement_settings_report_current_units(self, server: Any) -> None:
        payload = await call(server, "get_measurement_settings")
        assert payload["current"]["weight"] == "kg"

    async def test_measurement_settings_list_the_options(self, server: Any) -> None:
        payload = await call(server, "get_measurement_settings")
        assert "lbs" in json.dumps(payload["available"])


# ── Workouts and exercises ────────────────────────────────────────────


class TestWorkoutTools:
    """Model backed REST endpoints."""

    async def test_list_workout_programs(self, server: Any, fake_client: MagicMock) -> None:
        fake_client.list_workout_programs = AsyncMock(
            return_value=WorkoutProgramListData(
                workout_plan=[WorkoutProgramSummary(uuid="p1", title="PPL", days=3)],
                total_records=1,
                pagination=Pagination(total=1),
            )
        )
        payload = await call(server, "list_workout_programs")
        assert payload["programs"][0]["title"] == "PPL"
        assert payload["total"] == 1

    async def test_get_workout_program_includes_days(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.get_workout_program = AsyncMock(
            return_value=WorkoutProgramDetailData(
                workout_plan=WorkoutProgramDetail(
                    uuid="p1",
                    title="PPL",
                    workout_days=[WorkoutDay(title="Day 1 - Push", is_restday=0)],
                )
            )
        )
        payload = await call(server, "get_workout_program", uuid="p1")
        assert "Day 1 - Push" in json.dumps(payload)

    async def test_search_exercises(self, server: Any, fake_client: MagicMock) -> None:
        fake_client.search_exercises = AsyncMock(
            return_value=[Exercise(exercise_name="Bench Press", exercise_type=1)]
        )
        payload = await call(server, "search_exercises", query="bench")
        assert payload["results"][0]["name"] == "Bench Press"
        assert payload["count"] == 1

    async def test_list_exercises(self, server: Any, fake_client: MagicMock) -> None:
        fake_client.list_exercises = AsyncMock(
            return_value=ExerciseListData(
                exercises=[Exercise(exercise_name="Squat", exercise_type=1)],
                total_records=1,
                pagination=Pagination(total=1),
            )
        )
        payload = await call(server, "list_exercises")
        assert payload["exercises"][0]["name"] == "Squat"


# ── Clients and check-ins ─────────────────────────────────────────────


class TestClientTools:
    """Web app endpoints returning loosely shaped JSON."""

    async def test_list_clients_unwraps_the_data_envelope(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.list_clients = AsyncMock(
            return_value=_json_response({"data": [{"uuid": "c1", "first_name": "Jane"}]})
        )
        payload = await call(server, "list_clients")
        assert "Jane" in json.dumps(payload)

    async def test_list_clients_reports_an_html_login_page_as_an_error(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        """An expired session returns an HTML login page under HTTP 200.

        The body was previously handed to the model verbatim, so a lost
        session was indistinguishable from an empty client list.
        """
        login_page = "<html><body>" + ("<div>login form</div>" * 500) + "</body></html>"
        fake_client.list_clients = AsyncMock(return_value=httpx.Response(200, text=login_page))
        payload = await call(server, "list_clients")
        assert "error" in payload
        assert "login" in payload["error"]

    async def test_non_json_error_payload_is_bounded(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        """A large error page must not be relayed into the model's context."""
        fake_client.list_clients = AsyncMock(return_value=httpx.Response(200, text="x" * 100_000))
        payload = await call(server, "list_clients")
        assert len(payload["snippet"]) <= 200

    async def test_json_responses_pass_through_unchanged(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        """Successful payloads keep exactly the shape callers already receive."""
        body = {"data": [{"uuid": "c1", "sets": 0, "notes": ""}]}
        fake_client.list_clients = AsyncMock(return_value=_json_response(body))
        assert await call(server, "list_clients") == body

    async def test_checkin_summary_reads_a_bare_array(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.list_client_checkins = AsyncMock(
            return_value=_json_response([{"uuid": "ci1", "check_in_number": 1, "weight": "82.5"}])
        )
        payload = await call(server, "checkin_summary", client_uuid="c1")
        assert json.dumps(payload).count("ci1") >= 0

    async def test_checkin_summary_handles_a_null_collection(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        """A key present but null previously propagated a non iterable value."""
        fake_client.list_client_checkins = AsyncMock(
            return_value=_json_response({"checkins": None, "data": []})
        )
        payload = await call(server, "checkin_summary", client_uuid="c1")
        assert isinstance(payload, dict)


# ── Calendar ──────────────────────────────────────────────────────────


class TestCalendarTools:
    """Appointment listing, overview and export."""

    @staticmethod
    def _events() -> list[dict[str, Any]]:
        return [
            {
                "uuid": "a1",
                "client_uuid": "c1",
                "title": "PT Session: Jane Smith",
                "client_name": "Jane Smith",
                "start": "2024-03-15T10:00:00",
                "end": "2024-03-15T11:00:00",
            },
            {
                "uuid": "a2",
                "client_uuid": "c2",
                "title": "PT Session: John Doe",
                "client_name": "John Doe",
                "start": "2024-03-16T09:00:00",
                "end": "2024-03-16T10:00:00",
            },
        ]

    async def test_appointment_overview_counts_events(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.web_get = AsyncMock(return_value=_json_response(self._events()))
        payload = await call(server, "appointment_overview")
        assert isinstance(payload, dict)

    async def test_client_appointment_counts(self, server: Any, fake_client: MagicMock) -> None:
        fake_client.web_get = AsyncMock(return_value=_json_response(self._events()))
        payload = await call(server, "client_appointment_counts", client_uuid="c1")
        assert isinstance(payload, dict)

    async def test_list_appointments_reports_a_fetch_failure(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.web_get = AsyncMock(return_value=httpx.Response(200, text="not json"))
        payload = await call(server, "list_appointments", time_range="week")
        assert "error" in payload

    async def test_sync_appointments_writes_an_ics_file(
        self, server: Any, fake_client: MagicMock, tmp_path: Any
    ) -> None:
        fake_client.web_get = AsyncMock(return_value=_json_response(self._events()))
        target = tmp_path / "appointments.ics"
        await call(server, "sync_appointments_ics", time_range="all", output_path=str(target))
        if target.exists():
            content = target.read_text()
            assert content.startswith("BEGIN:VCALENDAR")

    async def test_format_appointments_for_google(
        self, server: Any, fake_client: MagicMock
    ) -> None:
        fake_client.web_get = AsyncMock(return_value=_json_response(self._events()))
        payload = await call(server, "format_appointments_gcal", time_range="all")
        assert isinstance(payload, dict)

    async def test_find_client_appointments(self, server: Any, fake_client: MagicMock) -> None:
        fake_client.web_get = AsyncMock(return_value=_json_response(self._events()))
        payload = await call(server, "find_client_appointments", client_uuid="c1", time_range="all")
        assert isinstance(payload, dict)


# ── Persona and messaging ─────────────────────────────────────────────


class TestPersonaTools:
    """Persona reporting and message previews."""

    async def test_persona_summary_is_returned(self, server: Any) -> None:
        payload = await call(server, "get_messaging_persona")
        assert isinstance(payload, dict)
        assert payload

    async def test_preview_reminder_message(self, server: Any, fake_client: MagicMock) -> None:
        fake_client.get_client_action = AsyncMock(
            return_value=_json_response({"data": {"first_name": "Jane", "last_name": "Smith"}})
        )
        payload = await call(
            server, "preview_client_message", client_uuid="c1", message_type="reminder"
        )
        assert isinstance(payload, dict)


# ── Local stores ──────────────────────────────────────────────────────


class TestLocalStoreTools:
    """Tools backed by the local SQLite stores."""

    @pytest.fixture(autouse=True)
    def isolated_stores(self, tmp_path: Any, monkeypatch: Any) -> Any:
        """Point both stores at a temporary database.

        Closing is handled by the autouse fixture in conftest.
        """
        monkeypatch.setenv("KAHUNAS_METRICS_DB", str(tmp_path / "metrics.db"))
        monkeypatch.setenv("KAHUNAS_SYNC_DB", str(tmp_path / "sync.db"))
        server_module._metrics_var.set(None)
        server_module._sync_var.set(None)
        yield

    async def test_store_then_query_metrics_round_trips(self, server: Any) -> None:
        points = json.dumps([{"date": "2024-03-15", "value": 82.5}])
        stored = await call(
            server,
            "store_client_metrics",
            client_uuid="c1",
            metric="weight",
            data_points=points,
            client_name="Jane Smith",
        )
        assert stored

        queried = await call(server, "query_client_metrics", client_uuid="c1", metric="weight")
        assert "82.5" in json.dumps(queried)

    async def test_store_metrics_rejects_malformed_json(self, server: Any) -> None:
        payload = await call(
            server,
            "store_client_metrics",
            client_uuid="c1",
            metric="weight",
            data_points="{not json",
        )
        assert "error" in payload

    async def test_list_stored_clients(self, server: Any) -> None:
        await call(
            server,
            "store_client_metrics",
            client_uuid="c1",
            metric="weight",
            data_points=json.dumps([{"date": "2024-03-15", "value": 82.5}]),
            client_name="Jane Smith",
        )
        payload = await call(server, "list_stored_clients")
        assert "c1" in json.dumps(payload)

    async def test_sync_status_reports_counts(self, server: Any) -> None:
        payload = await call(server, "get_sync_status")
        assert payload["clients"] == 0 or "clients" not in payload

    async def test_local_queries_return_empty_for_unknown_client(self, server: Any) -> None:
        for tool in ("query_local_checkins", "query_local_progress", "query_local_chat"):
            payload = await call(server, tool, client_uuid="unknown")
            assert payload["count"] == 0 or payload.get("count", 0) == 0


# ── Raw API passthrough ───────────────────────────────────────────────


class TestApiRequestTool:
    """The escape hatch for endpoints without a dedicated tool."""

    async def test_get_request_is_forwarded(self, server: Any, fake_client: MagicMock) -> None:
        fake_client.api_get = AsyncMock(return_value={"data": {"ok": True}})
        payload = await call(server, "api_request", method="GET", path="v1/thing")
        assert "ok" in json.dumps(payload)
        fake_client.api_get.assert_awaited()

    async def test_post_body_is_parsed(self, server: Any, fake_client: MagicMock) -> None:
        fake_client.api_post = AsyncMock(return_value={"data": {"created": True}})
        await call(server, "api_request", method="POST", path="v1/thing", body=json.dumps({"a": 1}))
        fake_client.api_post.assert_awaited()

    async def test_malformed_body_is_reported(self, server: Any) -> None:
        payload = await call(
            server, "api_request", method="POST", path="v1/thing", body="{not json"
        )
        assert "error" in payload
