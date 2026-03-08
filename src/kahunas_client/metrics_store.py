"""Local timeseries database for client metrics.

Stores client progress data (weight, body fat, steps, measurements)
locally in SQLite so charts can be generated from cached data without
requiring a live API connection.

The database is created at ``~/.kahunas/metrics.db`` by default
(configurable via ``KAHUNAS_METRICS_DB`` env var).

Supported metrics:
    weight, bodyfat, steps, chest, waist, hips, arms, thighs
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# All supported metrics with default metadata.
# Units for weight and measurements are configurable via KahunasConfig
# (KAHUNAS_WEIGHT_UNIT, KAHUNAS_HEIGHT_UNIT, etc.) to match the Kahunas
# coach/configuration page settings.
METRICS = {
    "weight": {"label": "Body Weight", "unit": "kg", "color": "#2196F3"},
    "bodyfat": {"label": "Body Fat", "unit": "%", "color": "#FF9800"},
    "steps": {"label": "Steps", "unit": "steps", "color": "#4CAF50"},
    "chest": {"label": "Chest", "unit": "cm", "color": "#9C27B0"},
    "waist": {"label": "Waist", "unit": "cm", "color": "#F44336"},
    "hips": {"label": "Hips", "unit": "cm", "color": "#00BCD4"},
    "arms": {"label": "Arms", "unit": "cm", "color": "#FF5722"},
    "thighs": {"label": "Thighs", "unit": "cm", "color": "#607D8B"},
}

# Valid unit choices for configurable measurement settings
# (from Kahunas coach/configuration page)
MEASUREMENT_SETTINGS = {
    "weight": {"options": ["kg", "lbs"], "default": "kg"},
    "height": {"options": ["cm", "inches"], "default": "cm"},
    "glucose": {"options": ["mmol_l", "mg_dl"], "default": "mmol_l"},
    "food": {"options": ["grams", "ounces", "qty", "cups", "oz", "ml", "tsp"], "default": "grams"},
    "water": {"options": ["ml", "l", "oz"], "default": "ml"},
}


def get_metrics_with_units(
    weight_unit: str = "kg",
    height_unit: str = "cm",
) -> dict[str, dict[str, str]]:
    """Return METRICS dict with units adjusted to configured settings.

    Args:
        weight_unit: 'kg' or 'lbs' (from KahunasConfig.weight_unit).
        height_unit: 'cm' or 'inches' (from KahunasConfig.height_unit).

    Returns:
        Copy of METRICS with adjusted unit values.
    """
    adjusted = {}
    measurement_unit = "inches" if height_unit == "inches" else "cm"
    for key, meta in METRICS.items():
        entry = dict(meta)
        if key == "weight":
            entry["unit"] = weight_unit
        elif key in ("chest", "waist", "hips", "arms", "thighs"):
            entry["unit"] = measurement_unit
        adjusted[key] = entry
    return adjusted


_DEFAULT_DB_DIR = Path.home() / ".kahunas"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "metrics.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS client_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_uuid TEXT NOT NULL,
    client_name TEXT NOT NULL DEFAULT '',
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'kahunas',
    UNIQUE(client_uuid, metric, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_client_metric
    ON client_metrics(client_uuid, metric, recorded_at);

CREATE INDEX IF NOT EXISTS idx_metric_date
    ON client_metrics(metric, recorded_at);
"""


class MetricsStore:
    """Local SQLite timeseries store for client progress metrics.

    Usage::

        store = MetricsStore()
        store.record("client-uuid-123", "weight", 85.0, "2024-03-15", name="John Doe")
        points = store.query("client-uuid-123", "weight")
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            env_path = os.environ.get("KAHUNAS_METRICS_DB", "")
            db_path = Path(env_path) if env_path else _DEFAULT_DB_PATH

        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def record(
        self,
        client_uuid: str,
        metric: str,
        value: float,
        recorded_at: str,
        client_name: str = "",
        source: str = "kahunas",
    ) -> bool:
        """Record a single metric data point.

        Args:
            client_uuid: Kahunas client UUID.
            metric: Metric name (weight, bodyfat, steps, etc.).
            value: Metric value.
            recorded_at: ISO date string when the measurement was taken.
            client_name: Optional client name for display.
            source: Data source identifier.

        Returns:
            True if inserted, False if duplicate (already exists).
        """
        if metric not in METRICS:
            raise ValueError(f"Unknown metric: '{metric}'. Valid: {', '.join(sorted(METRICS))}")

        conn = self._get_conn()
        synced_at = datetime.now(UTC).isoformat()
        try:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO client_metrics
                    (client_uuid, client_name, metric, value, recorded_at, synced_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (client_uuid, client_name, metric, value, recorded_at, synced_at, source),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error:
            logger.exception("Failed to record metric %s for %s", metric, client_uuid)
            return False

    def record_batch(
        self,
        client_uuid: str,
        metric: str,
        data_points: list[dict[str, Any]],
        client_name: str = "",
        source: str = "kahunas",
    ) -> int:
        """Record multiple data points for a client metric.

        Each data point dict should have 'date' (or 'recorded_at')
        and 'value' keys.

        Args:
            client_uuid: Kahunas client UUID.
            metric: Metric name.
            data_points: List of {date, value} dicts.
            client_name: Optional client name.
            source: Data source identifier.

        Returns:
            Number of new records inserted.
        """
        if metric not in METRICS:
            raise ValueError(f"Unknown metric: '{metric}'. Valid: {', '.join(sorted(METRICS))}")

        conn = self._get_conn()
        synced_at = datetime.now(UTC).isoformat()
        inserted = 0

        for point in data_points:
            date = point.get("date", point.get("recorded_at", ""))
            value = point.get("value")
            if not date or value is None:
                continue
            try:
                val = float(value)
            except (TypeError, ValueError):
                continue
            try:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO client_metrics
                        (client_uuid, client_name, metric, value, recorded_at, synced_at, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (client_uuid, client_name, metric, val, str(date), synced_at, source),
                )
                inserted += cursor.rowcount
            except sqlite3.Error:
                logger.exception("Failed to insert data point: %s", point)
                continue

        conn.commit()
        return inserted

    def query(
        self,
        client_uuid: str,
        metric: str,
        start_date: str = "",
        end_date: str = "",
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """Query stored metric data points for a client.

        Args:
            client_uuid: Kahunas client UUID.
            metric: Metric name.
            start_date: Optional start date filter (inclusive).
            end_date: Optional end date filter (inclusive).
            limit: Maximum number of points to return (0 = no limit).

        Returns:
            List of {date, value, synced_at} dicts, ordered by date.
        """
        conn = self._get_conn()
        sql = """
            SELECT recorded_at AS date, value, synced_at
            FROM client_metrics
            WHERE client_uuid = ? AND metric = ?
        """
        params: list[Any] = [client_uuid, metric]

        if start_date:
            sql += " AND recorded_at >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND recorded_at <= ?"
            params.append(end_date)

        sql += " ORDER BY recorded_at ASC"

        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_clients(self) -> list[dict[str, Any]]:
        """List all clients that have stored metrics.

        Returns:
            List of {uuid, name, metrics, first_date, last_date} dicts.
        """
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT
                client_uuid AS uuid,
                MAX(client_name) AS name,
                GROUP_CONCAT(DISTINCT metric) AS metrics,
                MIN(recorded_at) AS first_date,
                MAX(recorded_at) AS last_date,
                COUNT(*) AS data_points
            FROM client_metrics
            GROUP BY client_uuid
            ORDER BY MAX(recorded_at) DESC
            """
        ).fetchall()
        return [
            {
                "uuid": row["uuid"],
                "name": row["name"],
                "metrics": row["metrics"].split(",") if row["metrics"] else [],
                "first_date": row["first_date"],
                "last_date": row["last_date"],
                "data_points": row["data_points"],
            }
            for row in rows
        ]

    def get_latest(
        self,
        client_uuid: str,
        metric: str,
    ) -> dict[str, Any] | None:
        """Get the most recent data point for a client metric.

        Returns:
            Dict with {date, value, synced_at} or None.
        """
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT recorded_at AS date, value, synced_at
            FROM client_metrics
            WHERE client_uuid = ? AND metric = ?
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            (client_uuid, metric),
        ).fetchone()
        return dict(row) if row else None

    def delete_client(self, client_uuid: str) -> int:
        """Delete all stored metrics for a client.

        Args:
            client_uuid: Kahunas client UUID.

        Returns:
            Number of records deleted.
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM client_metrics WHERE client_uuid = ?",
            (client_uuid,),
        )
        conn.commit()
        return cursor.rowcount

    def get_summary(
        self,
        client_uuid: str,
        metric: str,
    ) -> dict[str, Any]:
        """Get summary statistics for a client metric.

        Returns:
            Dict with min, max, avg, count, first_date, last_date, change.
        """
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT
                MIN(value) AS min_val,
                MAX(value) AS max_val,
                AVG(value) AS avg_val,
                COUNT(*) AS count,
                MIN(recorded_at) AS first_date,
                MAX(recorded_at) AS last_date
            FROM client_metrics
            WHERE client_uuid = ? AND metric = ?
            """,
            (client_uuid, metric),
        ).fetchone()

        if not row or row["count"] == 0:
            return {"count": 0}

        result = dict(row)

        # Calculate change from first to last
        first = conn.execute(
            """
            SELECT value FROM client_metrics
            WHERE client_uuid = ? AND metric = ?
            ORDER BY recorded_at ASC LIMIT 1
            """,
            (client_uuid, metric),
        ).fetchone()
        last = conn.execute(
            """
            SELECT value FROM client_metrics
            WHERE client_uuid = ? AND metric = ?
            ORDER BY recorded_at DESC LIMIT 1
            """,
            (client_uuid, metric),
        ).fetchone()

        if first and last:
            result["first_value"] = first["value"]
            result["last_value"] = last["value"]
            result["change"] = round(last["value"] - first["value"], 2)
            if first["value"] != 0:
                result["change_pct"] = round(
                    (last["value"] - first["value"]) / first["value"] * 100, 1
                )

        # Add metric metadata
        meta = METRICS.get(metric, {})
        result["label"] = meta.get("label", metric)
        result["unit"] = meta.get("unit", "")

        return result
