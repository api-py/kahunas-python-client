"""Incremental SQLite sync for all Kahunas coaching data.

Provides a local mirror of the full Kahunas dataset — clients, check-ins
(with photos), progress metrics, habits, chat messages, workout programs,
and exercises — with delta-only synchronisation so subsequent syncs are fast.

Sync state is tracked per-client per-data-type so partial failures can
resume from the last successful point.

Database location: ``~/.kahunas/sync.db`` (configurable via
``KAHUNAS_SYNC_DB`` env var).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "~/.kahunas/sync.db"

# ── Schema ──────────────────────────────────────────────────────────────

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS sync_state (
    client_uuid TEXT NOT NULL,
    data_type   TEXT NOT NULL,
    last_synced_at TEXT NOT NULL,
    last_id     TEXT NOT NULL DEFAULT '',
    record_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (client_uuid, data_type)
);

CREATE TABLE IF NOT EXISTS clients (
    uuid        TEXT PRIMARY KEY,
    first_name  TEXT NOT NULL DEFAULT '',
    last_name   TEXT NOT NULL DEFAULT '',
    email       TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT '',
    raw_json    TEXT NOT NULL DEFAULT '{}',
    synced_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkins (
    uuid            TEXT PRIMARY KEY,
    client_uuid     TEXT NOT NULL,
    check_in_number INTEGER NOT NULL DEFAULT 0,
    submitted_at    TEXT NOT NULL DEFAULT '',
    weight          REAL,
    waist           REAL,
    hips            REAL,
    biceps          REAL,
    thighs          REAL,
    sleep_quality   REAL,
    nutrition_adherence REAL,
    workout_rating  REAL,
    stress_level    REAL,
    energy_level    REAL,
    mood_wellbeing  REAL,
    water_intake    REAL,
    notes           TEXT NOT NULL DEFAULT '',
    raw_json        TEXT NOT NULL DEFAULT '{}',
    synced_at       TEXT NOT NULL,
    FOREIGN KEY (client_uuid) REFERENCES clients(uuid)
);
CREATE INDEX IF NOT EXISTS idx_checkins_client
    ON checkins(client_uuid, submitted_at);

CREATE TABLE IF NOT EXISTS checkin_photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    checkin_uuid TEXT NOT NULL,
    client_uuid TEXT NOT NULL,
    photo_url   TEXT NOT NULL,
    local_path  TEXT NOT NULL DEFAULT '',
    downloaded  INTEGER NOT NULL DEFAULT 0,
    synced_at   TEXT NOT NULL,
    UNIQUE(checkin_uuid, photo_url),
    FOREIGN KEY (checkin_uuid) REFERENCES checkins(uuid)
);
CREATE INDEX IF NOT EXISTS idx_photos_checkin
    ON checkin_photos(checkin_uuid);
CREATE INDEX IF NOT EXISTS idx_photos_pending
    ON checkin_photos(downloaded) WHERE downloaded = 0;

CREATE TABLE IF NOT EXISTS progress_metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_uuid TEXT NOT NULL,
    metric      TEXT NOT NULL,
    value       REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    synced_at   TEXT NOT NULL,
    UNIQUE(client_uuid, metric, recorded_at),
    FOREIGN KEY (client_uuid) REFERENCES clients(uuid)
);
CREATE INDEX IF NOT EXISTS idx_progress_client_metric
    ON progress_metrics(client_uuid, metric, recorded_at);

CREATE TABLE IF NOT EXISTS habits (
    uuid        TEXT NOT NULL,
    client_uuid TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    date        TEXT NOT NULL DEFAULT '',
    completed   INTEGER NOT NULL DEFAULT 0,
    raw_json    TEXT NOT NULL DEFAULT '{}',
    synced_at   TEXT NOT NULL,
    PRIMARY KEY (uuid, date),
    FOREIGN KEY (client_uuid) REFERENCES clients(uuid)
);
CREATE INDEX IF NOT EXISTS idx_habits_client
    ON habits(client_uuid, date);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY,
    client_uuid TEXT NOT NULL,
    sender_uuid TEXT NOT NULL DEFAULT '',
    message     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT '',
    is_read     INTEGER NOT NULL DEFAULT 0,
    raw_json    TEXT NOT NULL DEFAULT '{}',
    synced_at   TEXT NOT NULL,
    FOREIGN KEY (client_uuid) REFERENCES clients(uuid)
);
CREATE INDEX IF NOT EXISTS idx_chat_client
    ON chat_messages(client_uuid, created_at);

CREATE TABLE IF NOT EXISTS workout_programs (
    uuid        TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    short_desc  TEXT NOT NULL DEFAULT '',
    long_desc   TEXT NOT NULL DEFAULT '',
    days        INTEGER NOT NULL DEFAULT 0,
    tags        TEXT NOT NULL DEFAULT '[]',
    updated_at  TEXT NOT NULL DEFAULT '',
    raw_json    TEXT NOT NULL DEFAULT '{}',
    synced_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exercises (
    uuid            TEXT PRIMARY KEY,
    exercise_name   TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',
    exercise_type   INTEGER NOT NULL DEFAULT 0,
    sets            TEXT NOT NULL DEFAULT '',
    reps            TEXT NOT NULL DEFAULT '',
    tags            TEXT NOT NULL DEFAULT '[]',
    raw_json        TEXT NOT NULL DEFAULT '{}',
    synced_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_uuid TEXT NOT NULL,
    parent_type TEXT NOT NULL DEFAULT '',
    file_url    TEXT NOT NULL,
    file_name   TEXT NOT NULL DEFAULT '',
    local_path  TEXT NOT NULL DEFAULT '',
    downloaded  INTEGER NOT NULL DEFAULT 0,
    synced_at   TEXT NOT NULL,
    UNIQUE(parent_uuid, file_url)
);
CREATE INDEX IF NOT EXISTS idx_attachments_parent
    ON attachments(parent_uuid);
CREATE INDEX IF NOT EXISTS idx_attachments_pending
    ON attachments(downloaded) WHERE downloaded = 0;
"""


# ── Helpers ─────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _to_float(val: Any) -> float | None:
    if val is None or val == "" or val == "N/A":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_json(obj: Any) -> str:
    return json.dumps(obj, default=str, separators=(",", ":"))


def _extract_photos(checkin: dict[str, Any]) -> list[str]:
    """Extract photo URLs from a check-in dict."""
    urls: list[str] = []
    for key in ("photos", "images", "progress_photos"):
        photos = checkin.get(key, [])
        if isinstance(photos, list):
            for p in photos:
                if isinstance(p, str) and p.startswith("http"):
                    urls.append(p)
                elif isinstance(p, dict):
                    url = p.get("file_url", p.get("url", p.get("image_url", "")))
                    if url and url.startswith("http"):
                        urls.append(url)
    return urls


def _extract_attachments(item: dict[str, Any]) -> list[dict[str, str]]:
    """Extract media/attachment entries from exercises or programs."""
    attachments: list[dict[str, str]] = []
    media = item.get("media", [])
    if isinstance(media, list):
        for m in media:
            if isinstance(m, dict):
                url = m.get("file_url", "")
                if url:
                    attachments.append(
                        {
                            "file_url": url,
                            "file_name": m.get("file_name", ""),
                        }
                    )
    return attachments


# ── SyncStore ───────────────────────────────────────────────────────────


class SyncStore:
    """Local SQLite mirror of all Kahunas coaching data with delta sync."""

    def __init__(self, db_path: str | None = None) -> None:
        resolved = db_path or os.getenv("KAHUNAS_SYNC_DB", _DEFAULT_DB_PATH)
        self._db_path = Path(resolved).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def __enter__(self) -> SyncStore:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _init_schema(self) -> None:
        for statement in _SCHEMA_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                self._conn.execute(stmt)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── Sync state ──────────────────────────────────────────────────────

    def get_sync_state(self, client_uuid: str, data_type: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM sync_state WHERE client_uuid=? AND data_type=?",
            (client_uuid, data_type),
        ).fetchone()
        return dict(row) if row else None

    def set_sync_state(
        self,
        client_uuid: str,
        data_type: str,
        record_count: int = 0,
        last_id: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO sync_state
                   (client_uuid, data_type, last_synced_at, last_id, record_count)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(client_uuid, data_type)
                   DO UPDATE SET last_synced_at=excluded.last_synced_at,
                                 last_id=excluded.last_id,
                                 record_count=excluded.record_count""",
                (client_uuid, data_type, _now(), last_id, record_count),
            )
            self._conn.commit()

    # ── Clients ─────────────────────────────────────────────────────────

    def upsert_client(self, client: dict[str, Any]) -> bool:
        uuid = client.get("uuid", client.get("id", ""))
        if not uuid:
            return False
        with self._lock:
            self._conn.execute(
                """INSERT INTO clients
                   (uuid, first_name, last_name, email, phone, status, raw_json, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(uuid)
                   DO UPDATE SET first_name=excluded.first_name, last_name=excluded.last_name,
                                 email=excluded.email, phone=excluded.phone, status=excluded.status,
                                 raw_json=excluded.raw_json, synced_at=excluded.synced_at""",
                (
                    str(uuid),
                    client.get("first_name", ""),
                    client.get("last_name", ""),
                    client.get("email", ""),
                    client.get("phone", ""),
                    client.get("status", ""),
                    _safe_json(client),
                    _now(),
                ),
            )
            self._conn.commit()
        return True

    def upsert_clients(self, clients: list[dict[str, Any]]) -> int:
        count = 0
        with self._lock:
            for c in clients:
                uuid = c.get("uuid", c.get("id", ""))
                if not uuid:
                    continue
                self._conn.execute(
                    """INSERT INTO clients
                       (uuid, first_name, last_name, email, phone, status, raw_json, synced_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(uuid)
                       DO UPDATE SET first_name=excluded.first_name, last_name=excluded.last_name,
                                     email=excluded.email, phone=excluded.phone,
                                     status=excluded.status, raw_json=excluded.raw_json,
                                     synced_at=excluded.synced_at""",
                    (
                        str(uuid),
                        c.get("first_name", ""),
                        c.get("last_name", ""),
                        c.get("email", ""),
                        c.get("phone", ""),
                        c.get("status", ""),
                        _safe_json(c),
                        _now(),
                    ),
                )
                count += 1
            self._conn.commit()
        return count

    def list_clients(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT uuid, first_name, last_name, email, phone, status, synced_at FROM clients"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Check-ins ───────────────────────────────────────────────────────

    def _upsert_checkin_no_commit(
        self, client_uuid: str, checkin: dict[str, Any]
    ) -> tuple[bool, int]:
        """Upsert a single check-in without committing (caller manages tx)."""
        uuid = checkin.get("uuid", "")
        if not uuid:
            return False, 0
        now = _now()
        self._conn.execute(
            """INSERT INTO checkins
               (uuid, client_uuid, check_in_number, submitted_at,
                weight, waist, hips, biceps, thighs,
                sleep_quality, nutrition_adherence, workout_rating,
                stress_level, energy_level, mood_wellbeing, water_intake,
                notes, raw_json, synced_at)
               VALUES (?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?,?, ?,?,?)
               ON CONFLICT(uuid) DO UPDATE SET
                weight=excluded.weight, waist=excluded.waist,
                hips=excluded.hips, biceps=excluded.biceps, thighs=excluded.thighs,
                sleep_quality=excluded.sleep_quality,
                nutrition_adherence=excluded.nutrition_adherence,
                workout_rating=excluded.workout_rating,
                stress_level=excluded.stress_level,
                energy_level=excluded.energy_level,
                mood_wellbeing=excluded.mood_wellbeing,
                water_intake=excluded.water_intake,
                notes=excluded.notes, raw_json=excluded.raw_json,
                synced_at=excluded.synced_at""",
            (
                uuid,
                client_uuid,
                checkin.get("check_in_number", 0),
                checkin.get("submitted_at", checkin.get("date", "")),
                _to_float(checkin.get("weight")),
                _to_float(checkin.get("waist")),
                _to_float(checkin.get("hips")),
                _to_float(checkin.get("biceps")),
                _to_float(checkin.get("thighs")),
                _to_float(checkin.get("sleep_quality")),
                _to_float(checkin.get("nutrition_adherence")),
                _to_float(checkin.get("workout_rating")),
                _to_float(checkin.get("stress_level")),
                _to_float(checkin.get("energy_level")),
                _to_float(checkin.get("mood_wellbeing")),
                _to_float(checkin.get("water_intake")),
                checkin.get("notes", ""),
                _safe_json(checkin),
                now,
            ),
        )

        photo_count = 0
        for url in _extract_photos(checkin):
            self._conn.execute(
                """INSERT INTO checkin_photos
                   (checkin_uuid, client_uuid, photo_url, synced_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(checkin_uuid, photo_url) DO NOTHING""",
                (uuid, client_uuid, url, now),
            )
            photo_count += 1

        return True, photo_count

    def upsert_checkin(self, client_uuid: str, checkin: dict[str, Any]) -> tuple[bool, int]:
        """Upsert a check-in and its photos. Returns (inserted, photo_count)."""
        with self._lock:
            result = self._upsert_checkin_no_commit(client_uuid, checkin)
            self._conn.commit()
        return result

    def upsert_checkins(self, client_uuid: str, checkins: list[dict[str, Any]]) -> dict[str, int]:
        inserted = 0
        photos = 0
        with self._lock:
            for ci in checkins:
                ok, pc = self._upsert_checkin_no_commit(client_uuid, ci)
                if ok:
                    inserted += 1
                photos += pc
            self._conn.commit()
        return {"checkins": inserted, "photos": photos}

    def get_client_checkin_count(self, client_uuid: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM checkins WHERE client_uuid=?",
            (client_uuid,),
        ).fetchone()
        return row["cnt"] if row else 0

    def get_latest_checkin_number(self, client_uuid: str) -> int:
        row = self._conn.execute(
            "SELECT MAX(check_in_number) AS max_num FROM checkins WHERE client_uuid=?",
            (client_uuid,),
        ).fetchone()
        return row["max_num"] or 0 if row else 0

    # ── Progress metrics ────────────────────────────────────────────────

    def upsert_progress(
        self,
        client_uuid: str,
        metric: str,
        data_points: list[dict[str, Any]],
    ) -> int:
        now = _now()
        inserted = 0
        with self._lock:
            for pt in data_points:
                date_str = pt.get("date", pt.get("label", ""))
                val = _to_float(pt.get("value", pt.get("y")))
                if not date_str or val is None:
                    continue
                try:
                    self._conn.execute(
                        """INSERT INTO progress_metrics
                           (client_uuid, metric, value, recorded_at, synced_at)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(client_uuid, metric, recorded_at)
                           DO UPDATE SET value=excluded.value, synced_at=excluded.synced_at""",
                        (client_uuid, metric, val, date_str, now),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
            self._conn.commit()
        return inserted

    def get_progress_count(self, client_uuid: str, metric: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM progress_metrics WHERE client_uuid=? AND metric=?",
            (client_uuid, metric),
        ).fetchone()
        return row["cnt"] if row else 0

    # ── Habits ──────────────────────────────────────────────────────────

    def upsert_habits(self, client_uuid: str, habits: list[dict[str, Any]]) -> int:
        now = _now()
        inserted = 0
        with self._lock:
            for h in habits:
                uuid = h.get("uuid", "")
                if not uuid:
                    continue
                self._conn.execute(
                    """INSERT INTO habits
                       (uuid, client_uuid, title, date, completed, raw_json, synced_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(uuid, date) DO UPDATE SET
                       completed=excluded.completed, raw_json=excluded.raw_json,
                       synced_at=excluded.synced_at""",
                    (
                        uuid,
                        client_uuid,
                        h.get("title", ""),
                        h.get("date", ""),
                        1 if h.get("completed") else 0,
                        _safe_json(h),
                        now,
                    ),
                )
                inserted += 1
            self._conn.commit()
        return inserted

    # ── Chat messages ───────────────────────────────────────────────────

    def upsert_chat_messages(self, client_uuid: str, messages: list[dict[str, Any]]) -> int:
        now = _now()
        inserted = 0
        with self._lock:
            for msg in messages:
                msg_id = msg.get("id", 0)
                if not msg_id:
                    continue
                self._conn.execute(
                    """INSERT INTO chat_messages
                       (id, client_uuid, sender_uuid, message, created_at, is_read,
                        raw_json, synced_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                       is_read=excluded.is_read, raw_json=excluded.raw_json,
                       synced_at=excluded.synced_at""",
                    (
                        int(msg_id),
                        client_uuid,
                        msg.get("sender_uuid", msg.get("sender_name", "")),
                        msg.get("message", ""),
                        msg.get("created_at", ""),
                        1 if msg.get("read") else 0,
                        _safe_json(msg),
                        now,
                    ),
                )
                inserted += 1
            self._conn.commit()
        return inserted

    def get_last_chat_id(self, client_uuid: str) -> int:
        row = self._conn.execute(
            "SELECT MAX(id) AS max_id FROM chat_messages WHERE client_uuid=?",
            (client_uuid,),
        ).fetchone()
        return row["max_id"] or 0 if row else 0

    # ── Workout programs ────────────────────────────────────────────────

    def upsert_workout_program(self, program: dict[str, Any]) -> bool:
        uuid = program.get("uuid", "")
        if not uuid:
            return False
        tags = program.get("tags", [])
        with self._lock:
            self._conn.execute(
                """INSERT INTO workout_programs
                   (uuid, title, short_desc, long_desc, days, tags, updated_at, raw_json, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(uuid) DO UPDATE SET
                   title=excluded.title, short_desc=excluded.short_desc,
                   long_desc=excluded.long_desc, days=excluded.days,
                   tags=excluded.tags, updated_at=excluded.updated_at,
                   raw_json=excluded.raw_json, synced_at=excluded.synced_at""",
                (
                    uuid,
                    program.get("title", ""),
                    program.get("short_desc", ""),
                    program.get("long_desc", ""),
                    program.get("days", len(program.get("workout_days", []))),
                    _safe_json(tags if isinstance(tags, list) else []),
                    program.get("updated_at", ""),
                    _safe_json(program),
                    _now(),
                ),
            )
            for att in _extract_attachments(program):
                self._upsert_attachment(uuid, "workout_program", att)
            self._conn.commit()
        return True

    def upsert_workout_programs(self, programs: list[dict[str, Any]]) -> int:
        count = 0
        with self._lock:
            for p in programs:
                uuid = p.get("uuid", "")
                if not uuid:
                    continue
                tags = p.get("tags", [])
                self._conn.execute(
                    """INSERT INTO workout_programs
                       (uuid, title, short_desc, long_desc, days, tags,
                        updated_at, raw_json, synced_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(uuid) DO UPDATE SET
                       title=excluded.title, short_desc=excluded.short_desc,
                       long_desc=excluded.long_desc, days=excluded.days,
                       tags=excluded.tags, updated_at=excluded.updated_at,
                       raw_json=excluded.raw_json, synced_at=excluded.synced_at""",
                    (
                        uuid,
                        p.get("title", ""),
                        p.get("short_desc", ""),
                        p.get("long_desc", ""),
                        p.get("days", len(p.get("workout_days", []))),
                        _safe_json(tags if isinstance(tags, list) else []),
                        p.get("updated_at", ""),
                        _safe_json(p),
                        _now(),
                    ),
                )
                for att in _extract_attachments(p):
                    self._upsert_attachment(uuid, "workout_program", att)
                count += 1
            self._conn.commit()
        return count

    # ── Exercises ───────────────────────────────────────────────────────

    def upsert_exercise(self, exercise: dict[str, Any]) -> bool:
        uuid = exercise.get("uuid", "")
        if not uuid:
            return False
        tags = exercise.get("tags", [])
        with self._lock:
            self._conn.execute(
                """INSERT INTO exercises
                   (uuid, exercise_name, title, exercise_type, sets, reps,
                    tags, raw_json, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(uuid) DO UPDATE SET
                   exercise_name=excluded.exercise_name, title=excluded.title,
                   exercise_type=excluded.exercise_type, sets=excluded.sets,
                   reps=excluded.reps, tags=excluded.tags,
                   raw_json=excluded.raw_json, synced_at=excluded.synced_at""",
                (
                    uuid,
                    exercise.get("exercise_name", ""),
                    exercise.get("title", ""),
                    exercise.get("exercise_type", 0),
                    str(exercise.get("sets", "")),
                    str(exercise.get("reps", "")),
                    _safe_json(tags if isinstance(tags, list) else []),
                    _safe_json(exercise),
                    _now(),
                ),
            )
            for att in _extract_attachments(exercise):
                self._upsert_attachment(uuid, "exercise", att)
            self._conn.commit()
        return True

    def upsert_exercises(self, exercises: list[dict[str, Any]]) -> int:
        count = 0
        with self._lock:
            for e in exercises:
                uuid = e.get("uuid", "")
                if not uuid:
                    continue
                tags = e.get("tags", [])
                self._conn.execute(
                    """INSERT INTO exercises
                       (uuid, exercise_name, title, exercise_type, sets, reps,
                        tags, raw_json, synced_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(uuid) DO UPDATE SET
                       exercise_name=excluded.exercise_name, title=excluded.title,
                       exercise_type=excluded.exercise_type, sets=excluded.sets,
                       reps=excluded.reps, tags=excluded.tags,
                       raw_json=excluded.raw_json, synced_at=excluded.synced_at""",
                    (
                        uuid,
                        e.get("exercise_name", ""),
                        e.get("title", ""),
                        e.get("exercise_type", 0),
                        str(e.get("sets", "")),
                        str(e.get("reps", "")),
                        _safe_json(tags if isinstance(tags, list) else []),
                        _safe_json(e),
                        _now(),
                    ),
                )
                for att in _extract_attachments(e):
                    self._upsert_attachment(uuid, "exercise", att)
                count += 1
            self._conn.commit()
        return count

    # ── Attachments ─────────────────────────────────────────────────────

    def _upsert_attachment(self, parent_uuid: str, parent_type: str, att: dict[str, str]) -> None:
        self._conn.execute(
            """INSERT INTO attachments
               (parent_uuid, parent_type, file_url, file_name, synced_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(parent_uuid, file_url) DO NOTHING""",
            (
                parent_uuid,
                parent_type,
                att.get("file_url", ""),
                att.get("file_name", ""),
                _now(),
            ),
        )

    def mark_attachment_downloaded(self, parent_uuid: str, file_url: str, local_path: str) -> None:
        with self._lock:
            self._conn.execute(
                """UPDATE attachments SET downloaded=1, local_path=?
                   WHERE parent_uuid=? AND file_url=?""",
                (local_path, parent_uuid, file_url),
            )
            self._conn.commit()

    def mark_photo_downloaded(self, checkin_uuid: str, photo_url: str, local_path: str) -> None:
        with self._lock:
            self._conn.execute(
                """UPDATE checkin_photos SET downloaded=1, local_path=?
                   WHERE checkin_uuid=? AND photo_url=?""",
                (local_path, checkin_uuid, photo_url),
            )
            self._conn.commit()

    def get_pending_photos(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT checkin_uuid, client_uuid, photo_url
               FROM checkin_photos WHERE downloaded=0 LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_pending_attachments(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT parent_uuid, parent_type, file_url, file_name
               FROM attachments WHERE downloaded=0 LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Summary / stats ─────────────────────────────────────────────────

    _ALLOWED_TABLES = frozenset(
        {
            "clients",
            "checkins",
            "checkin_photos",
            "progress_metrics",
            "habits",
            "chat_messages",
            "workout_programs",
            "exercises",
            "attachments",
        }
    )

    def get_sync_summary(self) -> dict[str, Any]:
        """Return counts of all synced data."""

        def _count(table: str) -> int:
            if table not in self._ALLOWED_TABLES:
                raise ValueError(f"Invalid table name: {table}")
            row = self._conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
            return row["c"] if row else 0

        return {
            "db_path": str(self._db_path),
            "clients": _count("clients"),
            "checkins": _count("checkins"),
            "checkin_photos": _count("checkin_photos"),
            "checkin_photos_downloaded": self._conn.execute(
                "SELECT COUNT(*) AS c FROM checkin_photos WHERE downloaded=1"
            ).fetchone()["c"],
            "progress_metrics": _count("progress_metrics"),
            "habits": _count("habits"),
            "chat_messages": _count("chat_messages"),
            "workout_programs": _count("workout_programs"),
            "exercises": _count("exercises"),
            "attachments": _count("attachments"),
            "attachments_downloaded": self._conn.execute(
                "SELECT COUNT(*) AS c FROM attachments WHERE downloaded=1"
            ).fetchone()["c"],
        }

    def query_checkins(self, client_uuid: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT uuid, check_in_number, submitted_at, weight, waist, hips,
                      biceps, thighs, sleep_quality, nutrition_adherence,
                      workout_rating, stress_level, energy_level,
                      mood_wellbeing, water_intake, notes
               FROM checkins WHERE client_uuid=?
               ORDER BY submitted_at DESC LIMIT ?""",
            (client_uuid, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def query_progress(
        self, client_uuid: str, metric: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT metric, value, recorded_at
               FROM progress_metrics
               WHERE client_uuid=? AND metric=?
               ORDER BY recorded_at DESC LIMIT ?""",
            (client_uuid, metric, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def query_chat(self, client_uuid: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT id, sender_uuid, message, created_at, is_read
               FROM chat_messages WHERE client_uuid=?
               ORDER BY created_at DESC LIMIT ?""",
            (client_uuid, limit),
        ).fetchall()
        return [dict(r) for r in rows]
