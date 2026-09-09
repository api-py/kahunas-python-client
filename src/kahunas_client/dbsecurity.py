"""Filesystem permissions for the local SQLite stores.

Both local databases hold client personal and health data: names, contact
details, body measurements, check-in notes and chat history. SQLite creates
a new database with the process umask, which on most systems leaves it
world readable, and the write ahead log and shared memory files it creates
alongside inherit the same mode.

These helpers restrict the database directory and every file SQLite keeps
in it to the owning user.
"""

from __future__ import annotations

import logging
import stat
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["DB_DIR_MODE", "DB_FILE_MODE", "prepare_db_directory", "restrict_db_permissions"]

DB_DIR_MODE = 0o700
"""Owner only access for the directory holding the databases."""

DB_FILE_MODE = 0o600
"""Owner only read and write for the database and its sidecar files."""

# SQLite keeps the write ahead log and shared memory files beside the
# database, and both contain the same client data as the database itself.
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def prepare_db_directory(db_path: Path) -> None:
    """Create the parent directory of ``db_path`` with owner only access.

    An existing directory is left as it is: the user may have chosen to
    share it deliberately, and silently tightening a directory that holds
    unrelated files would be surprising.
    """
    parent = db_path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True, mode=DB_DIR_MODE)


def restrict_db_permissions(db_path: Path) -> None:
    """Restrict ``db_path`` and its SQLite sidecar files to the owner.

    Called after the connection is opened, so the files SQLite created
    exist. Failures are logged rather than raised: on a filesystem that
    does not carry POSIX modes, such as a mounted Windows share, the
    database is still perfectly usable.
    """
    for path in (db_path, *(_sidecar(db_path, suffix) for suffix in _SIDECAR_SUFFIXES)):
        if not path.exists():
            continue
        try:
            current = stat.S_IMODE(path.stat().st_mode)
            if current != DB_FILE_MODE:
                path.chmod(DB_FILE_MODE)
        except OSError as exc:
            logger.warning(
                "Could not restrict permissions on %s (%s). "
                "This database holds client data; check its mode manually.",
                path,
                exc,
            )


def _sidecar(db_path: Path, suffix: str) -> Path:
    """Return the path of a SQLite sidecar file beside ``db_path``."""
    return db_path.with_name(db_path.name + suffix)
