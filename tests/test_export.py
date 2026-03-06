"""Tests for the export manager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx

from kahunas_client.mcp.export import ExportManager, _sanitize_name


class TestSanitizeName:
    def test_clean_name(self) -> None:
        assert _sanitize_name("John Doe") == "John Doe"

    def test_special_chars(self) -> None:
        assert _sanitize_name('a<b>c:d"e') == "a_b_c_d_e"

    def test_trailing_dot(self) -> None:
        assert _sanitize_name("test.") == "test"


class TestExportManager:
    def _mock_client(self) -> MagicMock:
        client = MagicMock()
        # Mock all methods as async
        client.get_client_action = AsyncMock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "email": "john@test.com",
                        "uuid": "c1",
                    },
                },
            )
        )
        client.list_clients = AsyncMock(return_value=httpx.Response(200, json={"data": []}))
        client.list_habits = AsyncMock(return_value=httpx.Response(200, json={"habits": []}))
        client.get_chat_messages = AsyncMock(
            return_value=httpx.Response(200, json={"messages": []})
        )
        client.get_chart_data = AsyncMock(return_value=httpx.Response(200, json={"data": []}))
        client.list_exercises = AsyncMock()
        client.list_workout_programs = AsyncMock()
        return client

    async def test_export_client_creates_directory(self, tmp_path: Path) -> None:
        client = self._mock_client()
        mgr = ExportManager(client)
        path = await mgr.export_client("c1", output_dir=str(tmp_path))
        assert path.exists()
        assert (path / "profile.xlsx").exists()

    async def test_export_client_name_from_data(self, tmp_path: Path) -> None:
        client = self._mock_client()
        mgr = ExportManager(client)
        path = await mgr.export_client("c1", output_dir=str(tmp_path))
        assert "John Doe" in str(path)

    async def test_export_exercise_library(self, tmp_path: Path) -> None:
        client = self._mock_client()
        from kahunas_client.models import Exercise, ExerciseListData, Pagination

        client.list_exercises = AsyncMock(
            return_value=ExerciseListData(
                exercises=[
                    Exercise(exercise_name="Bench Press", exercise_type=1, tags=["chest"]),
                    Exercise(exercise_name="Running", exercise_type=2),
                ],
                total_records=2,
                pagination=Pagination(total=2),
            )
        )
        mgr = ExportManager(client)
        path = await mgr.export_exercise_library(output_dir=str(tmp_path))
        assert path.exists()
        assert path.name == "exercise_library.xlsx"

    async def test_export_workout_programs(self, tmp_path: Path) -> None:
        client = self._mock_client()
        from kahunas_client.models import (
            Pagination,
            WorkoutDay,
            WorkoutProgramDetail,
            WorkoutProgramDetailData,
            WorkoutProgramListData,
            WorkoutProgramSummary,
        )

        client.list_workout_programs = AsyncMock(
            return_value=WorkoutProgramListData(
                workout_plan=[WorkoutProgramSummary(uuid="p1", title="PPL")],
                total_records=1,
                pagination=Pagination(total=1),
            )
        )
        client.get_workout_program = AsyncMock(
            return_value=WorkoutProgramDetailData(
                workout_plan=WorkoutProgramDetail(
                    uuid="p1",
                    title="PPL",
                    workout_days=[WorkoutDay(title="Day 1 - Push", is_restday=0)],
                )
            )
        )
        mgr = ExportManager(client)
        path = await mgr.export_workout_programs(output_dir=str(tmp_path))
        assert path.exists()
        assert (path / "PPL.xlsx").exists()

    async def test_export_all_clients_empty(self, tmp_path: Path) -> None:
        client = self._mock_client()
        mgr = ExportManager(client)
        path = await mgr.export_all_clients(output_dir=str(tmp_path))
        assert path.exists()
        assert (path / "clients_summary.xlsx").exists()
