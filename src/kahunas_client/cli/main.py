"""Kahunas CLI — manage clients, workouts, exercises, and exports from the terminal."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from ..client import KahunasClient
from ..config import KahunasConfig
from ..mcp.export import ExportManager

console = Console()


def _run(coro: Any) -> Any:
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _load_config(ctx: click.Context) -> KahunasConfig:
    """Load config from CLI context or environment."""
    email = ctx.obj.get("email", "")
    password = ctx.obj.get("password", "")
    token = ctx.obj.get("token", "")
    config_file = ctx.obj.get("config", "")

    cfg = KahunasConfig.from_yaml(config_file) if config_file else KahunasConfig.from_env()

    if email:
        cfg.email = email
    if password:
        cfg.password = password
    if token:
        cfg.auth_token = token
    return cfg


@click.group()
@click.option("--email", envvar="KAHUNAS_EMAIL", default="", help="Account email")
@click.option("--password", envvar="KAHUNAS_PASSWORD", default="", help="Account password")
@click.option("--token", envvar="KAHUNAS_AUTH_TOKEN", default="", help="Auth token (skips login)")
@click.option("--config", envvar="KAHUNAS_CONFIG_FILE", default="", help="Path to YAML config file")
@click.version_option(package_name="kahunas-client")
@click.pass_context
def cli(ctx: click.Context, email: str, password: str, token: str, config: str) -> None:
    """Kahunas — fitness coaching platform CLI."""
    ctx.ensure_object(dict)
    ctx.obj["email"] = email
    ctx.obj["password"] = password
    ctx.obj["token"] = token
    ctx.obj["config"] = config


# ── Workout Programs ──


@cli.group("workouts")
def workouts() -> None:
    """Manage workout programs."""


@workouts.command("list")
@click.option("--page", default=1, help="Page number")
@click.option("--per-page", default=12, help="Results per page")
@click.pass_context
def workouts_list(ctx: click.Context, page: int, per_page: int) -> None:
    """List workout programs."""

    async def _run_cmd() -> None:
        cfg = _load_config(ctx)
        async with KahunasClient(cfg) as client:
            data = await client.list_workout_programs(page, per_page)

            table = Table(title="Workout Programs")
            table.add_column("Title", style="cyan")
            table.add_column("UUID", style="dim")
            table.add_column("Days", justify="right")
            table.add_column("Assigned", justify="right")
            table.add_column("Updated")

            for p in data.workout_plan:
                table.add_row(
                    p.title, p.uuid[:12] + "...", str(p.days), str(p.assigned_clients), p.updated_at
                )

            console.print(table)
            console.print(f"Total: {data.total_records} programs (page {page})")

    _run(_run_cmd())


@workouts.command("show")
@click.argument("uuid")
@click.pass_context
def workouts_show(ctx: click.Context, uuid: str) -> None:
    """Show details of a workout program."""

    async def _run_cmd() -> None:
        cfg = _load_config(ctx)
        async with KahunasClient(cfg) as client:
            data = await client.get_workout_program(uuid)
            program = data.workout_plan

            console.print(f"\n[bold cyan]{program.title}[/bold cyan]")
            if program.short_desc:
                console.print(f"  {program.short_desc}")
            console.print(f"  Tags: {', '.join(program.tags) or 'none'}")
            console.print(f"  Days: {len(program.workout_days)}\n")

            for day in program.workout_days:
                if day.is_restday:
                    console.print(f"  [dim]{day.title}: Rest Day[/dim]")
                    continue
                console.print(f"  [bold]{day.title}[/bold]")
                for section in ("warmup", "workout", "cooldown"):
                    groups = getattr(day.exercise_list, section, [])
                    for group in groups:
                        for ex in group.exercises:
                            sets_info = f"{ex.sets} sets" if ex.sets else ""
                            reps_info = f"x {ex.reps}" if ex.reps else ""
                            console.print(f"    - {ex.exercise_name}  {sets_info}{reps_info}")

    _run(_run_cmd())


# ── Exercises ──


@cli.group("exercises")
def exercises() -> None:
    """Manage exercises."""


@exercises.command("list")
@click.option("--page", default=1, help="Page number")
@click.option("--per-page", default=12, help="Results per page")
@click.pass_context
def exercises_list(ctx: click.Context, page: int, per_page: int) -> None:
    """List exercises from the library."""

    async def _run_cmd() -> None:
        cfg = _load_config(ctx)
        async with KahunasClient(cfg) as client:
            data = await client.list_exercises(page, per_page)

            table = Table(title="Exercise Library")
            table.add_column("Name", style="cyan")
            table.add_column("Type")
            table.add_column("Tags")

            for ex in data.exercises:
                ex_type = "Strength" if ex.exercise_type == 1 else "Cardio"
                table.add_row(ex.exercise_name or ex.title, ex_type, ", ".join(ex.tags))

            console.print(table)
            console.print(f"Total: {data.total_records}")

    _run(_run_cmd())


@exercises.command("search")
@click.argument("query")
@click.pass_context
def exercises_search(ctx: click.Context, query: str) -> None:
    """Search exercises by keyword."""

    async def _run_cmd() -> None:
        cfg = _load_config(ctx)
        async with KahunasClient(cfg) as client:
            results = await client.search_exercises(query)

            table = Table(title=f"Search: '{query}'")
            table.add_column("Name", style="cyan")
            table.add_column("Type")

            for ex in results:
                ex_type = "Strength" if ex.exercise_type == 1 else "Cardio"
                table.add_row(ex.exercise_name or ex.title, ex_type)

            console.print(table)
            console.print(f"Found: {len(results)}")

    _run(_run_cmd())


# ── Clients ──


@cli.group("clients")
def clients() -> None:
    """Manage coaching clients."""


@clients.command("list")
@click.pass_context
def clients_list(ctx: click.Context) -> None:
    """List all clients."""

    async def _run_cmd() -> None:
        cfg = _load_config(ctx)
        async with KahunasClient(cfg) as client:
            resp = await client.list_clients()
            data = resp.json() if resp.status_code == 200 else {}

            client_list = data.get("data", data.get("clients", []))
            if isinstance(client_list, list):
                table = Table(title="Clients")
                table.add_column("Name", style="cyan")
                table.add_column("Email")
                table.add_column("Status")
                table.add_column("UUID", style="dim")

                for c in client_list:
                    name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
                    table.add_row(
                        name,
                        c.get("email", ""),
                        c.get("status", ""),
                        str(c.get("uuid", ""))[:12] + "...",
                    )

                console.print(table)
                console.print(f"Total: {len(client_list)}")
            else:
                console.print_json(json.dumps(data))

    _run(_run_cmd())


# ── Export ──


@cli.group("export")
def export() -> None:
    """Export data to Excel files."""


@export.command("client")
@click.argument("client_uuid")
@click.option("--output", "-o", default="", help="Output directory")
@click.option("--no-photos", is_flag=True, help="Skip downloading photos")
@click.pass_context
def export_client(ctx: click.Context, client_uuid: str, output: str, no_photos: bool) -> None:
    """Export all data for a single client."""

    async def _run_cmd() -> None:
        cfg = _load_config(ctx)
        async with KahunasClient(cfg) as client:
            mgr = ExportManager(client)
            path = await mgr.export_client(
                client_uuid=client_uuid,
                output_dir=output or None,
                include_photos=not no_photos,
            )
            console.print(f"[green]Exported to:[/green] {path}")

    _run(_run_cmd())


@export.command("all-clients")
@click.option("--output", "-o", default="", help="Output directory")
@click.pass_context
def export_all_clients(ctx: click.Context, output: str) -> None:
    """Export data for all clients."""

    async def _run_cmd() -> None:
        cfg = _load_config(ctx)
        async with KahunasClient(cfg) as client:
            mgr = ExportManager(client)
            path = await mgr.export_all_clients(output_dir=output or None)
            console.print(f"[green]Exported to:[/green] {path}")

    _run(_run_cmd())


@export.command("exercises")
@click.option("--output", "-o", default="", help="Output directory")
@click.pass_context
def export_exercises(ctx: click.Context, output: str) -> None:
    """Export the exercise library to Excel."""

    async def _run_cmd() -> None:
        cfg = _load_config(ctx)
        async with KahunasClient(cfg) as client:
            mgr = ExportManager(client)
            path = await mgr.export_exercise_library(output_dir=output or None)
            console.print(f"[green]Exported to:[/green] {path}")

    _run(_run_cmd())


@export.command("workouts")
@click.option("--output", "-o", default="", help="Output directory")
@click.pass_context
def export_workouts(ctx: click.Context, output: str) -> None:
    """Export all workout programs to Excel files."""

    async def _run_cmd() -> None:
        cfg = _load_config(ctx)
        async with KahunasClient(cfg) as client:
            mgr = ExportManager(client)
            path = await mgr.export_workout_programs(output_dir=output or None)
            console.print(f"[green]Exported to:[/green] {path}")

    _run(_run_cmd())


# ── MCP Server ──


@cli.command("serve")
@click.option(
    "--transport",
    "-t",
    type=click.Choice(["stdio", "http", "sse", "streamable-http"]),
    default="stdio",
    help="MCP transport protocol (default: stdio)",
)
@click.option("--host", "-H", default="0.0.0.0", help="Bind address for HTTP transport")
@click.option("--port", "-p", default=8000, type=int, help="Port for HTTP transport")
def serve(transport: str, host: str, port: int) -> None:
    """Start the MCP server."""
    from ..mcp.server import create_server

    server = create_server()
    if transport in ("http", "sse", "streamable-http"):
        server.run(transport=transport, host=host, port=port)
    else:
        server.run(transport="stdio")


# ── Raw API ──


@cli.command("api")
@click.argument("path")
@click.option("--method", "-m", default="GET", help="HTTP method")
@click.option("--data", "-d", default="", help="JSON request body")
@click.pass_context
def api_cmd(ctx: click.Context, path: str, method: str, data: str) -> None:
    """Make a raw API request."""

    async def _run_cmd() -> None:
        cfg = _load_config(ctx)
        async with KahunasClient(cfg) as client:
            if method.upper() == "GET":
                result = await client.api_get(path)
            else:
                body = json.loads(data) if data else None
                result = await client.api_post(path, data=body)
            console.print_json(json.dumps(result, default=str))

    _run(_run_cmd())


if __name__ == "__main__":
    cli()
