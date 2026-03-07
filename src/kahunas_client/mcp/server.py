"""MCP server exposing Kahunas API as tools (stdio transport)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from ..anomaly_detection import parse_thresholds, scan_client_anomalies
from ..checkin_reminders import build_reminder_message, find_overdue_clients
from ..client import KahunasClient
from ..config import KahunasConfig
from ..metrics_store import (
    MEASUREMENT_SETTINGS,
    MetricsStore,
    get_metrics_with_units,
)
from ..metrics_store import (
    METRICS as METRIC_DEFINITIONS,
)
from ..pdf_export import (
    export_checkin_summary_pdf,
    export_workout_plan_pdf,
    export_workout_program_pdf,
)
from ..persona import PersonaConfig, build_anomaly_warning, get_persona_summary
from ..phone_alignment import build_phone_alignment_report
from .export import ExportManager

logger = logging.getLogger(__name__)

_client: KahunasClient | None = None
_export: ExportManager | None = None
_metrics: MetricsStore | None = None

# Constants to avoid string duplication (SonarQube S1192)
_CALENDAR_EVENTS_PATH = "/coach/getCalendarEvents"
_CALENDAR_FETCH_ERROR = "Could not fetch calendar events"


def _get_client() -> KahunasClient:
    if _client is None:
        raise RuntimeError("Kahunas client not initialized — call login() first")
    return _client


def _get_export() -> ExportManager:
    if _export is None:
        raise RuntimeError("Export manager not initialized — call login() first")
    return _export


def _get_metrics() -> MetricsStore:
    global _metrics
    if _metrics is None:
        _metrics = MetricsStore()
    return _metrics


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
            "workouts, exercises, check-ins, charts, WhatsApp messaging, "
            "and calendar sync (Google Calendar / Apple iCal)."
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
        global _client, _export, _metrics
        if _client:
            await _client.__aexit__(None, None, None)
            _client = None
            _export = None
        if _metrics:
            _metrics.close()
            _metrics = None
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

    @mcp.tool()
    async def checkin_summary(client_uuid: str, client_name: str = "") -> str:
        """Get a tabular check-in history summary for a client.

        Returns a structured table of all check-ins with body measurements
        (weight, waist, hips, biceps, thighs) and lifestyle ratings
        (sleep, nutrition, water, workouts, stress, energy, mood).

        Similar to the Check In History table on the Kahunas dashboard.
        Includes trend analysis showing changes between check-ins.

        Units are automatically configured from your measurement settings
        (KAHUNAS_WEIGHT_UNIT, KAHUNAS_HEIGHT_UNIT).
        """
        from ..checkin_history import format_checkin_summary

        cfg = config or KahunasConfig.from_env()

        # Fetch client data (includes check-ins)
        resp = await _get_client().list_client_checkins(client_uuid)
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": "Could not parse check-in data", "raw": resp.text[:200]})

        # Extract check-ins from response
        checkins: list[dict[str, Any]] = []
        if isinstance(data, dict):
            checkins = data.get("checkins", data.get("check_ins", data.get("data", [])))
            if isinstance(checkins, dict):
                checkins = checkins.get("checkins", checkins.get("check_ins", []))
        elif isinstance(data, list):
            checkins = data

        if not checkins:
            return _compact(
                {
                    "client_uuid": client_uuid,
                    "client_name": client_name or None,
                    "total_checkins": 0,
                    "message": "No check-ins found for this client",
                }
            )

        measurement_unit = "inches" if cfg.height_unit == "inches" else "cm"
        summary = format_checkin_summary(
            checkins,
            client_name=client_name,
            weight_unit=cfg.weight_unit,
            measurement_unit=measurement_unit,
        )
        return _compact(summary)

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

        # Generate the chart (blocking I/O — run in thread pool)
        png_bytes = await asyncio.to_thread(
            generate_chart,
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

    # ── Calendar Sync ──

    @mcp.tool()
    async def list_appointments(
        time_range: str = "next_7d",
    ) -> str:
        """List Kahunas appointments, optionally filtered by time range.

        Time ranges: today, next_24h, next_48h, next_7d, next_month,
        next_3m, next_6m, next_12m.

        Returns appointments with Kahunas UUIDs for calendar sync.
        """
        from ..calendar_sync import CalendarConfig, filter_appointments_by_range, parse_time_range

        cfg = config or KahunasConfig.from_env()
        cal_config = CalendarConfig(
            prefix=cfg.calendar_prefix,
            default_gym=cfg.default_gym,
            default_duration_minutes=cfg.calendar_default_duration,
        )

        # Fetch Kahunas calendar events via web endpoint
        resp = await _get_client().web_get(_CALENDAR_EVENTS_PATH)
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": _CALENDAR_FETCH_ERROR, "raw": resp.text[:200]})

        events = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get("data", data.get("events", []))

        # Filter by time range
        try:
            start_dt, end_dt = parse_time_range(time_range)
            events = filter_appointments_by_range(events, start_dt, end_dt, date_field="start")
        except ValueError as exc:
            return _compact({"error": str(exc)})

        # Format for LLM consumption
        appointments = []
        for evt in events:
            appt: dict[str, Any] = {
                "uuid": evt.get("id", evt.get("uuid", "")),
                "title": evt.get("title", ""),
                "start": evt.get("start", ""),
                "end": evt.get("end", ""),
            }
            if evt.get("client_name"):
                appt["client"] = evt["client_name"]
            if cal_config.default_gym:
                appt["location"] = cal_config.default_gym
            appointments.append(appt)

        return _compact(
            {
                "appointments": appointments,
                "count": len(appointments),
                "range": time_range,
                "prefix": cal_config.prefix,
            }
        )

    @mcp.tool()
    async def sync_appointments_ics(
        time_range: str = "next_7d",
        output_path: str = "",
    ) -> str:
        """Generate an iCal (.ics) file for Apple Calendar from Kahunas appointments.

        Exports appointments for the given time range to an .ics file that
        can be imported into Apple Calendar, Outlook, or any iCal-compatible app.

        Each event embeds the Kahunas UUID for safe add/edit/remove tracking.

        Time ranges: today, next_24h, next_48h, next_7d, next_month,
        next_3m, next_6m, next_12m.
        """
        from ..calendar_sync import (
            CalendarConfig,
            filter_appointments_by_range,
            generate_ics,
            parse_time_range,
        )

        cfg = config or KahunasConfig.from_env()
        cal_config = CalendarConfig(
            prefix=cfg.calendar_prefix,
            default_gym=cfg.default_gym,
            default_duration_minutes=cfg.calendar_default_duration,
        )

        # Fetch Kahunas events
        resp = await _get_client().web_get(_CALENDAR_EVENTS_PATH)
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": _CALENDAR_FETCH_ERROR})

        events = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get("data", data.get("events", []))

        # Filter by time range
        try:
            start_dt, end_dt = parse_time_range(time_range)
            events = filter_appointments_by_range(events, start_dt, end_dt, date_field="start")
        except ValueError as exc:
            return _compact({"error": str(exc)})

        # Map to appointment dicts
        appointments = []
        for evt in events:
            appointments.append(
                {
                    "uuid": evt.get("id", evt.get("uuid", "")),
                    "client_name": evt.get("client_name", evt.get("title", "Client")),
                    "start_time": evt.get("start", ""),
                    "end_time": evt.get("end", ""),
                    "notes": evt.get("description", ""),
                    "location": evt.get("location", ""),
                }
            )

        # Generate .ics
        ics_content = generate_ics(appointments, cal_config)

        if not output_path:
            output_path = f"/tmp/kahunas_appointments_{time_range}.ics"

        await asyncio.to_thread(Path(output_path).write_text, ics_content)

        return _compact(
            {
                "status": "exported",
                "path": output_path,
                "events": len(appointments),
                "range": time_range,
                "format": "iCal (.ics)",
            }
        )

    @mcp.tool()
    async def format_appointments_gcal(
        time_range: str = "next_7d",
    ) -> str:
        """Format Kahunas appointments as Google Calendar event objects.

        Returns a list of event objects ready for the Google Calendar API.
        Each event includes the Kahunas UUID in extendedProperties for
        safe tracking, and the title follows the configured prefix format.

        Time ranges: today, next_24h, next_48h, next_7d, next_month,
        next_3m, next_6m, next_12m.
        """
        from ..calendar_sync import (
            CalendarConfig,
            filter_appointments_by_range,
            format_for_google_calendar,
            parse_time_range,
        )

        cfg = config or KahunasConfig.from_env()
        cal_config = CalendarConfig(
            prefix=cfg.calendar_prefix,
            default_gym=cfg.default_gym,
            default_duration_minutes=cfg.calendar_default_duration,
        )

        # Fetch Kahunas events
        resp = await _get_client().web_get(_CALENDAR_EVENTS_PATH)
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": _CALENDAR_FETCH_ERROR})

        events = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get("data", data.get("events", []))

        # Filter by time range
        try:
            start_dt, end_dt = parse_time_range(time_range)
            events = filter_appointments_by_range(events, start_dt, end_dt, date_field="start")
        except ValueError as exc:
            return _compact({"error": str(exc)})

        # Map to appointment dicts
        appointments = []
        for evt in events:
            appointments.append(
                {
                    "uuid": evt.get("id", evt.get("uuid", "")),
                    "client_name": evt.get("client_name", evt.get("title", "Client")),
                    "start_time": evt.get("start", ""),
                    "end_time": evt.get("end", ""),
                    "notes": evt.get("description", ""),
                    "location": evt.get("location", ""),
                }
            )

        gcal_events = format_for_google_calendar(appointments, cal_config)
        return _compact(
            {
                "events": gcal_events,
                "count": len(gcal_events),
                "range": time_range,
                "prefix": cal_config.prefix,
            }
        )

    @mcp.tool()
    async def find_client_appointments(
        client_uuid: str,
        client_name: str = "",
        time_range: str = "next_12m",
    ) -> str:
        """Find all calendar appointments for a specific client.

        Searches Kahunas calendar events for a client by UUID or name.
        Returns matching appointments with their Kahunas UUIDs for
        editing or removal.

        Time ranges: today, next_24h, next_48h, next_7d, next_month,
        next_3m, next_6m, next_12m.
        """
        from ..calendar_sync import filter_appointments_by_range, parse_time_range

        resp = await _get_client().web_get(_CALENDAR_EVENTS_PATH)
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": _CALENDAR_FETCH_ERROR})

        events = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get("data", data.get("events", []))

        # Filter by time range
        try:
            start_dt, end_dt = parse_time_range(time_range)
            events = filter_appointments_by_range(events, start_dt, end_dt, date_field="start")
        except ValueError as exc:
            return _compact({"error": str(exc)})

        # Match by client UUID or name
        matched = []
        search_name = client_name.lower()
        for evt in events:
            evt_client = evt.get("client_uuid", evt.get("client_id", ""))
            evt_title = evt.get("title", "").lower()
            evt_name = evt.get("client_name", "").lower()

            if (
                evt_client == client_uuid
                or (search_name and search_name in evt_title)
                or (search_name and search_name in evt_name)
            ):
                matched.append(
                    {
                        "uuid": evt.get("id", evt.get("uuid", "")),
                        "title": evt.get("title", ""),
                        "start": evt.get("start", ""),
                        "end": evt.get("end", ""),
                        "client": evt.get("client_name", ""),
                    }
                )

        return _compact(
            {
                "appointments": matched,
                "count": len(matched),
                "client_uuid": client_uuid,
                "client_name": client_name,
            }
        )

    @mcp.tool()
    async def appointment_overview() -> str:
        """Get a comprehensive overview of all appointments across time windows.

        Shows upcoming appointments (rest of today, tomorrow, rest of week,
        rest of month) and historical counts (last week, 1/3/6 months, year,
        all time). Also shows per-client appointment counts.

        Use this tool to quickly see what's coming up and review scheduling
        patterns.
        """
        from ..checkin_history import build_appointment_overview

        resp = await _get_client().web_get(_CALENDAR_EVENTS_PATH)
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": _CALENDAR_FETCH_ERROR})

        events = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get("data", data.get("events", []))

        overview = build_appointment_overview(events)
        return _compact(overview)

    @mcp.tool()
    async def client_appointment_counts(
        client_uuid: str,
        client_name: str = "",
    ) -> str:
        """Get appointment counts for a specific client across time windows.

        Shows how many appointments a client has had in the last week,
        1 month, 3 months, 6 months, last year, and all time.

        Useful for reviewing training frequency and client engagement.
        """
        from ..checkin_history import build_client_appointment_counts

        resp = await _get_client().web_get(_CALENDAR_EVENTS_PATH)
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": _CALENDAR_FETCH_ERROR})

        events = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get("data", data.get("events", []))

        counts = build_client_appointment_counts(events, client_uuid, client_name)
        return _compact(counts)

    @mcp.tool()
    async def sync_calendar(
        mode: str = "preview",
        time_range: str = "next_3m",
        calendar_type: str = "google",
    ) -> str:
        """Sync Kahunas appointments with your calendar (Google or Apple).

        Modes:
            preview  — Show what would be added/removed/updated (default, safe)
            add      — Add new Kahunas appointments not yet in calendar
            remove   — Remove calendar events for deleted Kahunas appointments
            sync     — Full two-way sync: add new + remove deleted
            trust    — Trust all: sync everything without individual confirmation

        Calendar types: google, apple (ics)

        Time ranges: today, next_24h, next_48h, next_7d, next_month,
        next_3m, next_6m, next_12m.

        For Google Calendar: Returns event objects ready for the API.
        For Apple Calendar: Generates an .ics file for import.

        In 'preview' mode, returns a summary of pending changes.
        The AI assistant should present these to the user for confirmation
        before switching to 'add', 'remove', or 'sync' mode.
        """
        from ..calendar_sync import (
            CalendarConfig,
            filter_appointments_by_range,
            format_for_google_calendar,
            generate_ics,
            parse_time_range,
        )

        cfg = config or KahunasConfig.from_env()
        cal_config = CalendarConfig(
            prefix=cfg.calendar_prefix,
            default_gym=cfg.default_gym,
            default_duration_minutes=cfg.calendar_default_duration,
        )

        # Validate mode
        valid_modes = ("preview", "add", "remove", "sync", "trust")
        if mode not in valid_modes:
            return _compact({"error": f"Invalid mode: '{mode}'. Use: {', '.join(valid_modes)}"})

        # Fetch Kahunas events
        resp = await _get_client().web_get(_CALENDAR_EVENTS_PATH)
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": _CALENDAR_FETCH_ERROR})

        events = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get("data", data.get("events", []))

        # Filter by time range
        try:
            start_dt, end_dt = parse_time_range(time_range)
            events = filter_appointments_by_range(events, start_dt, end_dt, date_field="start")
        except ValueError as exc:
            return _compact({"error": str(exc)})

        # Map to appointment dicts
        appointments = []
        for evt in events:
            appointments.append(
                {
                    "uuid": evt.get("id", evt.get("uuid", "")),
                    "client_name": evt.get("client_name", evt.get("title", "Client")),
                    "start_time": evt.get("start", ""),
                    "end_time": evt.get("end", ""),
                    "notes": evt.get("description", ""),
                    "location": evt.get("location", ""),
                }
            )

        result: dict[str, Any] = {
            "mode": mode,
            "calendar_type": calendar_type,
            "time_range": time_range,
            "total_appointments": len(appointments),
        }

        if mode == "preview":
            # Show what would be synced
            result["appointments"] = [
                {
                    "uuid": a["uuid"],
                    "client": a["client_name"],
                    "start": a["start_time"],
                    "end": a["end_time"],
                    "location": a.get("location") or None,
                }
                for a in appointments
            ]
            result["message"] = (
                f"Found {len(appointments)} appointments in the '{time_range}' range. "
                f"Use mode='sync' to add all to {calendar_type} calendar, "
                f"or mode='add'/'remove' for granular control."
            )
        elif mode in ("add", "sync", "trust"):
            if calendar_type == "apple":
                ics_content = generate_ics(appointments, cal_config)
                # Save to temp file
                ics_path = f"/tmp/kahunas_sync_{time_range}.ics"
                try:
                    with open(ics_path, "w") as f:
                        f.write(ics_content)
                    result["ics_file"] = ics_path
                    result["message"] = (
                        f"Generated .ics file with {len(appointments)} appointments. "
                        f"Import {ics_path} into Apple Calendar."
                    )
                except OSError as exc:
                    result["error"] = f"Could not write .ics file: {exc}"
            else:
                # Google Calendar format
                gcal_events = format_for_google_calendar(appointments, cal_config)
                result["events"] = gcal_events
                result["message"] = (
                    f"Formatted {len(gcal_events)} appointments for Google Calendar API. "
                    "Use these event objects with gcal_create_event to add them."
                )
        elif mode == "remove":
            # List appointments that could be removed
            result["removable"] = [
                {"uuid": a["uuid"], "client": a["client_name"], "start": a["start_time"]}
                for a in appointments
            ]
            result["message"] = (
                f"Found {len(appointments)} appointments that can be removed. "
                "Use the UUIDs with your calendar's delete API."
            )

        return _compact(result)

    # ── Gym / Location Management ──

    @mcp.tool()
    async def list_gyms() -> str:
        """List configured gyms/locations for calendar appointments.

        Returns the default gym and the full list of available gyms.
        Configure via KAHUNAS_GYM_LIST (comma-separated) and
        KAHUNAS_DEFAULT_GYM environment variables.
        """
        cfg = config or KahunasConfig.from_env()
        gym_list = [g.strip() for g in cfg.gym_list.split(",") if g.strip()] if cfg.gym_list else []
        return _compact(
            {
                "default_gym": cfg.default_gym or None,
                "gyms": gym_list if gym_list else None,
                "prefix": cfg.calendar_prefix,
                "duration_minutes": cfg.calendar_default_duration,
            }
        )

    # ── Measurement Settings ──

    @mcp.tool()
    async def get_measurement_settings() -> str:
        """Get the configured measurement unit settings.

        Returns current unit settings for weight, height, glucose, food,
        and water along with all available options for each.

        Configure via environment variables:
            KAHUNAS_WEIGHT_UNIT: kg or lbs (default: kg)
            KAHUNAS_HEIGHT_UNIT: cm or inches (default: cm)
            KAHUNAS_GLUCOSE_UNIT: mmol_l or mg_dl (default: mmol_l)
            KAHUNAS_FOOD_UNIT: grams, ounces, qty, cups, oz, ml, tsp (default: grams)
            KAHUNAS_WATER_UNIT: ml, l, or oz (default: ml)
        """
        cfg = config or KahunasConfig.from_env()
        current = {
            "weight": cfg.weight_unit,
            "height": cfg.height_unit,
            "glucose": cfg.glucose_unit,
            "food": cfg.food_unit,
            "water": cfg.water_unit,
        }
        return _compact(
            {
                "current": current,
                "available": MEASUREMENT_SETTINGS,
                "metrics": get_metrics_with_units(cfg.weight_unit, cfg.height_unit),
            }
        )

    # ── Client Removal ──

    @mcp.tool()
    async def remove_client(
        client_uuid: str,
        remove_from_kahunas: bool = True,
        remove_calendar_appointments: bool = True,
    ) -> str:
        """Remove a client from Kahunas and/or their calendar appointments.

        This tool can:
        1. Delete the client from Kahunas (remove_from_kahunas=True)
        2. Find and list their calendar appointments for removal
           (remove_calendar_appointments=True)

        Calendar events are identified by Kahunas UUID. For Google Calendar,
        use the returned appointment UUIDs with your calendar's delete API.
        For Apple Calendar, re-export the .ics without the removed client.

        WARNING: Removing a client from Kahunas is permanent.
        """
        from ..calendar_sync import build_removal_summary

        results: dict[str, Any] = {"client_uuid": client_uuid}
        appointments_found = 0
        kahunas_removed = False

        # Find calendar appointments for this client
        if remove_calendar_appointments:
            try:
                resp = await _get_client().web_get(_CALENDAR_EVENTS_PATH)
                data = resp.json()
                events = []
                if isinstance(data, list):
                    events = data
                elif isinstance(data, dict):
                    events = data.get("data", data.get("events", []))

                client_events = []
                for evt in events:
                    if evt.get("client_uuid", evt.get("client_id", "")) == client_uuid:
                        client_events.append(
                            {
                                "uuid": evt.get("id", evt.get("uuid", "")),
                                "title": evt.get("title", ""),
                                "start": evt.get("start", ""),
                            }
                        )
                appointments_found = len(client_events)
                results["calendar_appointments"] = client_events
            except Exception as exc:
                results["calendar_error"] = str(exc)

        # Remove from Kahunas
        if remove_from_kahunas:
            try:
                resp = await _get_client().get_client_action("delete", client_uuid)
                kahunas_removed = resp.status_code < 400
                results["kahunas_response"] = resp.text[:200]
            except Exception as exc:
                results["kahunas_error"] = str(exc)

        summary = build_removal_summary(
            client_name=results.get("client_name", client_uuid),
            client_uuid=client_uuid,
            appointments_found=appointments_found,
            appointments_removed=0,  # Actual removal done by external calendar API
            kahunas_removed=kahunas_removed,
        )
        results["summary"] = summary
        return _compact(results)

    # ── Exercise & Diet Discovery ──

    @mcp.tool()
    async def discover_all_exercises(max_pages: int = 20) -> str:
        """Discover and list ALL exercises in the Kahunas exercise library.

        Paginates through the entire exercise library to return every
        exercise name, UUID, and type. Useful for building a complete
        exercise catalogue or checking which exercises are available.

        Returns all exercises sorted alphabetically by name.
        """
        all_exercises: list[dict[str, Any]] = []
        page = 1
        per_page = 50

        while page <= max_pages:
            data = await _get_client().list_exercises(page, per_page)
            for ex in data.exercises:
                all_exercises.append(
                    {
                        "name": ex.exercise_name or ex.title,
                        "uuid": ex.uuid,
                        "type": "strength" if ex.exercise_type == 1 else "cardio",
                        "tags": ex.tags or None,
                    }
                )
            if len(data.exercises) < per_page:
                break
            page += 1

        # Sort alphabetically
        all_exercises.sort(key=lambda x: (x.get("name") or "").lower())

        return _compact(
            {
                "exercises": all_exercises,
                "total": len(all_exercises),
                "types": {
                    "strength": sum(1 for e in all_exercises if e["type"] == "strength"),
                    "cardio": sum(1 for e in all_exercises if e["type"] == "cardio"),
                },
            }
        )

    @mcp.tool()
    async def discover_diet_plans() -> str:
        """Discover all diet plans available in Kahunas.

        Lists all diet plans with their details. Useful for checking
        what nutrition plans are configured for clients.
        """
        resp = await _get_client().diet_plan_action("list")
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": "Could not fetch diet plans", "raw": resp.text[:200]})
        return _compact(data)

    @mcp.tool()
    async def discover_supplement_plans() -> str:
        """Discover all supplement plans available in Kahunas.

        Lists all supplement plans with their details.
        """
        resp = await _get_client().supplement_plan_action("list")
        try:
            data = resp.json()
        except Exception:
            return _compact({"error": "Could not fetch supplement plans", "raw": resp.text[:200]})
        return _compact(data)

    # ── Metrics Store (Local Timeseries) ──

    @mcp.tool()
    async def store_client_metrics(
        client_uuid: str,
        metric: str,
        data_points: str,
        client_name: str = "",
    ) -> str:
        """Store client metric data points in the local timeseries database.

        Saves progress data locally so charts can be generated from cache.
        Data is stored in ~/.kahunas/metrics.db (SQLite).

        Metrics: weight, bodyfat, steps, chest, waist, hips, arms, thighs.

        data_points should be a JSON string of [{date, value}, ...].
        Example: '[{"date":"2024-01-15","value":85.0},{"date":"2024-02-15","value":83.5}]'
        """
        store = _get_metrics()
        try:
            points = json.loads(data_points)
        except json.JSONDecodeError:
            return _compact({"error": "Invalid JSON in data_points"})

        if not isinstance(points, list):
            return _compact({"error": "data_points must be a JSON array"})

        try:
            inserted = store.record_batch(
                client_uuid=client_uuid,
                metric=metric,
                data_points=points,
                client_name=client_name,
            )
        except ValueError as exc:
            return _compact({"error": str(exc)})

        return _compact(
            {
                "status": "stored",
                "client_uuid": client_uuid,
                "metric": metric,
                "inserted": inserted,
                "total_points": len(points),
            }
        )

    @mcp.tool()
    async def query_client_metrics(
        client_uuid: str,
        metric: str,
        start_date: str = "",
        end_date: str = "",
    ) -> str:
        """Query stored metric data from the local timeseries database.

        Returns data points for the specified client and metric, optionally
        filtered by date range. Data is sorted chronologically.

        Metrics: weight, bodyfat, steps, chest, waist, hips, arms, thighs.
        """
        store = _get_metrics()
        points = store.query(
            client_uuid=client_uuid,
            metric=metric,
            start_date=start_date,
            end_date=end_date,
        )
        summary = store.get_summary(client_uuid, metric)
        meta = METRIC_DEFINITIONS.get(metric, {})

        return _compact(
            {
                "data": points,
                "count": len(points),
                "metric": metric,
                "label": meta.get("label", metric),
                "unit": meta.get("unit", ""),
                "summary": summary,
            }
        )

    @mcp.tool()
    async def list_stored_clients() -> str:
        """List all clients with locally stored metric data.

        Shows which clients have cached progress data and what metrics
        are available for each.
        """
        store = _get_metrics()
        clients = store.list_clients()
        return _compact({"clients": clients, "count": len(clients)})

    @mcp.tool()
    async def sync_client_metrics(
        client_uuid: str,
        metric: str = "weight",
        time_range: str = "all",
        client_name: str = "",
    ) -> str:
        """Fetch client metrics from Kahunas API and store locally.

        Fetches progress data from the Kahunas API and saves it to the
        local timeseries database for offline chart generation.

        Metrics: weight, bodyfat, steps, chest, waist, hips, arms, thighs.
        Time ranges: week, month, quarter, year, all.
        """
        # Fetch from API
        resp = await _get_client().get_chart_data(client_uuid, value=metric, range_type=time_range)

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
            return _compact({"error": "Could not parse API response"})

        # Store locally
        store = _get_metrics()
        try:
            inserted = store.record_batch(
                client_uuid=client_uuid,
                metric=metric,
                data_points=data_points,
                client_name=client_name,
            )
        except ValueError as exc:
            return _compact({"error": str(exc)})

        return _compact(
            {
                "status": "synced",
                "metric": metric,
                "fetched": len(data_points),
                "new_records": inserted,
                "client_uuid": client_uuid,
            }
        )

    @mcp.tool()
    async def generate_chart_from_store(
        client_uuid: str,
        metric: str = "weight",
        time_range: str = "all",
        client_name: str = "",
        output_path: str = "",
    ) -> str:
        """Generate a PNG chart from locally stored metric data.

        Uses data from the local timeseries database (no API call needed).
        Call sync_client_metrics first to ensure data is up to date.

        Metrics: weight, bodyfat, steps, chest, waist, hips, arms, thighs.
        Time ranges: week, month, quarter, year, all.
        """
        from ..charts import generate_chart

        store = _get_metrics()
        points = store.query(client_uuid, metric)

        # Convert to chart format
        chart_data = [{"date": p["date"], "value": p["value"]} for p in points]

        if not output_path:
            safe_name = client_name.replace(" ", "_") or client_uuid[:8]
            output_path = f"/tmp/kahunas_{safe_name}_{metric}_{time_range}.png"

        png_bytes = await asyncio.to_thread(
            generate_chart,
            data_points=chart_data,
            metric=metric,
            time_range=time_range,
            client_name=client_name,
            output_path=output_path,
        )

        b64 = base64.b64encode(png_bytes).decode("ascii")
        return _compact(
            {
                "path": output_path,
                "metric": metric,
                "range": time_range,
                "points": len(chart_data),
                "size_kb": round(len(png_bytes) / 1024, 1),
                "image_base64": b64[:100] + "..." if len(b64) > 100 else b64,
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

    # ── Phone Alignment Tools ──

    @mcp.tool()
    async def phone_alignment_report(country_code: str = "44") -> str:
        """Show phone alignment between Kahunas client data and WhatsApp E.164 format.

        Compares stored phone numbers with their normalised WhatsApp equivalents.
        Identifies aligned, mismatched, and missing numbers so you can fix them.
        """
        client = _get_client()
        resp = await client.list_clients()
        try:
            clients_data = resp.json()
        except Exception:
            return _compact({"error": "Could not fetch clients"})

        raw_clients = (
            clients_data if isinstance(clients_data, list) else clients_data.get("data", [])
        )
        report = build_phone_alignment_report(raw_clients, country_code)
        return _compact(report)

    @mcp.tool()
    async def update_client_phone(client_uuid: str, phone: str) -> str:
        """Update a client's phone number in Kahunas.

        Use after running phone_alignment_report to fix mismatched numbers.
        """
        client = _get_client()
        resp = await client.get_client_action("edit", client_uuid, phone=phone)
        try:
            data = resp.json()
        except Exception:
            data = {"status": resp.status_code, "text": resp.text[:200]}
        return _compact(
            {
                "status": "updated",
                "client_uuid": client_uuid,
                "phone": phone,
                "response": data,
            }
        )

    # ── PDF Export Tools ──

    @mcp.tool()
    async def export_workout_program_to_pdf(uuid: str, output_path: str = "") -> str:
        """Export a workout program as a professionally formatted PDF.

        Includes exercise tables with sets, reps, rest, and tempo per day.
        """
        client = _get_client()
        program = await client.get_workout_program(uuid)
        program_data = program.model_dump()

        if not output_path:
            output_path = os.path.expanduser(
                f"~/kahunas_exports/{program_data.get('name', uuid)}_program.pdf"
            )

        path = await asyncio.to_thread(export_workout_program_pdf, program_data, output_path)
        return _compact({"status": "exported", "path": str(path)})

    @mcp.tool()
    async def export_checkin_summary_to_pdf(
        client_uuid: str,
        client_name: str = "Client",
        output_path: str = "",
    ) -> str:
        """Export a client's check-in history as a PDF with metrics table and trends."""
        from ..checkin_history import format_checkin_summary

        client = _get_client()
        config = client._config

        resp = await client.list_client_checkins(client_uuid)
        try:
            raw_data = resp.json()
        except Exception:
            return _compact({"error": "Could not fetch check-in data"})

        summary = format_checkin_summary(
            raw_data,
            client_name=client_name,
            weight_unit=config.weight_unit,
            measurement_unit=config.height_unit,
        )

        summary_data = {
            "client_name": client_name,
            "checkins": summary.get("checkins", []),
            "trends": summary.get("trends"),
        }

        if not output_path:
            output_path = os.path.expanduser(
                f"~/kahunas_exports/{client_name.replace(' ', '_')}_checkins.pdf"
            )

        path = await asyncio.to_thread(
            export_checkin_summary_pdf,
            summary_data,
            output_path,
            weight_unit=config.weight_unit,
            measurement_unit=config.height_unit,
        )
        return _compact({"status": "exported", "path": str(path)})

    @mcp.tool()
    async def export_workout_plan_to_pdf(client_uuid: str, output_path: str = "") -> str:
        """Export a client's assigned workout plan as a formatted PDF."""
        client = _get_client()
        resp = await client.get_client_action("view", client_uuid)
        try:
            client_data = resp.json()
        except Exception:
            return _compact({"error": "Could not fetch client data"})

        # Extract workout plan from client view data
        plan_data = client_data.get("workout_plan", client_data.get("plan", {}))
        if not plan_data:
            return _compact({"error": "No workout plan found for this client"})

        first = client_data.get("first_name", "")
        last = client_data.get("last_name", "")
        client_name = f"{first} {last}".strip()
        plan_data["client_name"] = client_name or "Client"

        if not output_path:
            output_path = os.path.expanduser(
                f"~/kahunas_exports/{client_name.replace(' ', '_')}_plan.pdf"
            )

        path = await asyncio.to_thread(export_workout_plan_pdf, plan_data, output_path)
        return _compact({"status": "exported", "path": str(path)})

    # ── Check-in Reminder Tools ──

    @mcp.tool()
    async def find_overdue_checkins(days: int = 7) -> str:
        """Find clients who haven't checked in for the specified number of days.

        Returns a list of overdue clients sorted by most overdue first,
        with their last check-in date and days overdue.
        """
        client = _get_client()
        resp = await client.list_clients()
        try:
            clients_data = resp.json()
        except Exception:
            return _compact({"error": "Could not fetch clients"})

        raw_clients = (
            clients_data if isinstance(clients_data, list) else clients_data.get("data", [])
        )

        # Fetch check-in data for each client
        checkins_by_client: dict[str, list[dict[str, Any]]] = {}
        for c in raw_clients:
            uuid = c.get("uuid", "")
            if not uuid:
                continue
            try:
                checkin_resp = await client.list_client_checkins(uuid)
                checkin_data = checkin_resp.json()
                checkins = checkin_data.get("check_ins", checkin_data.get("checkins", []))
                if isinstance(checkins, list):
                    checkins_by_client[uuid] = checkins
            except Exception:
                logger.debug("Could not fetch check-ins for client %s", uuid)

        overdue = find_overdue_clients(
            raw_clients,
            checkins_by_client,
            days_threshold=days,
        )
        return _compact(
            {
                "overdue_clients": overdue,
                "threshold_days": days,
                "total_overdue": len(overdue),
            }
        )

    @mcp.tool()
    async def send_checkin_reminders(
        client_uuids: str,
        via_chat: bool = True,
        via_whatsapp: bool = False,
        custom_message: str = "",
    ) -> str:
        """Send check-in reminders to specified clients via Kahunas chat and/or WhatsApp.

        client_uuids: Comma-separated UUIDs of clients to remind.
        """
        from ..whatsapp import WhatsAppClient, WhatsAppConfig, normalise_phone

        client = _get_client()
        config = client._config
        uuids = [u.strip() for u in client_uuids.split(",") if u.strip()]

        persona = PersonaConfig.from_config(
            persona_template=config.persona_template,
            persona_template_path=config.persona_template_path,
            weight_deviation_pct=config.persona_weight_deviation_pct,
            sleep_minimum=config.persona_sleep_minimum,
            step_minimum=config.persona_step_minimum,
        )

        results: list[dict[str, Any]] = []

        for uuid in uuids:
            entry: dict[str, Any] = {"uuid": uuid, "chat_sent": False, "whatsapp_sent": False}
            try:
                resp = await client.get_client_action("view", uuid)
                client_data = resp.json()
                first_name = client_data.get("first_name", "Client")
                phone = client_data.get("phone", "")
                entry["name"] = first_name

                message = build_reminder_message(
                    first_name,
                    config.checkin_reminder_days,
                    persona,
                    custom_message,
                )

                if via_chat:
                    try:
                        await client.send_chat_message(
                            {
                                "receiver_uuid": uuid,
                                "message": message,
                            }
                        )
                        entry["chat_sent"] = True
                    except Exception as exc:
                        entry["chat_error"] = str(exc)

                if via_whatsapp and phone:
                    wa_config = WhatsAppConfig(
                        access_token=config.whatsapp_token,
                        phone_number_id=config.whatsapp_phone_number_id,
                        default_country_code=config.whatsapp_default_country_code,
                    )
                    if wa_config.is_configured():
                        normalised = normalise_phone(phone, config.whatsapp_default_country_code)
                        if normalised:
                            try:
                                async with WhatsAppClient(wa_config) as wa:
                                    await wa.send_text(normalised, message)
                                entry["whatsapp_sent"] = True
                            except Exception as exc:
                                entry["whatsapp_error"] = str(exc)
                    else:
                        entry["whatsapp_error"] = "WhatsApp not configured"

            except Exception as exc:
                entry["error"] = str(exc)

            results.append(entry)

        return _compact({"reminders_sent": results, "total": len(results)})

    # ── Anomaly Detection Tools ──

    @mcp.tool()
    async def detect_client_anomalies(client_uuid: str, client_name: str = "Client") -> str:
        """Scan a single client's check-in data for anomalies and threshold breaches.

        Detects significant changes in weight, body measurements, sleep,
        stress, energy, and other metrics. Thresholds are configurable via
        KAHUNAS_ANOMALY_* environment variables.
        """
        from ..checkin_history import format_checkin_summary

        client = _get_client()
        config = client._config

        resp = await client.list_client_checkins(client_uuid)
        try:
            raw_data = resp.json()
        except Exception:
            return _compact({"error": "Could not fetch check-in data"})

        summary = format_checkin_summary(
            raw_data,
            client_name=client_name,
            weight_unit=config.weight_unit,
            measurement_unit=config.height_unit,
        )
        checkins = summary.get("checkins", [])

        thresholds = parse_thresholds(
            weight_pct=config.anomaly_weight_pct,
            body_pct=config.anomaly_body_pct,
            lifestyle_abs=config.anomaly_lifestyle_abs,
        )

        anomalies = scan_client_anomalies(
            checkins,
            thresholds=thresholds,
            window_days=config.anomaly_window_days,
            sleep_minimum=config.anomaly_sleep_minimum,
            step_minimum=config.anomaly_step_minimum,
        )

        total_anomalies = sum(len(v) for v in anomalies.values())
        return _compact(
            {
                "client": client_name,
                "client_uuid": client_uuid,
                "anomalies": anomalies,
                "total_anomalies": total_anomalies,
                "thresholds_used": {
                    "weight_pct": config.anomaly_weight_pct,
                    "body_pct": config.anomaly_body_pct,
                    "lifestyle_abs": config.anomaly_lifestyle_abs,
                    "window_days": config.anomaly_window_days,
                },
            }
        )

    @mcp.tool()
    async def scan_all_client_anomalies() -> str:
        """Scan ALL clients for check-in anomalies and threshold breaches.

        Returns a summary of anomalies found across all clients.
        Use detect_client_anomalies for detailed per-client analysis.
        """
        from ..checkin_history import format_checkin_summary

        client = _get_client()
        config = client._config

        resp = await client.list_clients()
        try:
            clients_data = resp.json()
        except Exception:
            return _compact({"error": "Could not fetch clients"})

        raw_clients = (
            clients_data if isinstance(clients_data, list) else clients_data.get("data", [])
        )

        thresholds = parse_thresholds(
            weight_pct=config.anomaly_weight_pct,
            body_pct=config.anomaly_body_pct,
            lifestyle_abs=config.anomaly_lifestyle_abs,
        )

        results: list[dict[str, Any]] = []
        for c in raw_clients:
            uuid = c.get("uuid", "")
            name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
            if not uuid:
                continue

            try:
                checkin_resp = await client.list_client_checkins(uuid)
                raw_data = checkin_resp.json()
                summary = format_checkin_summary(
                    raw_data,
                    client_name=name,
                    weight_unit=config.weight_unit,
                    measurement_unit=config.height_unit,
                )
                checkins = summary.get("checkins", [])
                anomalies = scan_client_anomalies(
                    checkins,
                    thresholds=thresholds,
                    window_days=config.anomaly_window_days,
                    sleep_minimum=config.anomaly_sleep_minimum,
                    step_minimum=config.anomaly_step_minimum,
                )
                if anomalies:
                    total = sum(len(v) for v in anomalies.values())
                    results.append(
                        {
                            "client": name,
                            "uuid": uuid,
                            "anomaly_count": total,
                            "metrics_affected": list(anomalies.keys()),
                        }
                    )
            except Exception:
                logger.debug("Could not scan anomalies for client %s", uuid)

        results.sort(key=lambda x: x.get("anomaly_count", 0), reverse=True)
        return _compact(
            {
                "clients_with_anomalies": results,
                "total_clients_scanned": len(raw_clients),
                "clients_with_issues": len(results),
            }
        )

    # ── Persona / Template Tools ──

    @mcp.tool()
    async def get_messaging_persona() -> str:
        """Show the current messaging persona configuration and template.

        Displays the active template source (default/custom), thresholds
        for highlighting weight deviations, sleep deprivation, and low
        step count in client messages.
        """
        client = _get_client()
        config = client._config

        persona = PersonaConfig.from_config(
            persona_template=config.persona_template,
            persona_template_path=config.persona_template_path,
            weight_deviation_pct=config.persona_weight_deviation_pct,
            sleep_minimum=config.persona_sleep_minimum,
            step_minimum=config.persona_step_minimum,
        )

        return _compact(get_persona_summary(persona))

    @mcp.tool()
    async def preview_client_message(
        client_uuid: str,
        message_type: str = "reminder",
        custom_context: str = "",
    ) -> str:
        """Preview what a message to a client would look like.

        message_type: 'reminder' for check-in reminder, 'anomaly' for anomaly warning.
        """
        from ..checkin_history import format_checkin_summary

        client = _get_client()
        config = client._config

        resp = await client.get_client_action("view", client_uuid)
        try:
            client_data = resp.json()
        except Exception:
            return _compact({"error": "Could not fetch client data"})

        first_name = client_data.get("first_name", "Client")

        persona = PersonaConfig.from_config(
            persona_template=config.persona_template,
            persona_template_path=config.persona_template_path,
            weight_deviation_pct=config.persona_weight_deviation_pct,
            sleep_minimum=config.persona_sleep_minimum,
            step_minimum=config.persona_step_minimum,
        )

        if message_type == "anomaly":
            # Fetch anomaly data for preview
            checkin_resp = await client.list_client_checkins(client_uuid)
            try:
                raw_data = checkin_resp.json()
            except Exception:
                return _compact({"error": "Could not fetch check-in data"})

            summary = format_checkin_summary(
                raw_data,
                client_name=first_name,
                weight_unit=config.weight_unit,
                measurement_unit=config.height_unit,
            )
            checkins = summary.get("checkins", [])
            thresholds = parse_thresholds(
                weight_pct=config.anomaly_weight_pct,
                body_pct=config.anomaly_body_pct,
                lifestyle_abs=config.anomaly_lifestyle_abs,
            )
            anomalies_data = scan_client_anomalies(checkins, thresholds=thresholds)
            flat_anomalies = [a for alist in anomalies_data.values() for a in alist]
            message = build_anomaly_warning(first_name, flat_anomalies, persona, custom_context)
        else:
            message = build_reminder_message(
                first_name, config.checkin_reminder_days, persona, custom_context
            )

        return _compact(
            {
                "message_type": message_type,
                "client": first_name,
                "message_preview": message,
            }
        )

    return mcp
