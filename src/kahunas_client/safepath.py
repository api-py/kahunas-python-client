"""Filesystem safety helpers for names and paths taken from remote data.

Client names, attachment filenames and photo URLs all reach this package
from the Kahunas API. Joining any of them into an output path directly
lets a crafted value escape the directory the caller chose, either with a
traversal sequence or with an absolute path, which ``pathlib`` silently
honours::

    >>> Path("/exports") / "../../etc/cron.d/job"   # escapes via traversal
    >>> Path("/exports") / "/etc/cron.d/job"        # escapes entirely

These helpers reduce an untrusted string to a single, inert path segment
and verify that a completed join stayed inside its base directory.
"""

from __future__ import annotations

import ntpath
import posixpath
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "MAX_SEGMENT_LENGTH",
    "safe_filename",
    "safe_join",
]

MAX_SEGMENT_LENGTH = 120
"""Maximum length of a generated path segment, leaving room for suffixes.

Most filesystems allow 255 bytes per component. Staying well under that
keeps room for the extensions and counters callers append, and avoids
ENAMETOOLONG on encodings where one character costs several bytes.
"""

# Characters that are path separators, shell or filesystem metacharacters, or
# reserved on Windows. Control characters are stripped separately.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')

# Device names Windows refuses to use as a file name, with or without suffix.
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def safe_filename(name: str, fallback: str = "unnamed") -> str:
    """Reduce an untrusted string to one inert filename segment.

    Strips any directory component, removes separators, control characters
    and filesystem metacharacters, and refuses names that would resolve to
    a parent directory or a reserved Windows device.

    Args:
        name: Untrusted candidate name, typically from an API response.
        fallback: Segment to return when nothing usable survives. It is
            sanitised too, so a caller cannot reintroduce a traversal
            through it.

    Returns:
        A single path segment that is safe to join onto a directory. Never
        empty, never ``.`` or ``..``, and never contains a separator.

    Examples:
        >>> safe_filename("../../etc/passwd")
        'passwd'
        >>> safe_filename("/absolute/path/report.xlsx")
        'report.xlsx'
        >>> safe_filename("C:\\\\Windows\\\\system32\\\\evil.dll")
        'evil.dll'
        >>> safe_filename("...")
        'unnamed'
    """
    # Take the final component under both POSIX and Windows rules, so a
    # Windows style path handed to a POSIX host is still reduced.
    candidate = posixpath.basename(ntpath.basename(name or ""))

    # Normalise so visually identical Unicode cannot smuggle a separator.
    candidate = unicodedata.normalize("NFKC", candidate)
    candidate = _UNSAFE_CHARS.sub("_", candidate)

    # A name of only dots resolves to this or the parent directory.
    candidate = candidate.strip().strip(".").strip()
    candidate = candidate[:MAX_SEGMENT_LENGTH].strip()

    if not candidate or set(candidate) <= {"_"}:
        # Guard the fallback too: callers pass API data into it as well.
        return "unnamed" if fallback == "unnamed" else safe_filename(fallback, "unnamed")

    stem = candidate.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        candidate = f"_{candidate}"

    return candidate


def safe_join(base: Path, *segments: str) -> Path:
    """Join sanitised ``segments`` onto ``base`` and confirm the result is inside it.

    Each segment is passed through :func:`safe_filename`, so this is safe
    even when every segment is attacker controlled. The final containment
    check is a defence in depth backstop: it catches escapes through
    symlinks or through any future change that weakens the sanitiser.

    Args:
        base: Directory the result must stay within.
        *segments: Untrusted path segments, applied in order.

    Returns:
        The joined path, guaranteed to be inside ``base``.

    Raises:
        ValueError: If the joined path resolves outside ``base``.
    """
    root = base.expanduser().resolve()
    target = root
    for segment in segments:
        target = target / safe_filename(segment)

    # resolve() follows symlinks, so a symlinked segment pointing outside
    # the base is caught here rather than being written through.
    resolved = target.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Refusing to write outside {root}: {resolved}")
    return resolved
