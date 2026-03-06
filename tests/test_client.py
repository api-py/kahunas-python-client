"""Tests for the KahunasClient async HTTP client."""

from __future__ import annotations

import httpx
import pytest
import respx

from kahunas_client.client import KahunasClient
from kahunas_client.config import KahunasConfig
from kahunas_client.exceptions import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TokenExpiredError,
)


@pytest.fixture
def config() -> KahunasConfig:
    return KahunasConfig(
        api_base_url="https://api.kahunas.io/api",
        web_base_url="https://kahunas.io",
        auth_token="test-token-abc123",
    )


# ── Authentication ──


class TestAuthentication:
    @respx.mock(base_url="https://kahunas.io")
    async def test_authenticate_success(self, respx_mock: respx.MockRouter) -> None:
        cfg = KahunasConfig(
            api_base_url="https://api.kahunas.io/api",
            web_base_url="https://kahunas.io",
            email="test@test.com",
            password="pass123",
            auth_token="",
        )

        login_html = '<input name="csrf_kahunas_token" value="csrf-tok-123">'
        dashboard_html = """
        var web_auth_token = "real-auth-token-xyz";
        const userId = 'user-uuid-123';
        const userType = 'coach';
        const userName = "Test Coach";
        const userEmail = 'test@test.com';
        """

        respx_mock.get("/login").mock(return_value=httpx.Response(200, text=login_html))
        respx_mock.post("/login").mock(
            return_value=httpx.Response(302, headers={"location": "https://kahunas.io/dashboard"})
        )
        respx_mock.get("/dashboard").mock(return_value=httpx.Response(200, text=dashboard_html))

        async with KahunasClient(cfg) as client:
            assert client.is_authenticated
            assert client._session is not None
            assert client._session.auth_token == "real-auth-token-xyz"
            assert client._session.user_name == "Test Coach"
            assert client._session.user_id == "user-uuid-123"

    @respx.mock(base_url="https://kahunas.io")
    async def test_authenticate_bad_credentials(self, respx_mock: respx.MockRouter) -> None:
        cfg = KahunasConfig(
            api_base_url="https://api.kahunas.io/api",
            web_base_url="https://kahunas.io",
            email="bad@test.com",
            password="wrong",
            auth_token="",
        )

        login_html = '<input name="csrf_kahunas_token" value="csrf-tok">'
        respx_mock.get("/login").mock(return_value=httpx.Response(200, text=login_html))
        respx_mock.post("/login").mock(
            return_value=httpx.Response(
                200, text="redirected", headers={"location": "https://kahunas.io/login"}
            )
        )

        with pytest.raises(AuthenticationError, match="Login failed"):
            async with KahunasClient(cfg) as _client:
                pass

    async def test_authenticate_no_credentials(self) -> None:
        cfg = KahunasConfig(
            api_base_url="https://api.kahunas.io/api",
            web_base_url="https://kahunas.io",
            email="",
            password="",
            auth_token="",
        )
        # Should succeed but not be authenticated
        async with KahunasClient(cfg) as client:
            assert not client.is_authenticated

    async def test_pre_set_token(self, config: KahunasConfig) -> None:
        async with KahunasClient(config) as client:
            assert client.is_authenticated
            assert client._session is not None
            assert client._session.auth_token == "test-token-abc123"


# ── API Requests ──


class TestApiRequests:
    @respx.mock(base_url="https://api.kahunas.io/api")
    async def test_list_workout_programs(
        self, config: KahunasConfig, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get("/v1/workoutprogram").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "workout_plan": [
                            {
                                "uuid": "prog-1",
                                "title": "Push Pull Legs",
                                "days": 6,
                                "assigned_clients": 2,
                            },
                        ],
                        "total_records": 1,
                        "pagination": {"total": 1, "current_page": 1},
                    },
                },
            )
        )

        async with KahunasClient(config) as client:
            result = await client.list_workout_programs()
            assert result.total_records == 1
            assert len(result.workout_plan) == 1
            assert result.workout_plan[0].title == "Push Pull Legs"

    @respx.mock(base_url="https://api.kahunas.io/api")
    async def test_get_workout_program(
        self, config: KahunasConfig, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get("/v1/workoutprogram/prog-1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "workout_plan": {
                            "uuid": "prog-1",
                            "title": "Test Program",
                            "workout_days": [
                                {
                                    "uuid": "day-1",
                                    "title": "Push A",
                                    "is_restday": 0,
                                    "exercise_list": {
                                        "warmup": [],
                                        "workout": [
                                            {
                                                "type": "normal",
                                                "list": [
                                                    {
                                                        "exercise_name": "Bench Press",
                                                        "exercise_type": 1,
                                                        "sets": "4",
                                                        "reps": "8-12",
                                                        "rest_period": 120,
                                                        "media": [
                                                            {
                                                                "uuid": "m1",
                                                                "parent_type": None,
                                                                "file_url": "https://example.com/v",
                                                                "file_type": 1,
                                                                "created_at": None,
                                                            }
                                                        ],
                                                        "tags": ["chest"],
                                                    }
                                                ],
                                            }
                                        ],
                                        "cooldown": [],
                                    },
                                },
                            ],
                        },
                    },
                },
            )
        )

        async with KahunasClient(config) as client:
            result = await client.get_workout_program("prog-1")
            assert result.workout_plan.title == "Test Program"
            assert len(result.workout_plan.workout_days) == 1
            day = result.workout_plan.workout_days[0]
            assert len(day.exercise_list.workout) == 1
            ex = day.exercise_list.workout[0].exercises[0]
            assert ex.exercise_name == "Bench Press"
            assert ex.sets == "4"
            assert ex.reps == "8-12"
            assert ex.media[0].parent_type is None

    @respx.mock(base_url="https://api.kahunas.io/api")
    async def test_list_exercises(
        self, config: KahunasConfig, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get("/v1/exercise").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "exercises": [
                            {
                                "uuid": "ex-1",
                                "title": "Bench Press",
                                "exercise_name": "Bench Press",
                                "exercise_type": 1,
                                "sets": None,
                                "reps": None,
                                "tags": ["chest"],
                                "media": [
                                    {
                                        "uuid": "m1",
                                        "parent_type": 0,
                                        "file_url": "https://example.com/v",
                                        "file_type": 1,
                                        "created_at": "28th Sep 2023",
                                    },
                                    {
                                        "uuid": "",
                                        "parent_type": 4,
                                        "file_url": "https://example.com/thumb.jpg",
                                        "file_type": 2,
                                        "created_at": None,
                                    },
                                ],
                            },
                        ],
                        "total_records": 1,
                        "pagination": {"total": 1},
                    },
                },
            )
        )

        async with KahunasClient(config) as client:
            result = await client.list_exercises()
            assert result.total_records == 1
            assert result.exercises[0].exercise_name == "Bench Press"
            assert len(result.exercises[0].media) == 2
            assert result.exercises[0].media[1].created_at is None

    @respx.mock(base_url="https://api.kahunas.io/api")
    async def test_search_exercises(
        self, config: KahunasConfig, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get("/v1/exercise/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {"uuid": "ex-1", "exercise_name": "Squat", "exercise_type": 1},
                    ],
                },
            )
        )

        async with KahunasClient(config) as client:
            result = await client.search_exercises("squat")
            assert len(result) == 1
            assert result[0].exercise_name == "Squat"


# ── Error Handling ──


class TestErrorHandling:
    @respx.mock(base_url="https://api.kahunas.io/api")
    async def test_404_raises_not_found(
        self, config: KahunasConfig, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get("/v1/workoutprogram/bad-uuid").mock(
            return_value=httpx.Response(
                200, json={"success": False, "code": 404, "message": "Not found"}
            )
        )

        async with KahunasClient(config) as client:
            with pytest.raises(NotFoundError):
                await client.get_workout_program("bad-uuid")

    @respx.mock(base_url="https://api.kahunas.io/api")
    async def test_429_raises_rate_limit(
        self, config: KahunasConfig, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get("/v1/exercise").mock(
            return_value=httpx.Response(429, json={"message": "Rate limited"})
        )

        async with KahunasClient(config) as client:
            with pytest.raises(RateLimitError):
                await client.list_exercises()

    @respx.mock(base_url="https://api.kahunas.io/api")
    async def test_500_raises_server_error(
        self, config: KahunasConfig, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get("/v1/exercise").mock(
            return_value=httpx.Response(500, json={"message": "Internal error"})
        )

        async with KahunasClient(config) as client:
            with pytest.raises(ServerError):
                await client.list_exercises()

    @respx.mock(base_url="https://api.kahunas.io/api")
    async def test_token_refresh(self, config: KahunasConfig, respx_mock: respx.MockRouter) -> None:
        """Token refresh via updated_token in response."""
        respx_mock.get("/v1/exercise").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "updated_token": "new-refreshed-token",
                    "data": {"exercises": [], "total_records": 0, "pagination": {}},
                },
            )
        )

        async with KahunasClient(config) as client:
            await client.list_exercises()
            assert client._session is not None
            assert client._session.auth_token == "new-refreshed-token"

    @respx.mock(base_url="https://api.kahunas.io/api")
    async def test_token_expired_triggers_reauth(
        self, config: KahunasConfig, respx_mock: respx.MockRouter
    ) -> None:
        """Token expiry with no updated_token raises TokenExpiredError."""
        respx_mock.get("/v1/exercise").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": False,
                    "token_expired": 1,
                    "data": None,
                },
            )
        )

        config.email = ""
        config.password = ""
        async with KahunasClient(config) as client:
            with pytest.raises(TokenExpiredError):
                await client.list_exercises()


# ── Web Requests ──


class TestWebRequests:
    @respx.mock(base_url="https://kahunas.io")
    async def test_list_clients(self, config: KahunasConfig, respx_mock: respx.MockRouter) -> None:
        respx_mock.post("/coach/client_ajax").mock(
            return_value=httpx.Response(200, json={"data": [{"uuid": "c1", "first_name": "John"}]})
        )

        async with KahunasClient(config) as client:
            resp = await client.list_clients()
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["data"]) == 1

    @respx.mock(base_url="https://kahunas.io")
    async def test_get_chat_messages(
        self, config: KahunasConfig, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.post("/chat/getChatMessages").mock(
            return_value=httpx.Response(200, json={"messages": [{"id": 1, "message": "Hello"}]})
        )

        async with KahunasClient(config) as client:
            resp = await client.get_chat_messages("client-uuid")
            assert resp.status_code == 200

    @respx.mock(base_url="https://kahunas.io")
    async def test_list_habits(self, config: KahunasConfig, respx_mock: respx.MockRouter) -> None:
        respx_mock.post("/client/habits/views").mock(
            return_value=httpx.Response(
                200, json={"habits": [{"uuid": "h1", "title": "Drink water"}]}
            )
        )

        async with KahunasClient(config) as client:
            resp = await client.list_habits("client-uuid")
            assert resp.status_code == 200
