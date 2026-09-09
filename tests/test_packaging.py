"""Tests for the distribution's own metadata.

A release ships whatever these values say, so they are worth pinning: a
wheel that misreports its version, loses its typing marker, or drops a
console entry point is broken in a way no other test would notice.
"""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

import pytest

import kahunas_client

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


class TestVersion:
    """The runtime attribute and the distribution metadata must agree."""

    def test_runtime_version_matches_installed_distribution(self) -> None:
        """These used to be declared separately and could silently drift."""
        assert metadata.version("kahunas-client") == kahunas_client.__version__

    def test_version_is_pep440_parseable(self) -> None:
        from packaging.version import Version

        Version(kahunas_client.__version__)

    def test_version_is_not_hardcoded_in_pyproject(self, pyproject: dict) -> None:
        """It is derived from __init__ so the two cannot disagree."""
        project = pyproject["project"]
        assert "version" not in project
        assert "version" in project.get("dynamic", [])


class TestDistributionMetadata:
    """Fields an index displays, and the ones packaging correctness needs."""

    def test_declares_a_licence(self) -> None:
        meta = metadata.metadata("kahunas-client")
        assert meta.get("License-Expression") or meta.get("License")

    def test_licence_file_is_present_in_the_repository(self) -> None:
        assert (_PYPROJECT.parent / "LICENSE").is_file()

    def test_requires_a_supported_python(self) -> None:
        assert metadata.metadata("kahunas-client")["Requires-Python"] == ">=3.12"

    def test_declares_classifiers_and_urls(self, pyproject: dict) -> None:
        project = pyproject["project"]
        assert project["classifiers"]
        assert project["urls"]

    def test_ships_the_pep561_typing_marker(self) -> None:
        """Without py.typed, downstream type checkers ignore the package."""
        marker = Path(kahunas_client.__file__).parent / "py.typed"
        assert marker.is_file()


class TestEntryPoints:
    """Both console commands must resolve from the installed distribution."""

    @pytest.mark.parametrize("command", ["kahunas", "kahunas-mcp"])
    def test_console_script_is_declared(self, command: str) -> None:
        scripts = {ep.name for ep in metadata.entry_points(group="console_scripts")}
        assert command in scripts

    @pytest.mark.parametrize("command", ["kahunas", "kahunas-mcp"])
    def test_console_script_target_is_importable(self, command: str) -> None:
        (entry,) = [
            ep for ep in metadata.entry_points(group="console_scripts") if ep.name == command
        ]
        assert callable(entry.load())


class TestGeneratedFilesAreNotCommitted:
    """`uv export` output must not be committed alongside uv.lock.

    A committed export is never installed from: the Dockerfile runs the
    export itself during the build. It only drifts from uv.lock, and it
    attracts dependency bots, which raise pull requests against pins that
    nothing reads while the real lockfile goes unwatched.
    """

    def test_the_docker_export_is_absent(self) -> None:
        assert not (_PYPROJECT.parent / "dockerreq.txt").exists()

    def test_the_docker_export_is_ignored(self) -> None:
        ignored = (_PYPROJECT.parent / ".gitignore").read_text(encoding="utf-8").split()
        assert "dockerreq.txt" in ignored

    def test_the_lockfile_is_the_only_committed_pin_set(self) -> None:
        """uv.lock is the single source of dependency truth."""
        root = _PYPROJECT.parent
        assert (root / "uv.lock").is_file()
        exports = [p.name for p in root.glob("*.txt") if p.name.startswith("requirements")]
        assert exports == []
