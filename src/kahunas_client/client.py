"""Async HTTP client for the Kahunas API."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import KahunasConfig
from .exceptions import (
    AuthenticationError,
    KahunasError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TokenExpiredError,
    ValidationError,
)
from .models import (
    AuthSession,
    Exercise,
    ExerciseListData,
    WorkoutProgramDetailData,
    WorkoutProgramListData,
)

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r'var\s+web_auth_token\s*=\s*["\']([^"\']+)["\']')
_CSRF_RE = re.compile(r'name="csrf_kahunas_token"\s+value="([^"]+)"')
_USER_ID_RE = re.compile(r"const\s+userId\s*=\s*'([^']+)'")
_USER_TYPE_RE = re.compile(r"const\s+userType\s*=\s*'([^']+)'")
_USER_NAME_RE = re.compile(r'const\s+userName\s*=\s*"([^"]+)"')
_USER_EMAIL_RE = re.compile(r"const\s+userEmail\s*=\s*'([^']+)'")


class KahunasClient:
    """Async client for the Kahunas fitness coaching API.

    Supports both the REST API (api.kahunas.io) and web app routes (kahunas.io).
    Handles authentication, automatic token refresh, and retries.

    Usage::

        async with KahunasClient(config) as client:
            programs = await client.list_workout_programs()
    """

    def __init__(self, config: KahunasConfig | None = None) -> None:
        self._config = config or KahunasConfig.from_env()
        self._session: AuthSession | None = None
        self._http: httpx.AsyncClient | None = None
        self._web_http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> KahunasClient:
        self._http = httpx.AsyncClient(
            base_url=self._config.api_base_url,
            timeout=self._config.timeout,
            headers={"Accept": "application/json"},
        )
        self._web_http = httpx.AsyncClient(
            base_url=self._config.web_base_url,
            timeout=self._config.timeout,
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        if self._config.auth_token:
            self._session = AuthSession(auth_token=self._config.auth_token)
        elif self._config.email and self._config.password:
            await self.authenticate()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        if self._web_http:
            await self._web_http.aclose()
            self._web_http = None

    @property
    def is_authenticated(self) -> bool:
        return self._session is not None and bool(self._session.auth_token)

    async def authenticate(self) -> AuthSession:
        """Authenticate via the web app login flow to obtain an API token.

        The Kahunas API uses a custom Auth-User-Token header. Tokens are obtained
        by logging into the web app and extracting the token from the rendered page.
        """
        if not self._config.email or not self._config.password:
            raise AuthenticationError("Email and password required for authentication")

        web = self._web_http
        if not web:
            raise KahunasError("Client not initialized. Use 'async with' context manager.")

        # Step 1: Get login page for CSRF token
        try:
            login_page = await web.get("/login")
        except httpx.ConnectError as exc:
            raise KahunasError(f"Cannot connect to {self._config.web_base_url}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise KahunasError(f"Login page request timed out: {exc}") from exc

        csrf_match = _CSRF_RE.search(login_page.text)
        if not csrf_match:
            raise AuthenticationError("Could not find CSRF token on login page")
        csrf_token = csrf_match.group(1)

        # Step 2: POST login form
        try:
            resp = await web.post(
                "/login",
                data={
                    "csrf_kahunas_token": csrf_token,
                    "identity": self._config.email,
                    "password": self._config.password,
                    "signin": "Login",
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": f"{self._config.web_base_url}/login",
                    "Origin": self._config.web_base_url,
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
                follow_redirects=True,
            )
        except httpx.TimeoutException as exc:
            raise KahunasError(f"Login request timed out: {exc}") from exc

        if "/login" in str(resp.url):
            raise AuthenticationError("Login failed — check email and password")

        # Step 3: Extract auth token from dashboard page
        dashboard_html = resp.text
        if not dashboard_html:
            dashboard_resp = await web.get("/dashboard", follow_redirects=True)
            dashboard_html = dashboard_resp.text

        token_match = _TOKEN_RE.search(dashboard_html)
        if not token_match:
            raise AuthenticationError("Login succeeded but could not extract API auth token")

        auth_token = token_match.group(1)

        # Extract user info
        user_id = ""
        if m := _USER_ID_RE.search(dashboard_html):
            user_id = m.group(1)
        user_type = ""
        if m := _USER_TYPE_RE.search(dashboard_html):
            user_type = m.group(1)
        user_name = ""
        if m := _USER_NAME_RE.search(dashboard_html):
            user_name = m.group(1)
        user_email = ""
        if m := _USER_EMAIL_RE.search(dashboard_html):
            user_email = m.group(1)

        self._session = AuthSession(
            auth_token=auth_token,
            csrf_token=csrf_token,
            user_id=user_id,
            user_type=user_type,
            user_name=user_name,
            user_email=user_email,
        )
        logger.info("Authenticated as %s (%s)", user_name, user_email)
        return self._session

    def _api_headers(self) -> dict[str, str]:
        if not self._session:
            raise AuthenticationError("Not authenticated. Call authenticate() first.")
        return {"Auth-User-Token": self._session.auth_token}

    async def _handle_response(self, resp: httpx.Response) -> dict[str, Any]:
        """Parse and validate an API response, handling token refresh."""
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "5")
            raise RateLimitError(f"Rate limited by API (retry after {retry_after}s)", code=429)
        if resp.status_code >= 500:
            raise ServerError(f"Server error: {resp.status_code}", code=resp.status_code)

        # Guard against non-JSON responses (HTML error pages, redirects)
        content_type = resp.headers.get("content-type", "")
        if "application/json" not in content_type and resp.status_code != 200:
            raise KahunasError(
                f"Unexpected response (status={resp.status_code}, "
                f"type={content_type[:50]}): {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise KahunasError(f"Invalid JSON response: {resp.text[:200]}") from exc

        # Handle token expiration with automatic re-auth
        if data.get("token_expired") and not data.get("updated_token"):
            if self._config.email and self._config.password:
                logger.info("Token expired, re-authenticating...")
                await self.authenticate()
                raise TokenExpiredError("Token expired and was refreshed — retry the request")
            raise TokenExpiredError("Token expired. Provide credentials for auto re-auth.")

        # Handle updated token
        if data.get("updated_token") and self._session:
            self._session.auth_token = data["updated_token"]
            logger.debug("Auth token refreshed from response")

        if resp.status_code == 404 or data.get("code") == 404:
            raise NotFoundError(data.get("message", "Not found"), code=404)
        if resp.status_code == 422 or data.get("code") == 422:
            raise ValidationError(
                data.get("message", "Validation error"),
                errors=data.get("errors", []),
                code=422,
            )
        if not data.get("success", True) and data.get("status") == -3:
            raise TokenExpiredError(data.get("message", "Token expired"))

        return data

    @retry(
        retry=retry_if_exception_type(
            (RateLimitError, ServerError, TokenExpiredError, httpx.ConnectError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _api_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the REST API."""
        if not self._http:
            raise KahunasError("Client not initialized")
        try:
            resp = await self._http.request(
                method, f"/{path}", params=params, json=json_data, headers=self._api_headers()
            )
        except httpx.TimeoutException as exc:
            raise ServerError(f"Request timed out: {method} {path}") from exc
        return await self._handle_response(resp)

    @retry(
        retry=retry_if_exception_type((RateLimitError, ServerError, httpx.ConnectError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _web_request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Make a request to the web app (session-based).

        Web endpoints require session cookies from the login flow.
        Token-only auth does not provide the session cookies needed
        for web app endpoints — use email/password authentication
        for full access.
        """
        if not self._web_http:
            raise KahunasError("Client not initialized")
        headers: dict[str, str] = {}
        if self._session:
            if data is None:
                data = {}
            data.setdefault("csrf_kahunas_token", self._session.csrf_token)
            headers["Auth-User-Token"] = self._session.auth_token
        try:
            return await self._web_http.request(
                method, path, data=data, params=params, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise ServerError(f"Web request timed out: {method} {path}") from exc

    # ── REST API: Workout Programs ──

    async def list_workout_programs(
        self, page: int = 1, per_page: int = 12
    ) -> WorkoutProgramListData:
        """List all workout programs."""
        resp = await self._api_request(
            "GET", "v1/workoutprogram", params={"page": page, "per_page": per_page}
        )
        return WorkoutProgramListData.model_validate(resp.get("data", {}))

    async def get_workout_program(self, uuid: str) -> WorkoutProgramDetailData:
        """Get a single workout program with full details."""
        resp = await self._api_request("GET", f"v1/workoutprogram/{uuid}")
        return WorkoutProgramDetailData.model_validate(resp.get("data", {}))

    async def replicate_workout_program(self, uuid: str, client_uuid: str) -> dict[str, Any]:
        """Replicate/assign a workout program to a client."""
        resp = await self._api_request(
            "POST",
            "v1/workoutprogram/replicate",
            json_data={"uuid": uuid, "client_uuid": client_uuid},
        )
        return resp.get("data", {})

    async def restore_workout_program(self, uuid: str) -> dict[str, Any]:
        """Restore an archived workout program."""
        resp = await self._api_request(
            "POST", "v1/workoutprogram/restoreprogram", json_data={"uuid": uuid}
        )
        return resp.get("data", {})

    # ── REST API: Exercises ──

    async def list_exercises(self, page: int = 1, per_page: int = 12) -> ExerciseListData:
        """List exercises from the exercise library."""
        resp = await self._api_request(
            "GET", "v1/exercise", params={"page": page, "per_page": per_page}
        )
        return ExerciseListData.model_validate(resp.get("data", {}))

    async def search_exercises(self, query: str) -> list[Exercise]:
        """Search exercises by keyword."""
        resp = await self._api_request("GET", "v1/exercise/search", params={"search": query})
        data = resp.get("data", [])
        if isinstance(data, list):
            return [Exercise.model_validate(e) for e in data]
        return []

    # ── Web App: Clients ──

    async def list_clients(self) -> httpx.Response:
        """List all clients via the web app."""
        return await self._web_request("POST", "/coach/client_ajax")

    async def create_client(self, client_data: dict[str, Any]) -> httpx.Response:
        """Create a new client."""
        return await self._web_request("POST", "/coach/clients/create", data=client_data)

    async def get_client_action(self, action: str, client_id: str, **kwargs: Any) -> httpx.Response:
        """Perform a client action (view, edit, delete, etc)."""
        return await self._web_request(
            "POST", "/coach/clientAction", data={"action": action, "id": client_id, **kwargs}
        )

    # ── Web App: Diet / Nutrition ──

    async def diet_plan_action(self, action: str, plan_id: str = "") -> httpx.Response:
        """Perform a diet plan action."""
        return await self._web_request(
            "POST", "/coach/dietPlansAction", data={"action": action, "id": plan_id}
        )

    async def supplement_plan_action(self, action: str, plan_id: str = "") -> httpx.Response:
        """Perform a supplement plan action."""
        return await self._web_request(
            "POST", "/coach/supplementPlansAction", data={"action": action, "id": plan_id}
        )

    # ── Web App: Check-ins ──

    async def get_checkin(self, checkin_uuid: str) -> httpx.Response:
        """View a specific check-in."""
        return await self._web_request("GET", f"/client/checkin/check_in_view/{checkin_uuid}")

    async def delete_checkin(self, checkin_uuid: str) -> httpx.Response:
        """Delete a check-in."""
        return await self._web_request("GET", f"/client/checkin/check_in_delete/{checkin_uuid}")

    async def compare_checkins(self, checkin_uuid: str) -> httpx.Response:
        """Compare check-in data."""
        return await self._web_request("GET", f"/client/checkin/compar_check_in/{checkin_uuid}")

    # ── Web App: Habits ──

    async def create_habit(self, data: dict[str, Any]) -> httpx.Response:
        """Create a new habit for a client."""
        return await self._web_request("POST", "/client/habits/create/", data=data)

    async def complete_habit(self, data: dict[str, Any]) -> httpx.Response:
        """Mark a habit as complete."""
        return await self._web_request("POST", "/client/habits/complete/", data=data)

    async def list_habits(self, client_uuid: str, date: str = "") -> httpx.Response:
        """List habits for a client."""
        return await self._web_request(
            "POST",
            "/client/habits/views",
            data={"client": client_uuid, "date": date, "action": "list"},
        )

    # ── Web App: Chat ──

    async def get_chat_clients(self, keyword: str = "") -> httpx.Response:
        """Get list of chat clients."""
        return await self._web_request("POST", "/chat/getclients", data={"keyword": keyword})

    async def get_chat_messages(self, receiver_uuid: str, last_id: int = 0) -> httpx.Response:
        """Get chat messages with a client."""
        return await self._web_request(
            "POST",
            "/chat/getChatMessages",
            data={"receiver_uuid": receiver_uuid, "uuid": receiver_uuid, "last_id": last_id},
        )

    async def send_chat_message(self, data: dict[str, Any]) -> httpx.Response:
        """Send a chat message."""
        return await self._web_request("POST", "/chat/sendMessage", data=data)

    # ── Web App: Packages ──

    async def package_action(
        self, action: str, package_id: str = "", **kwargs: Any
    ) -> httpx.Response:
        """Perform a package action (list, create, update, delete)."""
        return await self._web_request(
            "POST", "/packageAction", data={"action": action, "id": package_id, **kwargs}
        )

    # ── Web App: Calendar ──

    async def delete_calendar_event(self, event_id: str) -> httpx.Response:
        """Delete a calendar event."""
        return await self._web_request(
            "POST", f"/calendar/global_calendar_delete_events/{event_id}"
        )

    # ── Web App: Configuration ──

    async def update_configuration(self, section: str, data: dict[str, Any]) -> httpx.Response:
        """Update coach configuration settings."""
        return await self._web_request("POST", f"/coach/configurationAction/{section}", data=data)

    # ── Web App: Charts / Progress ──

    async def get_chart_data(
        self, client_uuid: str, value: str = "", range_type: str = "", data_range: str = ""
    ) -> httpx.Response:
        """Get chart/progress data for a client.

        Metrics: weight, bodyfat, steps, chest, waist, hips, arms, thighs.
        Range types: week, month, quarter, year, all.
        """
        return await self._web_request(
            "GET",
            f"/client/chartData/{client_uuid}",
            params={"value": value, "rangeType": range_type, "range": data_range},
        )

    async def get_chart_by_exercise(
        self, exercise_name: str, client_id: str, chart_type: str = "", filter_val: str = ""
    ) -> httpx.Response:
        """Get exercise-specific chart data."""
        return await self._web_request(
            "POST",
            "/client/chartbyexercise",
            data={
                "excname": exercise_name,
                "clientid": client_id,
                "chart_type": chart_type,
                "filter": filter_val,
            },
        )

    # ── Web App: Workout Logs ──

    async def get_workout_log(
        self, exercise_id: str, client_id: str, filter_val: str = ""
    ) -> httpx.Response:
        """Get workout log book for an exercise."""
        return await self._web_request(
            "POST",
            "/client/client_workout_log_book",
            data={"exercise_id": exercise_id, "clientid": client_id, "filter": filter_val},
        )

    # ── Web App: Notifications ──

    async def notify_client(self, action: str, client_id: str) -> httpx.Response:
        """Send a notification to a client."""
        return await self._web_request(
            "POST", "/coach/notifyClient", data={"action": action, "id": client_id}
        )

    # ── Generic raw request ──

    async def api_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make an authenticated GET request to any API endpoint."""
        return await self._api_request("GET", path, params=params)

    async def api_post(self, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make an authenticated POST request to any API endpoint."""
        return await self._api_request("POST", path, json_data=data)

    async def web_get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """Make a GET request to any web app endpoint."""
        return await self._web_request("GET", path, params=params)

    async def web_post(self, path: str, data: dict[str, Any] | None = None) -> httpx.Response:
        """Make a POST request to any web app endpoint."""
        return await self._web_request("POST", path, data=data)
