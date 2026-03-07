"""Tests for the local timeseries metrics store."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from kahunas_client.metrics_store import METRICS, MetricsStore


@pytest.fixture
def store(tmp_path: Path) -> MetricsStore:
    """Create a metrics store with a temporary database."""
    db_path = tmp_path / "test_metrics.db"
    s = MetricsStore(db_path=db_path)
    yield s
    s.close()


# ── METRICS Definitions ──


_EXPECTED_METRICS = [
    ("weight", "Body Weight", "kg", "#2196F3"),
    ("bodyfat", "Body Fat", "%", "#FF9800"),
    ("steps", "Steps", "steps", "#4CAF50"),
    ("chest", "Chest", "cm", "#9C27B0"),
    ("waist", "Waist", "cm", "#F44336"),
    ("hips", "Hips", "cm", "#00BCD4"),
    ("arms", "Arms", "cm", "#FF5722"),
    ("thighs", "Thighs", "cm", "#607D8B"),
]


class TestMetricDefinitions:
    """Ensure all expected metrics are defined with correct metadata."""

    def test_all_metrics_present(self) -> None:
        for name, _label, _unit, _color in _EXPECTED_METRICS:
            assert name in METRICS, f"Missing metric: {name}"

    @pytest.mark.parametrize(
        ("name", "label", "unit", "color"),
        _EXPECTED_METRICS,
        ids=[m[0] for m in _EXPECTED_METRICS],
    )
    def test_metric_metadata(self, name: str, label: str, unit: str, color: str) -> None:
        meta = METRICS[name]
        assert meta["label"] == label, f"{name}: expected label '{label}', got '{meta['label']}'"
        assert meta["unit"] == unit, f"{name}: expected unit '{unit}', got '{meta['unit']}'"
        assert meta["color"] == color, f"{name}: expected color '{color}', got '{meta['color']}'"

    def test_metric_count(self) -> None:
        assert len(METRICS) == 8


# ── Record Single Data Point ──


class TestRecordSingle:
    def test_record_weight(self, store: MetricsStore) -> None:
        result = store.record("client-1", "weight", 85.0, "2024-03-15")
        assert result is True

    def test_record_all_metrics(self, store: MetricsStore) -> None:
        for metric in METRICS:
            result = store.record("client-1", metric, 50.0, "2024-03-15")
            assert result is True

    def test_reject_unknown_metric(self, store: MetricsStore) -> None:
        with pytest.raises(ValueError, match="Unknown metric"):
            store.record("client-1", "blood_pressure", 120.0, "2024-03-15")

    def test_duplicate_is_ignored(self, store: MetricsStore) -> None:
        store.record("client-1", "weight", 85.0, "2024-03-15")
        result = store.record("client-1", "weight", 86.0, "2024-03-15")  # Same date
        assert result is False  # Duplicate ignored

    def test_different_dates_allowed(self, store: MetricsStore) -> None:
        store.record("client-1", "weight", 85.0, "2024-03-15")
        result = store.record("client-1", "weight", 84.5, "2024-03-16")
        assert result is True

    def test_record_with_client_name(self, store: MetricsStore) -> None:
        store.record("client-1", "weight", 85.0, "2024-03-15", client_name="John Doe")
        points = store.query("client-1", "weight")
        assert len(points) == 1


# ── Record Batch ──


class TestRecordBatch:
    def test_batch_insert(self, store: MetricsStore) -> None:
        data = [
            {"date": "2024-01-15", "value": 85.0},
            {"date": "2024-02-15", "value": 83.5},
            {"date": "2024-03-15", "value": 82.0},
        ]
        inserted = store.record_batch("client-1", "weight", data)
        assert inserted == 3

    def test_batch_skips_duplicates(self, store: MetricsStore) -> None:
        data = [
            {"date": "2024-01-15", "value": 85.0},
            {"date": "2024-02-15", "value": 83.5},
        ]
        store.record_batch("client-1", "weight", data)
        inserted = store.record_batch("client-1", "weight", data)
        assert inserted == 0

    def test_batch_skips_invalid_points(self, store: MetricsStore) -> None:
        data = [
            {"date": "2024-01-15", "value": 85.0},
            {"date": "", "value": 83.5},  # Empty date
            {"date": "2024-03-15"},  # Missing value
            {"date": "2024-04-15", "value": "not_a_number"},  # Bad value
        ]
        inserted = store.record_batch("client-1", "weight", data)
        assert inserted == 1  # Only first is valid

    def test_batch_reject_unknown_metric(self, store: MetricsStore) -> None:
        with pytest.raises(ValueError, match="Unknown metric"):
            store.record_batch("client-1", "invalid", [{"date": "2024-01-15", "value": 1}])

    def test_batch_with_recorded_at_key(self, store: MetricsStore) -> None:
        data = [{"recorded_at": "2024-01-15", "value": 85.0}]
        inserted = store.record_batch("client-1", "weight", data)
        assert inserted == 1


# ── Query ──


class TestQuery:
    def test_query_returns_ordered(self, store: MetricsStore) -> None:
        data = [
            {"date": "2024-03-15", "value": 82.0},
            {"date": "2024-01-15", "value": 85.0},
            {"date": "2024-02-15", "value": 83.5},
        ]
        store.record_batch("client-1", "weight", data)
        points = store.query("client-1", "weight")
        assert len(points) == 3
        assert points[0]["date"] == "2024-01-15"
        assert points[1]["date"] == "2024-02-15"
        assert points[2]["date"] == "2024-03-15"

    def test_query_with_date_filter(self, store: MetricsStore) -> None:
        data = [
            {"date": "2024-01-15", "value": 85.0},
            {"date": "2024-02-15", "value": 83.5},
            {"date": "2024-03-15", "value": 82.0},
        ]
        store.record_batch("client-1", "weight", data)
        points = store.query("client-1", "weight", start_date="2024-02-01")
        assert len(points) == 2

    def test_query_with_end_date(self, store: MetricsStore) -> None:
        data = [
            {"date": "2024-01-15", "value": 85.0},
            {"date": "2024-02-15", "value": 83.5},
            {"date": "2024-03-15", "value": 82.0},
        ]
        store.record_batch("client-1", "weight", data)
        points = store.query("client-1", "weight", end_date="2024-02-28")
        assert len(points) == 2

    def test_query_with_limit(self, store: MetricsStore) -> None:
        data = [{"date": f"2024-{i:02d}-15", "value": 80 + i} for i in range(1, 7)]
        store.record_batch("client-1", "weight", data)
        points = store.query("client-1", "weight", limit=3)
        assert len(points) == 3

    def test_query_empty_result(self, store: MetricsStore) -> None:
        points = store.query("nonexistent", "weight")
        assert points == []

    def test_query_separates_clients(self, store: MetricsStore) -> None:
        store.record("client-1", "weight", 85.0, "2024-03-15")
        store.record("client-2", "weight", 75.0, "2024-03-15")
        points1 = store.query("client-1", "weight")
        points2 = store.query("client-2", "weight")
        assert len(points1) == 1
        assert len(points2) == 1
        assert points1[0]["value"] == 85.0
        assert points2[0]["value"] == 75.0

    def test_query_separates_metrics(self, store: MetricsStore) -> None:
        store.record("client-1", "weight", 85.0, "2024-03-15")
        store.record("client-1", "bodyfat", 18.0, "2024-03-15")
        weight = store.query("client-1", "weight")
        bodyfat = store.query("client-1", "bodyfat")
        assert len(weight) == 1
        assert len(bodyfat) == 1
        assert weight[0]["value"] == 85.0
        assert bodyfat[0]["value"] == 18.0


# ── List Clients ──


class TestListClients:
    def test_list_clients(self, store: MetricsStore) -> None:
        store.record("client-1", "weight", 85.0, "2024-03-15", client_name="John Doe")
        store.record("client-2", "weight", 75.0, "2024-03-15", client_name="Jane Smith")
        clients = store.list_clients()
        assert len(clients) == 2
        names = {c["name"] for c in clients}
        assert "John Doe" in names
        assert "Jane Smith" in names

    def test_list_clients_shows_metrics(self, store: MetricsStore) -> None:
        store.record("client-1", "weight", 85.0, "2024-03-15")
        store.record("client-1", "bodyfat", 18.0, "2024-03-15")
        clients = store.list_clients()
        assert len(clients) == 1
        assert "weight" in clients[0]["metrics"]
        assert "bodyfat" in clients[0]["metrics"]

    def test_list_clients_empty(self, store: MetricsStore) -> None:
        clients = store.list_clients()
        assert clients == []


# ── Get Latest ──


class TestGetLatest:
    def test_get_latest(self, store: MetricsStore) -> None:
        data = [
            {"date": "2024-01-15", "value": 85.0},
            {"date": "2024-03-15", "value": 82.0},
            {"date": "2024-02-15", "value": 83.5},
        ]
        store.record_batch("client-1", "weight", data)
        latest = store.get_latest("client-1", "weight")
        assert latest is not None
        assert latest["value"] == 82.0
        assert latest["date"] == "2024-03-15"

    def test_get_latest_nonexistent(self, store: MetricsStore) -> None:
        result = store.get_latest("nonexistent", "weight")
        assert result is None


# ── Delete Client ──


class TestDeleteClient:
    def test_delete_client(self, store: MetricsStore) -> None:
        store.record("client-1", "weight", 85.0, "2024-03-15")
        store.record("client-1", "bodyfat", 18.0, "2024-03-15")
        deleted = store.delete_client("client-1")
        assert deleted == 2
        points = store.query("client-1", "weight")
        assert points == []

    def test_delete_nonexistent(self, store: MetricsStore) -> None:
        deleted = store.delete_client("nonexistent")
        assert deleted == 0

    def test_delete_preserves_other_clients(self, store: MetricsStore) -> None:
        store.record("client-1", "weight", 85.0, "2024-03-15")
        store.record("client-2", "weight", 75.0, "2024-03-15")
        store.delete_client("client-1")
        points = store.query("client-2", "weight")
        assert len(points) == 1


# ── Summary ──


class TestGetSummary:
    def test_summary_with_data(self, store: MetricsStore) -> None:
        data = [
            {"date": "2024-01-15", "value": 85.0},
            {"date": "2024-02-15", "value": 83.0},
            {"date": "2024-03-15", "value": 81.0},
        ]
        store.record_batch("client-1", "weight", data)
        summary = store.get_summary("client-1", "weight")
        assert summary["count"] == 3
        assert summary["min_val"] == 81.0
        assert summary["max_val"] == 85.0
        assert summary["first_value"] == 85.0
        assert summary["last_value"] == 81.0
        assert summary["change"] == -4.0
        assert summary["label"] == "Body Weight"
        assert summary["unit"] == "kg"

    def test_summary_change_percentage(self, store: MetricsStore) -> None:
        data = [
            {"date": "2024-01-15", "value": 100.0},
            {"date": "2024-02-15", "value": 90.0},
        ]
        store.record_batch("client-1", "weight", data)
        summary = store.get_summary("client-1", "weight")
        assert summary["change_pct"] == -10.0

    def test_summary_no_data(self, store: MetricsStore) -> None:
        summary = store.get_summary("nonexistent", "weight")
        assert summary["count"] == 0

    def test_summary_single_point(self, store: MetricsStore) -> None:
        store.record("client-1", "weight", 85.0, "2024-03-15")
        summary = store.get_summary("client-1", "weight")
        assert summary["count"] == 1
        assert summary["change"] == 0.0


# ── Database Persistence ──


class TestPersistence:
    def test_data_persists_after_close(self, tmp_path: Path) -> None:
        db_path = tmp_path / "persist_test.db"
        store1 = MetricsStore(db_path=db_path)
        store1.record("client-1", "weight", 85.0, "2024-03-15")
        store1.close()

        store2 = MetricsStore(db_path=db_path)
        points = store2.query("client-1", "weight")
        assert len(points) == 1
        assert points[0]["value"] == 85.0
        store2.close()

    def test_default_db_path_creation(self) -> None:
        """Verify MetricsStore creates the default directory."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "subdir" / "test.db"
            store = MetricsStore(db_path=db_path)
            assert db_path.parent.exists()
            store.close()
