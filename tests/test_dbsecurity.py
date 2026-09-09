"""Tests for local database file permissions.

Both SQLite stores hold client personal and health data. SQLite creates
them with the process umask, which typically leaves them world readable.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from kahunas_client.data_sync import SyncStore
from kahunas_client.dbsecurity import (
    DB_DIR_MODE,
    DB_FILE_MODE,
    prepare_db_directory,
    restrict_db_permissions,
)
from kahunas_client.metrics_store import MetricsStore

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX file modes are not meaningful on Windows"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestPrepareDbDirectory:
    """Directory creation."""

    def test_creates_missing_directory_owner_only(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "store.db"
        prepare_db_directory(db_path)
        assert db_path.parent.is_dir()
        assert _mode(db_path.parent) == DB_DIR_MODE

    def test_leaves_an_existing_directory_alone(self, tmp_path: Path) -> None:
        """Tightening a directory the user already had would be surprising."""
        existing = tmp_path / "existing"
        existing.mkdir(mode=0o755)
        prepare_db_directory(existing / "store.db")
        assert _mode(existing) == 0o755


class TestRestrictDbPermissions:
    """File mode tightening, including SQLite sidecar files."""

    def test_restricts_the_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "store.db"
        db_path.write_bytes(b"")
        db_path.chmod(0o644)
        restrict_db_permissions(db_path)
        assert _mode(db_path) == DB_FILE_MODE

    @pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
    def test_restricts_sidecar_files(self, suffix: str, tmp_path: Path) -> None:
        """The write ahead log holds the same client data as the database."""
        db_path = tmp_path / "store.db"
        db_path.write_bytes(b"")
        sidecar = tmp_path / f"store.db{suffix}"
        sidecar.write_bytes(b"")
        sidecar.chmod(0o644)

        restrict_db_permissions(db_path)
        assert _mode(sidecar) == DB_FILE_MODE

    def test_missing_files_are_skipped(self, tmp_path: Path) -> None:
        restrict_db_permissions(tmp_path / "absent.db")

    def test_survives_an_unchangeable_file(self, tmp_path: Path, monkeypatch: object) -> None:
        """A filesystem without POSIX modes must not break the store."""
        db_path = tmp_path / "store.db"
        db_path.write_bytes(b"")

        def refuse(*args: object, **kwargs: object) -> None:
            raise OSError("read-only filesystem")

        monkeypatch.setattr(Path, "chmod", refuse)  # type: ignore[attr-defined]
        restrict_db_permissions(db_path)


class TestStoresApplyPermissions:
    """The stores wire the helpers in, not just export them."""

    def test_sync_store_database_is_owner_only(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sync.db"
        with SyncStore(str(db_path)):
            pass
        assert _mode(db_path) == DB_FILE_MODE

    def test_sync_store_wal_is_owner_only(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sync.db"
        store = SyncStore(str(db_path))
        try:
            wal = tmp_path / "sync.db-wal"
            if wal.exists():
                assert _mode(wal) == DB_FILE_MODE
        finally:
            store.close()

    def test_metrics_store_database_is_owner_only(self, tmp_path: Path) -> None:
        db_path = tmp_path / "metrics.db"
        store = MetricsStore(db_path)
        try:
            store.record("client-1", "weight", 82.5, "2024-03-15")
        finally:
            store.close()
        assert _mode(db_path) == DB_FILE_MODE

    def test_database_is_not_group_or_world_readable(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sync.db"
        with SyncStore(str(db_path)):
            pass
        mode = _mode(db_path)
        assert not mode & stat.S_IRGRP
        assert not mode & stat.S_IROTH
        assert not mode & stat.S_IWOTH

    def test_permissions_hold_regardless_of_umask(self, tmp_path: Path) -> None:
        """A permissive umask must not leave the database readable."""
        previous = os.umask(0o000)
        try:
            db_path = tmp_path / "sync.db"
            with SyncStore(str(db_path)):
                pass
            assert _mode(db_path) == DB_FILE_MODE
        finally:
            os.umask(previous)
