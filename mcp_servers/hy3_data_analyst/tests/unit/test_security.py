"""Tests for the local filesystem security boundary."""

from pathlib import Path

import pytest

from hy3_data_analyst_mcp.data.security import resolve_data_file
from hy3_data_analyst_mcp.errors import (
    DataAccessDeniedError,
    DataFileNotFoundError,
    DataLimitExceededError,
    UnsupportedDataFormatError,
)


def test_relative_and_absolute_paths_inside_root_are_allowed(fixture_dir: Path) -> None:
    relative = resolve_data_file("sales.csv", allowed_directory=fixture_dir, max_file_size_mb=20)
    absolute = resolve_data_file(
        fixture_dir / "sales.csv", allowed_directory=fixture_dir, max_file_size_mb=20
    )

    assert relative == absolute == (fixture_dir / "sales.csv").resolve()


def test_parent_traversal_is_denied(fixture_dir: Path) -> None:
    with pytest.raises(DataAccessDeniedError, match="outside HY3_DATA_DIR"):
        resolve_data_file("../outside.csv", allowed_directory=fixture_dir, max_file_size_mb=20)


def test_absolute_path_outside_root_is_denied(fixture_dir: Path) -> None:
    outside = fixture_dir.parent / "outside.csv"

    with pytest.raises(DataAccessDeniedError, match="outside HY3_DATA_DIR"):
        resolve_data_file(outside, allowed_directory=fixture_dir, max_file_size_mb=20)


def test_missing_file_is_actionable(fixture_dir: Path) -> None:
    with pytest.raises(DataFileNotFoundError, match="not found"):
        resolve_data_file("missing.csv", allowed_directory=fixture_dir, max_file_size_mb=20)


def test_unsupported_extension_is_rejected(fixture_dir: Path) -> None:
    with pytest.raises(UnsupportedDataFormatError, match="extension"):
        resolve_data_file("notes.txt", allowed_directory=fixture_dir, max_file_size_mb=20)


def test_uppercase_supported_extension_is_allowed(fixture_dir: Path) -> None:
    path = resolve_data_file("UPPER.CSV", allowed_directory=fixture_dir, max_file_size_mb=20)

    assert path.name == "UPPER.CSV"


def test_hidden_file_is_rejected(fixture_dir: Path) -> None:
    with pytest.raises(DataAccessDeniedError, match="Hidden"):
        resolve_data_file(".hidden.csv", allowed_directory=fixture_dir, max_file_size_mb=20)


def test_directory_is_not_accepted_as_a_file(fixture_dir: Path) -> None:
    with pytest.raises(DataAccessDeniedError, match="regular file"):
        resolve_data_file("directory.csv", allowed_directory=fixture_dir, max_file_size_mb=20)


def test_file_size_limit_is_enforced(fixture_dir: Path) -> None:
    large = fixture_dir / "generated_large.csv"
    large.write_bytes(b"x" * (1024 * 1024 + 1))
    try:
        with pytest.raises(DataLimitExceededError, match="size limit"):
            resolve_data_file(
                "generated_large.csv", allowed_directory=fixture_dir, max_file_size_mb=1
            )
    finally:
        large.unlink(missing_ok=True)


def test_symlink_escape_is_denied_when_supported(fixture_dir: Path) -> None:
    outside = fixture_dir.parent / "outside.csv"
    link = fixture_dir / "linked.csv"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this Windows installation")
    try:
        with pytest.raises(DataAccessDeniedError, match="outside HY3_DATA_DIR"):
            resolve_data_file(link, allowed_directory=fixture_dir, max_file_size_mb=20)
    finally:
        link.unlink(missing_ok=True)
