"""MCP server exposing Kahunas API as tools (stdio transport)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import FastMCP

from ..client import KahunasClient
from ..config import KahunasConfig
from .export import ExportManager

logger = logging.getLogger(__name__)

_client: KahunasClient | None = None
_export: ExportManager | None = None


def _get_client() -> KahunasClient:
    if _client is None:
        raise RuntimeError("Kahunas client not initialized")
    return _client


def _get_export() -> ExportManager:
    if _export is None:
        raise RuntimeError("Export manager not initialized")
    return _export


def _json_result(data: Any) -> str:
    """Serialize result to JSON string for MCP."""
    if hasattr(data, "model_dump"):
        return json.dumps(data.model_dump(), default=str, indent=2)
    if isinstance(data, list) and data and hasattr(data[0], "model_dump"):
        return json.dumps([d.model_dump() for d in data], default=str, indent=2)
    return json.dumps(data, default=str, indent=2)


def create_server(config: KahunasConfig | None = None) -> FastMCP:
    """Create and configure the MCP server with all Kahunas tools."""

    mcp = FastMCP(
        "kahunas",
        instructions=(
            "Kahunas fitness coaching platform — manage clients, "
            "workouts, exercises, check-ins, and more."
        ),
    )

    # ── Lifecycle ──

    @mcp.tool()
    async def login() -> str:
        """Authenticate with Kahunas. Call this first."""
        global _client, _export
        cfg = config or KahunasConfig.from_env()
        _client = KahunasClient(cfg)
        await _client.__aenter__()
        _export = ExportManager(_client)
        return json.dumps(
            {
                "status": "authenticated",
                "user": _client._session.user_name if _client._session else "",
                "email": _client._session.user_email if _client._session else "",
            }
        )

    @mcp.tool()
    async def logout() -> str:
        """Close the Kahunas session."""
        global _client, _export
        if _client:
            await _client.__aexit__(None, None, None)
            _client = None
            _export = None
        return '{"status": "logged_out"}'

    # ── Workout Programs ──

    @mcp.tool()
    async def list_workout_programs(page: int = 1, per_page: int = 12) -> str:
        """List all workout programs with pagination."""
        result = await _get_client().list_workout_programs(page, per_page)
        return _json_result(result)

    @mcp.tool()
    async def get_workout_program(uuid: str) -> str:
        """Get full details of a workout program including all days and exercises."""
        result = await _get_client().get_workout_program(uuid)
        return _json_result(result)

    @mcp.tool()
    async def assign_workout_program(program_uuid: str, client_uuid: str) -> str:
        """Assign (replicate) a workout program to a client."""
        result = await _get_client().replicate_workout_program(program_uuid, client_uuid)
        return _json_result(result)

    @mcp.tool()
    async def restore_workout_program(uuid: str) -> str:
        """Restore an archived workout program."""
        result = await _get_client().restore_workout_program(uuid)
        return _json_result(result)

    # ── Exercises ──

    @mcp.tool()
    async def list_exercises(page: int = 1, per_page: int = 12) -> str:
        """List exercises from the exercise library."""
        result = await _get_client().list_exercises(page, per_page)
        return _json_result(result)

    @mcp.tool()
    async def search_exercises(query: str) -> str:
        """Search exercises by name or keyword."""
        result = await _get_client().search_exercises(query)
        return _json_result(result)

    # ── Clients ──

    @mcp.tool()
    async def list_clients() -> str:
        """List all coaching clients."""
        resp = await _get_client().list_clients()
        return resp.text

    @mcp.tool()
    async def create_client(
        first_name: str,
        last_name: str,
        email: str,
        phone: str = "",
        package_uuid: str = "",
    ) -> str:
        """Create a new coaching client."""
        data = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
        }
        if package_uuid:
            data["package_uuid"] = package_uuid
        resp = await _get_client().create_client(data)
        return resp.text

    @mcp.tool()
    async def get_client(client_uuid: str, action: str = "view") -> str:
        """Get client details. Actions: view, edit, delete, suspend, activate."""
        resp = await _get_client().get_client_action(action, client_uuid)
        return resp.text

    # ── Diet & Supplements ──

    @mcp.tool()
    async def manage_diet_plan(action: str, plan_id: str = "") -> str:
        """Manage diet plans. Actions: list, view, create, update, delete."""
        resp = await _get_client().diet_plan_action(action, plan_id)
        return resp.text

    @mcp.tool()
    async def manage_supplement_plan(action: str, plan_id: str = "") -> str:
        """Manage supplement plans. Actions: list, view, create, update, delete."""
        resp = await _get_client().supplement_plan_action(action, plan_id)
        return resp.text

    # ── Check-ins ──

    @mcp.tool()
    async def view_checkin(checkin_uuid: str) -> str:
        """View a client check-in with all submitted data."""
        resp = await _get_client().get_checkin(checkin_uuid)
        return resp.text

    @mcp.tool()
    async def delete_checkin(checkin_uuid: str) -> str:
        """Delete a client check-in."""
        resp = await _get_client().delete_checkin(checkin_uuid)
        return resp.text

    @mcp.tool()
    async def compare_checkins(checkin_uuid: str) -> str:
        """Compare check-in data over time."""
        resp = await _get_client().compare_checkins(checkin_uuid)
        return resp.text

    # ── Habits ──

    @mcp.tool()
    async def create_habit(client_uuid: str, title: str) -> str:
        """Create a new habit for a client."""
        resp = await _get_client().create_habit({"client": client_uuid, "title": title})
        return resp.text

    @mcp.tool()
    async def complete_habit(habit_uuid: str) -> str:
        """Mark a habit as completed."""
        resp = await _get_client().complete_habit({"uuid": habit_uuid})
        return resp.text

    @mcp.tool()
    async def list_habits(client_uuid: str, date: str = "") -> str:
        """List habits for a client on a given date."""
        resp = await _get_client().list_habits(client_uuid, date)
        return resp.text

    # ── Chat ──

    @mcp.tool()
    async def list_chat_contacts(keyword: str = "") -> str:
        """List clients available for chat, optionally filtered by keyword."""
        resp = await _get_client().get_chat_clients(keyword)
        return resp.text

    @mcp.tool()
    async def get_chat_messages(client_uuid: str, last_id: int = 0) -> str:
        """Get chat messages with a client. Use last_id for pagination."""
        resp = await _get_client().get_chat_messages(client_uuid, last_id)
        return resp.text

    @mcp.tool()
    async def send_chat_message(receiver_uuid: str, message: str) -> str:
        """Send a chat message to a client."""
        resp = await _get_client().send_chat_message(
            {
                "receiver_uuid": receiver_uuid,
                "message": message,
            }
        )
        return resp.text

    # ── Packages ──

    @mcp.tool()
    async def manage_package(action: str, package_id: str = "") -> str:
        """Manage coaching packages. Actions: list, view, create, update, delete."""
        resp = await _get_client().package_action(action, package_id)
        return resp.text

    # ── Calendar ──

    @mcp.tool()
    async def delete_calendar_event(event_id: str) -> str:
        """Delete a calendar event."""
        resp = await _get_client().delete_calendar_event(event_id)
        return resp.text

    # ── Configuration ──

    @mcp.tool()
    async def update_coach_settings(section: str, settings: dict[str, Any]) -> str:
        """Update coach configuration settings for a section."""
        resp = await _get_client().update_configuration(section, settings)
        return resp.text

    # ── Progress & Charts ──

    @mcp.tool()
    async def get_client_progress(
        client_uuid: str,
        metric: str = "",
        range_type: str = "",
        date_range: str = "",
    ) -> str:
        """Get progress chart data for a client (weight, body fat, measurements, etc)."""
        resp = await _get_client().get_chart_data(client_uuid, metric, range_type, date_range)
        return resp.text

    @mcp.tool()
    async def get_exercise_progress(
        exercise_name: str,
        client_uuid: str,
        chart_type: str = "",
        filter_val: str = "",
    ) -> str:
        """Get exercise-specific progress chart data (strength progression, volume, etc)."""
        resp = await _get_client().get_chart_by_exercise(
            exercise_name, client_uuid, chart_type, filter_val
        )
        return resp.text

    # ── Workout Logs ──

    @mcp.tool()
    async def get_workout_log(
        exercise_id: str,
        client_uuid: str,
        filter_val: str = "",
    ) -> str:
        """Get the workout log book for an exercise and client."""
        resp = await _get_client().get_workout_log(exercise_id, client_uuid, filter_val)
        return resp.text

    # ── Notifications ──

    @mcp.tool()
    async def notify_client(client_uuid: str, action: str) -> str:
        """Send a notification to a client."""
        resp = await _get_client().notify_client(action, client_uuid)
        return resp.text

    # ── Raw API Access ──

    @mcp.tool()
    async def api_request(method: str, path: str, params: str = "", body: str = "") -> str:
        """Make a raw API request. Params and body should be JSON strings."""
        client = _get_client()
        parsed_params = json.loads(params) if params else None
        parsed_body = json.loads(body) if body else None
        if method.upper() == "GET":
            result = await client.api_get(path, params=parsed_params)
        else:
            result = await client.api_post(path, data=parsed_body)
        return _json_result(result)

    # ── Export Tools ──

    @mcp.tool()
    async def export_client_data(
        client_uuid: str,
        output_dir: str = "",
        include_photos: bool = True,
        include_checkins: bool = True,
        include_progress: bool = True,
        include_workouts: bool = True,
        include_habits: bool = True,
        include_chat: bool = True,
    ) -> str:
        """Export all data for a client to Excel files with organized directory structure.

        Creates a directory with the client's name containing:
        - profile.xlsx — Client profile and account info
        - checkins/ — Check-in data and progress photos
        - workouts/ — Workout programs and exercise logs
        - progress/ — Progress charts and body measurements
        - habits/ — Habit tracking history
        - chat/ — Chat message history
        - photos/ — All progress and check-in photos

        Returns the path to the export directory.
        """
        export = _get_export()
        path = await export.export_client(
            client_uuid=client_uuid,
            output_dir=output_dir or None,
            include_photos=include_photos,
            include_checkins=include_checkins,
            include_progress=include_progress,
            include_workouts=include_workouts,
            include_habits=include_habits,
            include_chat=include_chat,
        )
        return json.dumps({"status": "exported", "path": str(path)})

    @mcp.tool()
    async def export_all_clients(output_dir: str = "") -> str:
        """Export data for ALL clients to organized Excel files.

        Creates a top-level directory with subdirectories per client.
        Each client folder follows the same structure as export_client_data.

        Returns the path to the export directory.
        """
        export = _get_export()
        path = await export.export_all_clients(output_dir=output_dir or None)
        return json.dumps({"status": "exported", "path": str(path)})

    @mcp.tool()
    async def export_exercises(output_dir: str = "") -> str:
        """Export the full exercise library to an Excel file.

        Returns the path to the exported file.
        """
        export = _get_export()
        path = await export.export_exercise_library(output_dir=output_dir or None)
        return json.dumps({"status": "exported", "path": str(path)})

    @mcp.tool()
    async def export_workout_programs(output_dir: str = "") -> str:
        """Export all workout programs to Excel files.

        Each program gets its own file with sheets per training day.
        Returns the path to the export directory.
        """
        export = _get_export()
        path = await export.export_workout_programs(output_dir=output_dir or None)
        return json.dumps({"status": "exported", "path": str(path)})

    return mcp
