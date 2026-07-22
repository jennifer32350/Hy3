"""Tests for deterministic CSV, JSON, and JSONL loading."""

from pathlib import Path

import pytest

from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.data.loader import load_dataset
from hy3_data_analyst_mcp.errors import (
    DataLimitExceededError,
    DataParseError,
    UnsupportedDataFormatError,
)


@pytest.mark.parametrize(
    ("file_name", "expected_rows"),
    [("sales.csv", 2), ("customers.json", 2), ("events.jsonl", 2)],
)
def test_supported_formats_load(
    settings: Settings,
    file_name: str,
    expected_rows: int,
) -> None:
    frame = load_dataset(file_name, settings=settings)

    assert len(frame) == expected_rows


def test_utf8_bom_csv_loads(settings: Settings) -> None:
    frame = load_dataset("bom.csv", settings=settings, encoding="utf-8-sig")

    assert frame.columns.tolist() == ["name", "amount"]


def test_explicit_gb18030_loads(fixture_dir: Path) -> None:
    csv = fixture_dir / "generated_gb.csv"
    csv.write_bytes("名称,数值\n测试,3\n".encode("gb18030"))
    settings = Settings(data_dir=fixture_dir)
    try:
        frame = load_dataset("generated_gb.csv", settings=settings, encoding="gb18030")

        assert frame.iloc[0]["名称"] == "测试"
    finally:
        csv.unlink(missing_ok=True)


def test_unsupported_encoding_is_rejected(settings: Settings) -> None:
    with pytest.raises(UnsupportedDataFormatError, match="encoding"):
        load_dataset("sales.csv", settings=settings, encoding="latin-1")


def test_wrong_encoding_has_actionable_error(fixture_dir: Path) -> None:
    csv = fixture_dir / "generated_gb.csv"
    csv.write_bytes("名称,数值\n测试,3\n".encode("gb18030"))
    settings = Settings(data_dir=fixture_dir)
    try:
        with pytest.raises(DataParseError, match="not valid utf-8"):
            load_dataset("generated_gb.csv", settings=settings)
    finally:
        csv.unlink(missing_ok=True)


def test_empty_csv_has_actionable_error(settings: Settings) -> None:
    with pytest.raises(DataParseError, match="empty"):
        load_dataset("empty.csv", settings=settings)


def test_header_only_csv_has_actionable_error(settings: Settings) -> None:
    with pytest.raises(DataParseError, match="no data rows"):
        load_dataset("header_only.csv", settings=settings)


def test_malformed_json_has_line_and_column(settings: Settings) -> None:
    with pytest.raises(DataParseError, match=r"line .* column"):
        load_dataset("malformed.json", settings=settings)


def test_nested_json_is_rejected(settings: Settings) -> None:
    with pytest.raises(DataParseError, match="nested"):
        load_dataset("nested.json", settings=settings)


def test_non_array_json_is_rejected(settings: Settings) -> None:
    with pytest.raises(DataParseError, match="array of objects"):
        load_dataset("object.json", settings=settings)


def test_row_limit_is_enforced(fixture_dir: Path) -> None:
    settings = Settings(data_dir=fixture_dir, max_rows=1)

    with pytest.raises(DataLimitExceededError, match="row limit"):
        load_dataset("sales.csv", settings=settings)


def test_column_limit_is_enforced(fixture_dir: Path) -> None:
    settings = Settings(data_dir=fixture_dir, max_columns=1)

    with pytest.raises(DataLimitExceededError, match="column limit"):
        load_dataset("sales.csv", settings=settings)
