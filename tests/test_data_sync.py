"""Tests for the incremental SQLite sync store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kahunas_client.data_sync import (
    SyncStore,
    _extract_attachments,
    _extract_photos,
    _safe_json,
    _to_float,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> SyncStore:
    """Create a sync store with a temporary database."""
    db_path = tmp_path / "test_sync.db"
    s = SyncStore(db_path=str(db_path))
    yield s
    s.close()


def _make_client(
    uuid: str = "client-001",
    first_name: str = "John",
    last_name: str = "Doe",
    email: str = "john@example.com",
    phone: str = "+447700900123",
    status: str = "active",
) -> dict[str, Any]:
    return {
        "uuid": uuid,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "status": status,
    }


def _make_checkin(
    uuid: str = "ci-001",
    check_in_number: int = 1,
    submitted_at: str = "2024-03-01",
    weight: float = 85.0,
    waist: float = 90.0,
    photos: list[str] | None = None,
) -> dict[str, Any]:
    ci: dict[str, Any] = {
        "uuid": uuid,
        "check_in_number": check_in_number,
        "submitted_at": submitted_at,
        "weight": weight,
        "waist": waist,
        "hips": 100.0,
        "sleep_quality": 7.5,
        "nutrition_adherence": 8.0,
        "workout_rating": 7.0,
        "stress_level": 3.0,
        "energy_level": 7.0,
        "mood_wellbeing": 8.0,
        "notes": "Feeling good",
    }
    if photos:
        ci["photos"] = photos
    return ci


# ── Helper Functions ─────────────────────────────────────────────────────


class TestToFloat:
    def test_valid_float(self) -> None:
        assert _to_float(85.5) == 85.5

    def test_valid_int(self) -> None:
        assert _to_float(85) == 85.0

    def test_valid_string(self) -> None:
        assert _to_float("85.5") == 85.5

    def test_none(self) -> None:
        assert _to_float(None) is None

    def test_empty_string(self) -> None:
        assert _to_float("") is None

    def test_na_string(self) -> None:
        assert _to_float("N/A") is None

    def test_invalid_string(self) -> None:
        assert _to_float("not a number") is None

    def test_zero(self) -> None:
        assert _to_float(0) == 0.0

    def test_negative(self) -> None:
        assert _to_float(-1.5) == -1.5


class TestSafeJson:
    def test_dict(self) -> None:
        result = _safe_json({"a": 1, "b": "hello"})
        assert '"a":1' in result
        assert '"b":"hello"' in result

    def test_list(self) -> None:
        result = _safe_json([1, 2, 3])
        assert result == "[1,2,3]"

    def test_empty_dict(self) -> None:
        assert _safe_json({}) == "{}"


class TestExtractPhotos:
    def test_string_urls(self) -> None:
        checkin = {"photos": ["https://example.com/photo1.jpg", "https://example.com/photo2.jpg"]}
        urls = _extract_photos(checkin)
        assert len(urls) == 2
        assert urls[0] == "https://example.com/photo1.jpg"

    def test_dict_photos_file_url(self) -> None:
        checkin = {
            "photos": [
                {"file_url": "https://example.com/photo1.jpg"},
                {"file_url": "https://example.com/photo2.jpg"},
            ]
        }
        urls = _extract_photos(checkin)
        assert len(urls) == 2

    def test_dict_photos_url_key(self) -> None:
        checkin = {"photos": [{"url": "https://example.com/photo1.jpg"}]}
        urls = _extract_photos(checkin)
        assert len(urls) == 1

    def test_dict_photos_image_url_key(self) -> None:
        checkin = {"images": [{"image_url": "https://example.com/photo1.jpg"}]}
        urls = _extract_photos(checkin)
        assert len(urls) == 1

    def test_progress_photos_key(self) -> None:
        checkin = {"progress_photos": ["https://example.com/progress.jpg"]}
        urls = _extract_photos(checkin)
        assert len(urls) == 1

    def test_multiple_keys(self) -> None:
        checkin = {
            "photos": ["https://example.com/p1.jpg"],
            "images": ["https://example.com/p2.jpg"],
            "progress_photos": ["https://example.com/p3.jpg"],
        }
        urls = _extract_photos(checkin)
        assert len(urls) == 3

    def test_no_photos(self) -> None:
        assert _extract_photos({}) == []

    def test_empty_photos(self) -> None:
        assert _extract_photos({"photos": []}) == []

    def test_non_http_urls_skipped(self) -> None:
        checkin = {"photos": ["not-a-url", "https://example.com/valid.jpg"]}
        urls = _extract_photos(checkin)
        assert len(urls) == 1

    def test_dict_with_empty_url(self) -> None:
        checkin = {"photos": [{"file_url": ""}]}
        assert _extract_photos(checkin) == []

    def test_mixed_formats(self) -> None:
        checkin = {
            "photos": [
                "https://example.com/str.jpg",
                {"file_url": "https://example.com/dict.jpg"},
                42,  # non-string, non-dict — should be skipped
            ]
        }
        urls = _extract_photos(checkin)
        assert len(urls) == 2


class TestExtractAttachments:
    def test_media_list(self) -> None:
        item = {
            "media": [
                {"file_url": "https://example.com/video.mp4", "file_name": "demo.mp4"},
                {"file_url": "https://example.com/doc.pdf", "file_name": "plan.pdf"},
            ]
        }
        atts = _extract_attachments(item)
        assert len(atts) == 2
        assert atts[0]["file_url"] == "https://example.com/video.mp4"
        assert atts[0]["file_name"] == "demo.mp4"

    def test_no_media(self) -> None:
        assert _extract_attachments({}) == []

    def test_empty_media(self) -> None:
        assert _extract_attachments({"media": []}) == []

    def test_media_without_url_skipped(self) -> None:
        item = {"media": [{"file_name": "no-url.pdf"}]}
        assert _extract_attachments(item) == []

    def test_media_non_dict_skipped(self) -> None:
        item = {"media": ["not-a-dict", 42]}
        assert _extract_attachments(item) == []


# ── SyncStore Init ───────────────────────────────────────────────────────


class TestSyncStoreInit:
    def test_creates_db_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "new_sync.db"
        store = SyncStore(db_path=str(db_path))
        assert db_path.exists()
        store.close()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "deep" / "path" / "sync.db"
        store = SyncStore(db_path=str(db_path))
        assert db_path.exists()
        store.close()

    def test_wal_mode(self, store: SyncStore) -> None:
        row = store._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_foreign_keys_enabled(self, store: SyncStore) -> None:
        row = store._conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1

    def test_tables_created(self, store: SyncStore) -> None:
        tables = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(r[0] for r in tables)
        expected = sorted(
            [
                "sync_state",
                "clients",
                "checkins",
                "checkin_photos",
                "progress_metrics",
                "habits",
                "chat_messages",
                "workout_programs",
                "exercises",
                "attachments",
            ]
        )
        # sqlite_sequence is auto-created by SQLite for AUTOINCREMENT columns
        filtered = [t for t in table_names if t != "sqlite_sequence"]
        assert filtered == expected

    def test_env_var_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_path = tmp_path / "env_sync.db"
        monkeypatch.setenv("KAHUNAS_SYNC_DB", str(db_path))
        store = SyncStore()
        assert store._db_path == db_path
        store.close()


# ── Sync State ───────────────────────────────────────────────────────────


class TestSyncState:
    def test_get_returns_none_initially(self, store: SyncStore) -> None:
        assert store.get_sync_state("c1", "checkins") is None

    def test_set_and_get(self, store: SyncStore) -> None:
        store.set_sync_state("c1", "checkins", record_count=10, last_id="ci-10")
        state = store.get_sync_state("c1", "checkins")
        assert state is not None
        assert state["client_uuid"] == "c1"
        assert state["data_type"] == "checkins"
        assert state["record_count"] == 10
        assert state["last_id"] == "ci-10"

    def test_update_existing(self, store: SyncStore) -> None:
        store.set_sync_state("c1", "checkins", record_count=5)
        store.set_sync_state("c1", "checkins", record_count=10)
        state = store.get_sync_state("c1", "checkins")
        assert state is not None
        assert state["record_count"] == 10

    def test_separate_data_types(self, store: SyncStore) -> None:
        store.set_sync_state("c1", "checkins", record_count=5)
        store.set_sync_state("c1", "habits", record_count=3)
        ci_state = store.get_sync_state("c1", "checkins")
        h_state = store.get_sync_state("c1", "habits")
        assert ci_state is not None
        assert ci_state["record_count"] == 5
        assert h_state is not None
        assert h_state["record_count"] == 3


# ── Clients ──────────────────────────────────────────────────────────────


class TestClients:
    def test_upsert_client(self, store: SyncStore) -> None:
        c = _make_client()
        assert store.upsert_client(c) is True

    def test_upsert_client_no_uuid(self, store: SyncStore) -> None:
        assert store.upsert_client({"name": "test"}) is False

    def test_upsert_client_id_fallback(self, store: SyncStore) -> None:
        assert store.upsert_client({"id": "c-alt"}) is True

    def test_list_clients(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1", "Alice"))
        store.upsert_client(_make_client("c2", "Bob"))
        clients = store.list_clients()
        assert len(clients) == 2

    def test_upsert_updates_existing(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1", "Alice", phone="+440000"))
        store.upsert_client(_make_client("c1", "Alice", phone="+441111"))
        clients = store.list_clients()
        assert len(clients) == 1
        assert clients[0]["phone"] == "+441111"

    def test_upsert_clients_batch(self, store: SyncStore) -> None:
        clients = [_make_client(f"c{i}") for i in range(5)]
        count = store.upsert_clients(clients)
        assert count == 5
        assert len(store.list_clients()) == 5

    def test_upsert_clients_with_invalid(self, store: SyncStore) -> None:
        clients = [_make_client("c1"), {"name": "no-uuid"}, _make_client("c2")]
        count = store.upsert_clients(clients)
        assert count == 2

    def test_client_stores_raw_json(self, store: SyncStore) -> None:
        c = _make_client("c1", "Alice")
        store.upsert_client(c)
        row = store._conn.execute("SELECT raw_json FROM clients WHERE uuid='c1'").fetchone()
        assert row is not None
        assert '"first_name":"Alice"' in row["raw_json"]


# ── Check-ins ────────────────────────────────────────────────────────────


class TestCheckins:
    def test_upsert_checkin(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        ok, photos = store.upsert_checkin("c1", _make_checkin())
        assert ok is True
        assert photos == 0

    def test_upsert_checkin_no_uuid(self, store: SyncStore) -> None:
        ok, photos = store.upsert_checkin("c1", {"weight": 80})
        assert ok is False
        assert photos == 0

    def test_upsert_checkin_with_photos(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        ci = _make_checkin(photos=["https://example.com/p1.jpg", "https://example.com/p2.jpg"])
        ok, photos = store.upsert_checkin("c1", ci)
        assert ok is True
        assert photos == 2

    def test_upsert_checkin_idempotent(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        ci = _make_checkin()
        store.upsert_checkin("c1", ci)
        store.upsert_checkin("c1", ci)
        count = store.get_client_checkin_count("c1")
        assert count == 1

    def test_upsert_checkins_batch(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        checkins = [_make_checkin(f"ci-{i}", i, f"2024-03-{i + 1:02d}") for i in range(3)]
        result = store.upsert_checkins("c1", checkins)
        assert result["checkins"] == 3
        assert result["photos"] == 0

    def test_get_client_checkin_count(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        assert store.get_client_checkin_count("c1") == 0
        store.upsert_checkin("c1", _make_checkin("ci-1", 1))
        store.upsert_checkin("c1", _make_checkin("ci-2", 2))
        assert store.get_client_checkin_count("c1") == 2

    def test_get_latest_checkin_number(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        assert store.get_latest_checkin_number("c1") == 0
        store.upsert_checkin("c1", _make_checkin("ci-1", 5))
        store.upsert_checkin("c1", _make_checkin("ci-2", 3))
        assert store.get_latest_checkin_number("c1") == 5

    def test_checkin_stores_all_fields(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        ci = _make_checkin(weight=82.5, waist=88.0)
        store.upsert_checkin("c1", ci)
        rows = store.query_checkins("c1")
        assert len(rows) == 1
        assert rows[0]["weight"] == 82.5
        assert rows[0]["waist"] == 88.0
        assert rows[0]["notes"] == "Feeling good"

    def test_checkin_update_on_conflict(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        ci = _make_checkin(weight=85.0)
        store.upsert_checkin("c1", ci)
        ci["weight"] = 83.0
        store.upsert_checkin("c1", ci)
        rows = store.query_checkins("c1")
        assert rows[0]["weight"] == 83.0

    def test_photo_deduplication(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        ci = _make_checkin(photos=["https://example.com/p1.jpg"])
        store.upsert_checkin("c1", ci)
        store.upsert_checkin("c1", ci)
        rows = store._conn.execute("SELECT COUNT(*) AS c FROM checkin_photos").fetchone()
        assert rows["c"] == 1


# ── Progress Metrics ─────────────────────────────────────────────────────


class TestProgressMetrics:
    def test_upsert_progress(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        pts = [
            {"date": "2024-03-01", "value": 85.0},
            {"date": "2024-03-08", "value": 84.5},
        ]
        count = store.upsert_progress("c1", "weight", pts)
        assert count == 2

    def test_upsert_progress_skips_invalid(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        pts = [
            {"date": "2024-03-01", "value": 85.0},
            {"date": "", "value": 84.5},  # missing date
            {"date": "2024-03-03"},  # missing value
        ]
        count = store.upsert_progress("c1", "weight", pts)
        assert count == 1

    def test_progress_idempotent(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        pts = [{"date": "2024-03-01", "value": 85.0}]
        store.upsert_progress("c1", "weight", pts)
        store.upsert_progress("c1", "weight", pts)
        assert store.get_progress_count("c1", "weight") == 1

    def test_progress_update_on_conflict(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        store.upsert_progress("c1", "weight", [{"date": "2024-03-01", "value": 85.0}])
        store.upsert_progress("c1", "weight", [{"date": "2024-03-01", "value": 84.0}])
        data = store.query_progress("c1", "weight")
        assert len(data) == 1
        assert data[0]["value"] == 84.0

    def test_get_progress_count(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        assert store.get_progress_count("c1", "weight") == 0
        store.upsert_progress(
            "c1",
            "weight",
            [
                {"date": "2024-03-01", "value": 85.0},
                {"date": "2024-03-02", "value": 84.0},
            ],
        )
        assert store.get_progress_count("c1", "weight") == 2

    def test_progress_label_fallback(self, store: SyncStore) -> None:
        """Uses 'label' key when 'date' is missing."""
        store.upsert_client(_make_client("c1"))
        pts = [{"label": "2024-03-01", "y": 85.0}]
        count = store.upsert_progress("c1", "weight", pts)
        assert count == 1


# ── Habits ───────────────────────────────────────────────────────────────


class TestHabits:
    def test_upsert_habits(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        habits = [
            {"uuid": "h1", "title": "Drink water", "date": "2024-03-01", "completed": True},
            {"uuid": "h2", "title": "Stretch", "date": "2024-03-01", "completed": False},
        ]
        count = store.upsert_habits("c1", habits)
        assert count == 2

    def test_habits_skip_no_uuid(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        habits = [{"title": "No UUID", "date": "2024-03-01"}]
        count = store.upsert_habits("c1", habits)
        assert count == 0

    def test_habits_idempotent(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        habits = [{"uuid": "h1", "title": "Drink water", "date": "2024-03-01", "completed": True}]
        store.upsert_habits("c1", habits)
        store.upsert_habits("c1", habits)
        row = store._conn.execute("SELECT COUNT(*) AS c FROM habits").fetchone()
        assert row["c"] == 1

    def test_habits_update_completed(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        habits = [{"uuid": "h1", "title": "Drink water", "date": "2024-03-01", "completed": False}]
        store.upsert_habits("c1", habits)
        habits[0]["completed"] = True
        store.upsert_habits("c1", habits)
        row = store._conn.execute("SELECT completed FROM habits WHERE uuid='h1'").fetchone()
        assert row["completed"] == 1


# ── Chat Messages ────────────────────────────────────────────────────────


class TestChatMessages:
    def test_upsert_messages(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        messages = [
            {"id": 1, "sender_uuid": "coach1", "message": "Hello!", "created_at": "2024-03-01"},
            {"id": 2, "sender_uuid": "c1", "message": "Hi!", "created_at": "2024-03-01"},
        ]
        count = store.upsert_chat_messages("c1", messages)
        assert count == 2

    def test_messages_skip_no_id(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        messages = [{"message": "No ID"}]
        count = store.upsert_chat_messages("c1", messages)
        assert count == 0

    def test_messages_idempotent(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        messages = [{"id": 1, "message": "Hello!", "created_at": "2024-03-01"}]
        store.upsert_chat_messages("c1", messages)
        store.upsert_chat_messages("c1", messages)
        row = store._conn.execute("SELECT COUNT(*) AS c FROM chat_messages").fetchone()
        assert row["c"] == 1

    def test_get_last_chat_id(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        assert store.get_last_chat_id("c1") == 0
        store.upsert_chat_messages(
            "c1",
            [
                {"id": 5, "message": "A", "created_at": "2024-03-01"},
                {"id": 10, "message": "B", "created_at": "2024-03-02"},
            ],
        )
        assert store.get_last_chat_id("c1") == 10

    def test_query_chat(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        store.upsert_chat_messages(
            "c1",
            [
                {"id": 1, "sender_uuid": "coach", "message": "Hello!", "created_at": "2024-03-01"},
                {"id": 2, "sender_uuid": "c1", "message": "Hi!", "created_at": "2024-03-02"},
            ],
        )
        msgs = store.query_chat("c1")
        assert len(msgs) == 2
        # Sorted DESC by created_at
        assert msgs[0]["message"] == "Hi!"

    def test_query_chat_limit(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        store.upsert_chat_messages(
            "c1",
            [
                {"id": i, "message": f"msg-{i}", "created_at": f"2024-03-{i + 1:02d}"}
                for i in range(1, 6)
            ],
        )
        msgs = store.query_chat("c1", limit=2)
        assert len(msgs) == 2


# ── Workout Programs ────────────────────────────────────────────────────


class TestWorkoutPrograms:
    def test_upsert_program(self, store: SyncStore) -> None:
        program = {
            "uuid": "wp-001",
            "title": "Strength Program",
            "short_desc": "8 weeks",
            "long_desc": "Full body strength",
            "days": 4,
            "tags": ["strength", "beginner"],
        }
        assert store.upsert_workout_program(program) is True

    def test_program_no_uuid(self, store: SyncStore) -> None:
        assert store.upsert_workout_program({"title": "No UUID"}) is False

    def test_program_idempotent(self, store: SyncStore) -> None:
        program = {"uuid": "wp-001", "title": "Strength"}
        store.upsert_workout_program(program)
        store.upsert_workout_program(program)
        row = store._conn.execute("SELECT COUNT(*) AS c FROM workout_programs").fetchone()
        assert row["c"] == 1

    def test_program_update_on_conflict(self, store: SyncStore) -> None:
        store.upsert_workout_program({"uuid": "wp-001", "title": "V1"})
        store.upsert_workout_program({"uuid": "wp-001", "title": "V2"})
        row = store._conn.execute(
            "SELECT title FROM workout_programs WHERE uuid='wp-001'"
        ).fetchone()
        assert row["title"] == "V2"

    def test_upsert_programs_batch(self, store: SyncStore) -> None:
        programs = [{"uuid": f"wp-{i}", "title": f"Prog {i}"} for i in range(3)]
        count = store.upsert_workout_programs(programs)
        assert count == 3

    def test_program_with_media(self, store: SyncStore) -> None:
        program = {
            "uuid": "wp-001",
            "title": "With Video",
            "media": [
                {"file_url": "https://example.com/video.mp4", "file_name": "demo.mp4"},
            ],
        }
        store.upsert_workout_program(program)
        atts = store.get_pending_attachments()
        assert len(atts) == 1
        assert atts[0]["file_url"] == "https://example.com/video.mp4"

    def test_program_days_from_workout_days(self, store: SyncStore) -> None:
        program = {"uuid": "wp-001", "workout_days": [1, 2, 3]}
        store.upsert_workout_program(program)
        row = store._conn.execute(
            "SELECT days FROM workout_programs WHERE uuid='wp-001'"
        ).fetchone()
        assert row["days"] == 3


# ── Exercises ────────────────────────────────────────────────────────────


class TestExercises:
    def test_upsert_exercise(self, store: SyncStore) -> None:
        ex = {
            "uuid": "ex-001",
            "exercise_name": "Bench Press",
            "title": "Flat Bench Press",
            "exercise_type": 1,
            "sets": "4",
            "reps": "8-10",
        }
        assert store.upsert_exercise(ex) is True

    def test_exercise_no_uuid(self, store: SyncStore) -> None:
        assert store.upsert_exercise({"exercise_name": "test"}) is False

    def test_exercise_idempotent(self, store: SyncStore) -> None:
        ex = {"uuid": "ex-001", "exercise_name": "Bench"}
        store.upsert_exercise(ex)
        store.upsert_exercise(ex)
        row = store._conn.execute("SELECT COUNT(*) AS c FROM exercises").fetchone()
        assert row["c"] == 1

    def test_upsert_exercises_batch(self, store: SyncStore) -> None:
        exercises = [{"uuid": f"ex-{i}", "exercise_name": f"Ex {i}"} for i in range(4)]
        count = store.upsert_exercises(exercises)
        assert count == 4

    def test_exercise_with_media(self, store: SyncStore) -> None:
        ex = {
            "uuid": "ex-001",
            "exercise_name": "Bench",
            "media": [{"file_url": "https://example.com/bench.mp4", "file_name": "bench.mp4"}],
        }
        store.upsert_exercise(ex)
        atts = store.get_pending_attachments()
        assert len(atts) == 1


# ── Attachments ──────────────────────────────────────────────────────────


class TestAttachments:
    def test_mark_attachment_downloaded(self, store: SyncStore) -> None:
        store.upsert_workout_program(
            {
                "uuid": "wp-001",
                "media": [{"file_url": "https://example.com/v.mp4", "file_name": "v.mp4"}],
            }
        )
        pending = store.get_pending_attachments()
        assert len(pending) == 1

        store.mark_attachment_downloaded("wp-001", "https://example.com/v.mp4", "/local/v.mp4")
        pending = store.get_pending_attachments()
        assert len(pending) == 0

    def test_attachment_deduplication(self, store: SyncStore) -> None:
        program = {
            "uuid": "wp-001",
            "media": [{"file_url": "https://example.com/v.mp4", "file_name": "v.mp4"}],
        }
        store.upsert_workout_program(program)
        store.upsert_workout_program(program)
        row = store._conn.execute("SELECT COUNT(*) AS c FROM attachments").fetchone()
        assert row["c"] == 1


# ── Photos ───────────────────────────────────────────────────────────────


class TestPhotos:
    def test_pending_photos(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        ci = _make_checkin(photos=["https://example.com/p1.jpg", "https://example.com/p2.jpg"])
        store.upsert_checkin("c1", ci)
        pending = store.get_pending_photos()
        assert len(pending) == 2

    def test_mark_photo_downloaded(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        ci = _make_checkin(photos=["https://example.com/p1.jpg"])
        store.upsert_checkin("c1", ci)
        pending = store.get_pending_photos()
        assert len(pending) == 1

        store.mark_photo_downloaded("ci-001", "https://example.com/p1.jpg", "/local/p1.jpg")
        pending = store.get_pending_photos()
        assert len(pending) == 0

    def test_pending_photos_limit(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        photos = [f"https://example.com/p{i}.jpg" for i in range(10)]
        ci = _make_checkin(photos=photos)
        store.upsert_checkin("c1", ci)
        pending = store.get_pending_photos(limit=3)
        assert len(pending) == 3


# ── Summary & Queries ────────────────────────────────────────────────────


class TestSyncSummary:
    def test_empty_summary(self, store: SyncStore) -> None:
        summary = store.get_sync_summary()
        assert summary["clients"] == 0
        assert summary["checkins"] == 0
        assert summary["checkin_photos"] == 0
        assert summary["checkin_photos_downloaded"] == 0
        assert summary["progress_metrics"] == 0
        assert summary["habits"] == 0
        assert summary["chat_messages"] == 0
        assert summary["workout_programs"] == 0
        assert summary["exercises"] == 0
        assert summary["attachments"] == 0
        assert summary["attachments_downloaded"] == 0
        assert "db_path" in summary

    def test_summary_with_data(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        store.upsert_checkin("c1", _make_checkin())
        store.upsert_progress("c1", "weight", [{"date": "2024-03-01", "value": 85.0}])
        store.upsert_habits("c1", [{"uuid": "h1", "title": "Water", "date": "2024-03-01"}])
        store.upsert_chat_messages("c1", [{"id": 1, "message": "Hi", "created_at": "2024-03-01"}])
        store.upsert_workout_program({"uuid": "wp-001", "title": "Strength"})
        store.upsert_exercise({"uuid": "ex-001", "exercise_name": "Bench"})

        summary = store.get_sync_summary()
        assert summary["clients"] == 1
        assert summary["checkins"] == 1
        assert summary["progress_metrics"] == 1
        assert summary["habits"] == 1
        assert summary["chat_messages"] == 1
        assert summary["workout_programs"] == 1
        assert summary["exercises"] == 1


class TestQueryCheckins:
    def test_query_checkins_order(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        store.upsert_checkin("c1", _make_checkin("ci-1", 1, "2024-03-01"))
        store.upsert_checkin("c1", _make_checkin("ci-2", 2, "2024-03-08"))
        store.upsert_checkin("c1", _make_checkin("ci-3", 3, "2024-03-15"))
        checkins = store.query_checkins("c1")
        assert len(checkins) == 3
        # Sorted DESC by submitted_at
        assert checkins[0]["submitted_at"] == "2024-03-15"

    def test_query_checkins_limit(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        for i in range(5):
            store.upsert_checkin("c1", _make_checkin(f"ci-{i}", i, f"2024-03-{i + 1:02d}"))
        checkins = store.query_checkins("c1", limit=2)
        assert len(checkins) == 2

    def test_query_checkins_empty(self, store: SyncStore) -> None:
        assert store.query_checkins("nonexistent") == []


class TestQueryProgress:
    def test_query_progress_order(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        store.upsert_progress(
            "c1",
            "weight",
            [
                {"date": "2024-03-01", "value": 85.0},
                {"date": "2024-03-08", "value": 84.0},
                {"date": "2024-03-15", "value": 83.0},
            ],
        )
        data = store.query_progress("c1", "weight")
        assert len(data) == 3
        # Sorted DESC
        assert data[0]["recorded_at"] == "2024-03-15"

    def test_query_progress_metric_filter(self, store: SyncStore) -> None:
        store.upsert_client(_make_client("c1"))
        store.upsert_progress("c1", "weight", [{"date": "2024-03-01", "value": 85.0}])
        store.upsert_progress("c1", "bodyfat", [{"date": "2024-03-01", "value": 15.0}])
        weight_data = store.query_progress("c1", "weight")
        bf_data = store.query_progress("c1", "bodyfat")
        assert len(weight_data) == 1
        assert len(bf_data) == 1
        assert weight_data[0]["value"] == 85.0
        assert bf_data[0]["value"] == 15.0

    def test_query_progress_empty(self, store: SyncStore) -> None:
        assert store.query_progress("nonexistent", "weight") == []


# ── Close / Reopen ───────────────────────────────────────────────────────


class TestCloseReopen:
    def test_data_persists_after_close(self, tmp_path: Path) -> None:
        db_path = tmp_path / "persist.db"
        s1 = SyncStore(db_path=str(db_path))
        s1.upsert_client(_make_client("c1", "Alice"))
        s1.close()

        s2 = SyncStore(db_path=str(db_path))
        clients = s2.list_clients()
        assert len(clients) == 1
        assert clients[0]["first_name"] == "Alice"
        s2.close()

    def test_schema_idempotent(self, tmp_path: Path) -> None:
        """Opening the same DB twice doesn't error on CREATE IF NOT EXISTS."""
        db_path = tmp_path / "idempotent.db"
        s1 = SyncStore(db_path=str(db_path))
        s1.close()
        s2 = SyncStore(db_path=str(db_path))
        s2.close()
