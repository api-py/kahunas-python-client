"""MCP server exposing Kahunas API as tools (stdio transport)."""

from __future__ import annotations

import base64
import json
import logging
import os
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
        raise RuntimeError("Kahunas client not initialized — call login() first")
    return _client


def _get_export() -> ExportManager:
    if _export is None:
        raise RuntimeError("Export manager not initialized — call login() first")
    return _export


def _compact(data: Any) -> str:
    """Serialize to compact JSON, stripping null/empty/default values.

    Minimises payload size for LLM context windows by removing fields
    that carry no useful information (nulls, empty strings, empty lists,
    zero IDs, internal pagination metadata).
    """
    if hasattr(data, "model_dump"):
        raw = data.model_dump()
    elif isinstance(data, list) and data and hasattr(data[0], "model_dump"):
        raw = [d.model_dump() for d in data]
    else:
        raw = data
    cleaned = _strip_empty(raw)
    return json.dumps(cleaned, default=str, separators=(",", ":"))


def _strip_empty(obj: Any) -> Any:
    """Recursively remove null, empty string, empty list, and zero-value fields."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            # Skip pagination internals and internal IDs that waste tokens
            if k in ("showeachside", "eitherside", "num", "data_range"):
                continue
            cleaned = _strip_empty(v)
            # Keep booleans (even False), non-zero numbers, non-empty strings/lists
            if cleaned is None:
                continue
            if cleaned == "":
                continue
            if isinstance(cleaned, list) and not cleaned:
                continue
            if isinstance(cleaned, dict) and not cleaned:
                continue
            result[k] = cleaned
        return result
    if isinstance(obj, list):
        return [_strip_empty(item) for item in obj]
    return obj


def create_server(config: KahunasConfig | None = None) -> FastMCP:
    """Create and configure the MCP server with all Kahunas tools."""

    mcp = FastMCP(
        "kahunas",
        instructions=(
            "Kahunas fitness coaching platform — manage clients, "
            "workouts, exercises, check-ins, charts, and WhatsApp messaging."
        ),
    )

    # ── Lifecycle ──

    @mcp.tool()
    async def login() -> str:
        """Authenticate with Kahunas. Call this first before using other tools."""
        global _client, _export
        cfg = config or KahunasConfig.from_env()
        client = KahunasClient(cfg)
        await client.__aenter__()
        _client = client
        _export = ExportManager(client)
        return _compact(
            {
                "status": "authenticated",
                "user": client._session.user_name if client._session else "",
                "email": client._session.user_email if client._session else "",
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
        return '{"status":"logged_out"}'

    # ── Workout Programs ──

    @mcp.tool()
    async def list_workout_programs(page: int = 1, per_page: int = 12) -> str:
        """List workout programs. Returns: title, uuid, days count, tags."""
        data = await _get_client().list_workout_programs(page, per_page)
        # Return only essential fields for LLM context
        programs = []
        for p in data.workout_plan:
            programs.append(
                {
                    "title": p.title,
                    "uuid": p.uuid,
                    "days": p.days,
                    "tags": p.tags or None,
                    "assigned": p.assigned_clients or None,
                }
            )
        return _compact(
            {
                "programs": programs,
                "total": data.total_records,
                "page": data.pagination.current_page,
            }
        )

    @mcp.tool()
    async def get_workout_program(uuid: str) -> str:
        """Get full workout program details including all days and exercises."""
        data = await _get_client().get_workout_program(uuid)
        plan = data.workout_plan
        days = []
        for day in plan.workout_days:
            if day.is_restday:
                days.append({"title": day.title, "rest": True})
                continue
            sections: dict[str, Any] = {}
            for section_name in ("warmup", "workout", "cooldown"):
                groups = getattr(day.exercise_list, section_name, [])
                if not groups:
                    continue
                exercises = []
                for group in groups:
                    for ex in group.exercises:
                        e: dict[str, Any] = {"name": ex.exercise_name}
                        if ex.sets:
                            e["sets"] = ex.sets
                        if ex.reps:
                            e["reps"] = ex.reps
                        if ex.rir:
                            e["rir"] = ex.rir
                        if ex.rest_period:
                            e["rest"] = ex.rest_period
                        if ex.tempo:
                            e["tempo"] = ex.tempo
                        if ex.notes:
                            e["notes"] = ex.notes
                        if group.type and group.type != "normal":
                            e["group"] = group.type
                        exercises.append(e)
                sections[section_name] = exercises
            days.append({"title": day.title, **sections})
        return _compact(
            {
                "title": plan.title,
                "uuid": plan.uuid,
                "desc": plan.long_desc or plan.short_desc or None,
                "tags": plan.tags or None,
                "days": days,
            }
        )

    @mcp.tool()
    async def assign_workout_program(program_uuid: str, client_uuid: str) -> str:
        """Assign (replicate) a workout program to a client."""
        result = await _get_client().replicate_workout_program(program_uuid, client_uuid)
        return _compact(result)

    @mcp.tool()
    async def restore_workout_program(uuid: str) -> str:
        """Restore an archived workout program."""
        result = await _get_client().restore_workout_program(uuid)
        return _compact(result)

    # ── Exercises ──

    @mcp.tool()
    async def list_exercises(page: int = 1, per_page: int = 12) -> str:
        """List exercises from the library. Returns: name, type, uuid."""
        data = await _get_client().list_exercises(page, per_page)
        exercises = []
        for ex in data.exercises:
            e: dict[str, Any] = {
                "name": ex.exercise_name or ex.title,
                "uuid": ex.uuid,
                "type": "strength" if ex.exercise_type == 1 else "cardio",
            }
            if ex.tags:
                e["tags"] = ex.tags
            exercises.append(e)
        return _compact(
            {
                "exercises": exercises,
                "total": data.total_records,
                "page": data.pagination.current_page,
            }
        )

    @mcp.tool()
    async def search_exercises(query: str) -> str:
        """Search exercises by name or keyword."""
        results = await _get_client().search_exercises(query)
        exercises = [
            {
                "name": ex.exercise_name or ex.title,
                "uuid": ex.uuid,
                "type": "strength" if ex.exercise_type == 1 else "cardio",
            }
            for ex in results
        ]
        return _compact({"results": exercises, "count": len(exercises)})

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
        data: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
        }
        if phone:
            data["phone"] = phone
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
            {"receiver_uuid": receiver_uuid, "message": message}
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
        """Get progress data for a client (weight, bodyfat, steps, measurements).

        Metrics: weight, bodyfat, steps, chest, waist, hips, arms, thighs.
        Range types: week, month, quarter, year, all.
        """
        resp = await _get_client().get_chart_data(client_uuid, metric, range_type, date_range)
        return resp.text

    @mcp.tool()
    async def get_exercise_progress(
        exercise_name: str,
        client_uuid: str,
        chart_type: str = "",
        filter_val: str = "",
    ) -> str:
        """Get exercise-specific progress data (strength, volume, etc)."""
        resp = await _get_client().get_chart_by_exercise(
            exercise_name, client_uuid, chart_type, filter_val
        )
        return resp.text

    @mcp.tool()
    async def generate_progress_chart(
        client_uuid: str,
        metric: str = "weight",
        time_range: str = "all",
        client_name: str = "",
        output_path: str = "",
    ) -> str:
        """Generate a PNG chart image for a client's progress metric.

        Fetches progress data and renders a chart showing the metric over time.
        Metrics: weight, bodyfat, steps, chest, waist, hips, arms, thighs.
        Time ranges: week, month, quarter, year, all.

        Returns the file path of the saved PNG and base64-encoded image data.
        """
        from ..charts import generate_chart

        # Fetch the data
        resp = await _get_client().get_chart_data(client_uuid, value=metric, range_type=time_range)

        # Parse chart data from response
        data_points: list[dict[str, Any]] = []
        try:
            raw = resp.json()
            if isinstance(raw, list):
                data_points = raw
            elif isinstance(raw, dict):
                data_points = raw.get("data", raw.get("chart_data", []))
                if isinstance(data_points, dict):
                    data_points = []
        except Exception:
            pass

        # Determine output path
        if not output_path:
            safe_name = client_name.replace(" ", "_") or client_uuid[:8]
            output_path = f"/tmp/kahunas_{safe_name}_{metric}_{time_range}.png"

        # Generate the chart
        png_bytes = generate_chart(
            data_points=data_points,
            metric=metric,
            time_range=time_range,
            client_name=client_name,
            output_path=output_path,
        )

        # Return path and base64 for MCP clients that support inline images
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return _compact(
            {
                "path": output_path,
                "metric": metric,
                "range": time_range,
                "points": len(data_points),
                "size_kb": round(len(png_bytes) / 1024, 1),
                "image_base64": b64[:100] + "..." if len(b64) > 100 else b64,
            }
        )

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

    # ── WhatsApp Messaging ──

    @mcp.tool()
    async def whatsapp_send_message(
        phone: str,
        message: str,
    ) -> str:
        """Send a WhatsApp message to a client by phone number.

        Phone can be in any format — it will be normalised automatically.
        Examples: "+447700900123", "07700 900123", "447700900123".

        Requires WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID env vars.
        """
        from ..whatsapp import WhatsAppClient, WhatsAppConfig, normalise_phone

        wa_config = WhatsAppConfig(
            access_token=os.environ.get("WHATSAPP_TOKEN", ""),
            phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
            default_country_code=os.environ.get("WHATSAPP_DEFAULT_COUNTRY_CODE", "44"),
        )
        if not wa_config.is_configured():
            return _compact(
                {
                    "error": "WhatsApp not configured. "
                    "Set WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID."
                }
            )

        normalised = normalise_phone(phone, wa_config.default_country_code)
        if not normalised:
            return _compact({"error": f"Invalid phone number: {phone}"})

        async with WhatsAppClient(wa_config) as wa:
            result = await wa.send_text(normalised, message)
        return _compact({"status": "sent", "to": normalised, "message_id": result})

    @mcp.tool()
    async def whatsapp_send_image(
        phone: str,
        image_url: str,
        caption: str = "",
    ) -> str:
        """Send an image via WhatsApp to a client by phone number.

        The image must be a publicly accessible URL.
        """
        from ..whatsapp import WhatsAppClient, WhatsAppConfig, normalise_phone

        wa_config = WhatsAppConfig(
            access_token=os.environ.get("WHATSAPP_TOKEN", ""),
            phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
            default_country_code=os.environ.get("WHATSAPP_DEFAULT_COUNTRY_CODE", "44"),
        )
        if not wa_config.is_configured():
            return _compact({"error": "WhatsApp not configured."})

        normalised = normalise_phone(phone, wa_config.default_country_code)
        if not normalised:
            return _compact({"error": f"Invalid phone number: {phone}"})

        async with WhatsAppClient(wa_config) as wa:
            result = await wa.send_image(normalised, image_url, caption)
        return _compact({"status": "sent", "to": normalised, "message_id": result})

    @mcp.tool()
    async def whatsapp_validate_clients() -> str:
        """Check which Kahunas clients have valid WhatsApp phone numbers.

        Lists all clients and validates their phone numbers for WhatsApp messaging.
        """
        from ..whatsapp import match_clients_to_whatsapp

        resp = await _get_client().list_clients()
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": "Could not fetch clients"})

        clients_list = []
        if isinstance(data, dict):
            clients_list = data.get("data", data.get("clients", []))
        elif isinstance(data, list):
            clients_list = data

        if not isinstance(clients_list, list):
            return _compact({"error": "Unexpected client data format"})

        country_code = os.environ.get("WHATSAPP_DEFAULT_COUNTRY_CODE", "44")
        annotated = match_clients_to_whatsapp(clients_list, country_code)

        summary = []
        for c in annotated:
            name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
            summary.append(
                {
                    "name": name or c.get("email", "unknown"),
                    "phone": c.get("phone", ""),
                    "whatsapp": c.get("whatsapp_number", ""),
                    "ready": c.get("whatsapp_ready", False),
                }
            )

        ready_count = sum(1 for s in summary if s["ready"])
        return _compact(
            {
                "clients": summary,
                "total": len(summary),
                "whatsapp_ready": ready_count,
            }
        )

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
        return _compact(result)

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
        """Export all data for a client to Excel files."""
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
        return _compact({"status": "exported", "path": str(path)})

    @mcp.tool()
    async def export_all_clients(output_dir: str = "") -> str:
        """Export data for ALL clients to organized Excel files."""
        export = _get_export()
        path = await export.export_all_clients(output_dir=output_dir or None)
        return _compact({"status": "exported", "path": str(path)})

    @mcp.tool()
    async def export_exercises(output_dir: str = "") -> str:
        """Export the full exercise library to an Excel file."""
        export = _get_export()
        path = await export.export_exercise_library(output_dir=output_dir or None)
        return _compact({"status": "exported", "path": str(path)})

    @mcp.tool()
    async def export_workout_programs(output_dir: str = "") -> str:
        """Export all workout programs to Excel files."""
        export = _get_export()
        path = await export.export_workout_programs(output_dir=output_dir or None)
        return _compact({"status": "exported", "path": str(path)})

    return mcp
