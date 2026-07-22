"""Tests for deterministic and JSON-safe dataset profiling."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hy3_data_analyst_mcp.data.profiler import profile_dataset


def test_numeric_statistics_match_pandas(fixture_dir: Path) -> None:
    frame = pd.DataFrame({"value": [1.0, 2.0, 4.0, np.nan]})

    profile = profile_dataset(frame, source_path=fixture_dir / "sales.csv")
    column = profile.columns[0]

    assert column.semantic_type == "numeric"
    assert column.non_null_count == 3
    assert column.missing_rate == pytest.approx(0.25)
    assert column.statistics["mean"] == pytest.approx(frame["value"].mean())
    assert column.statistics["median"] == frame["value"].median()
    assert column.statistics["std"] == pytest.approx(frame["value"].std())


def test_dates_categories_duplicates_and_top_value_limit(fixture_dir: Path) -> None:
    frame = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-02-01", "2026-02-01"],
            "category": ["a", "b", "b"],
        }
    )

    profile = profile_dataset(frame, source_path=fixture_dir / "sales.csv", top_values=1)

    assert profile.duplicate_row_count == 1
    assert profile.columns[0].semantic_type == "datetime"
    assert profile.columns[0].statistics == {
        "min": "2026-01-01T00:00:00",
        "max": "2026-02-01T00:00:00",
    }
    assert profile.columns[1].semantic_type == "categorical"
    assert profile.columns[1].statistics["top_values"] == [{"value": "b", "count": 2}]


def test_nan_infinity_timestamp_and_empty_column_are_strict_json(fixture_dir: Path) -> None:
    frame = pd.DataFrame(
        {
            "number": [1.0, np.inf, np.nan],
            "when": [pd.Timestamp("2026-01-01"), pd.NaT, pd.NaT],
            "empty": [None, None, None],
        }
    )

    profile = profile_dataset(frame, source_path=fixture_dir / "sales.csv", sample_rows=3)
    encoded = json.dumps(profile.model_dump(mode="json"), allow_nan=False)

    assert "Infinity" not in encoded
    assert profile.sample_rows[1]["number"] is None
    assert profile.sample_rows[0]["when"] == "2026-01-01T00:00:00"
    assert profile.columns[2].semantic_type == "unknown"


def test_sample_rows_are_bounded(fixture_dir: Path) -> None:
    frame = pd.DataFrame({"value": [1]})

    with pytest.raises(ValueError, match="between 0 and 20"):
        profile_dataset(frame, source_path=fixture_dir / "sales.csv", sample_rows=21)
