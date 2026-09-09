"""Tests for filesystem safety helpers.

The traversal cases are regression tests: attachment filenames and client
names arrive from the API and were previously joined onto an output
directory without sanitisation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kahunas_client.safepath import MAX_SEGMENT_LENGTH, safe_filename, safe_join


class TestSafeFilenameTraversal:
    """Escapes that the unsanitised join allowed."""

    @pytest.mark.parametrize(
        ("hostile", "expected"),
        [
            ("../../etc/passwd", "passwd"),
            ("../../../root/.ssh/authorized_keys", "authorized_keys"),
            ("/etc/cron.d/backdoor", "backdoor"),
            ("/absolute/report.xlsx", "report.xlsx"),
            ("dir/sub/file.txt", "file.txt"),
        ],
    )
    def test_strips_directory_components(self, hostile: str, expected: str) -> None:
        assert safe_filename(hostile) == expected

    def test_strips_windows_directory_components(self) -> None:
        assert safe_filename("C:\\Windows\\system32\\evil.dll") == "evil.dll"

    def test_result_never_contains_a_separator(self) -> None:
        for hostile in ("a/b", "a\\b", "..%2f..%2fetc", "a:b"):
            result = safe_filename(hostile)
            assert "/" not in result
            assert "\\" not in result

    @pytest.mark.parametrize("hostile", ["..", ".", "...", "", "   ", "/", "//", "./"])
    def test_degenerate_names_fall_back(self, hostile: str) -> None:
        assert safe_filename(hostile) == "unnamed"

    def test_hostile_fallback_is_sanitised_too(self) -> None:
        """A caller must not reintroduce traversal through the fallback."""
        assert safe_filename("", fallback="../../escape") == "escape"

    def test_hostile_fallback_that_is_itself_degenerate(self) -> None:
        assert safe_filename("..", fallback="..") == "unnamed"


class TestSafeFilenameHygiene:
    """Non traversal hardening."""

    def test_removes_control_characters(self) -> None:
        assert "\n" not in safe_filename("report\nname.txt")
        assert "\x00" not in safe_filename("report\x00.txt")

    def test_keeps_ordinary_names_intact(self) -> None:
        assert safe_filename("Jane Doe.xlsx") == "Jane Doe.xlsx"
        assert safe_filename("check-in_2024-03-15.pdf") == "check-in_2024-03-15.pdf"

    def test_truncates_overlong_names(self) -> None:
        result = safe_filename("a" * 500)
        assert len(result) <= MAX_SEGMENT_LENGTH

    def test_prefixes_reserved_windows_device_names(self) -> None:
        assert safe_filename("CON") == "_CON"
        assert safe_filename("com1.txt") == "_com1.txt"

    def test_normalises_unicode_lookalikes(self) -> None:
        """NFKC folding stops a compatibility character standing in for a separator."""
        assert "/" not in safe_filename("a\uff0fb")


class TestSafeJoin:
    """Containment of a completed join."""

    def test_joins_sanitised_segments(self, tmp_path: Path) -> None:
        result = safe_join(tmp_path, "photos", "client.jpg")
        assert result == (tmp_path / "photos" / "client.jpg").resolve()

    @pytest.mark.parametrize(
        "hostile",
        ["../../etc/passwd", "/etc/passwd", "..", "../sibling"],
    )
    def test_hostile_segments_stay_inside_base(self, hostile: str, tmp_path: Path) -> None:
        result = safe_join(tmp_path, hostile)
        assert tmp_path.resolve() in result.parents

    def test_rejects_escape_through_a_symlink(self, tmp_path: Path) -> None:
        """The containment check is the backstop when a segment is a symlink."""
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (base / "link").symlink_to(outside, target_is_directory=True)

        with pytest.raises(ValueError, match="Refusing to write outside"):
            safe_join(base, "link", "captured.txt")

    def test_base_itself_is_permitted(self, tmp_path: Path) -> None:
        assert safe_join(tmp_path) == tmp_path.resolve()
