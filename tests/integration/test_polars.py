"""Integration tests for the Polars engine path.

Tests check() with DataFrame, parquet, CSV — no external services needed.
Same 10 rows, same expected fail counts as SQL tests.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from eliza import check

pytestmark = pytest.mark.polars

NOW = datetime.now()

TEST_DF = pl.DataFrame(
    {
        "name": ["Alice", "Bob", None, None, "Eve", None, "", "Heidi", "Ivan", "Jane"],
        "email": [
            "alice@test.com",
            "bob@test.com",
            "invalid-email",
            "dave@test.com",
            "",
            "frank@test.com",
            "grace@test.com",
            "heidi@test.com",
            "bad-email",
            "jane@test.com",
        ],
        "amount": [100.50, 50.0, -10.0, 200.0, 0.50, -5.25, 75.0, 300.0, 25.0, 150.0],
        "status": ["active", "active", "closed", "active", "pending", "active", "active", "active", "closed", "active"],
        "code": ["ABC12", "DEF34", "AB1", "CDEF5", "EF2", "GHI78", "JK3", "LMN90", "OP4", "QRS12"],
        "score": [80, 90, 30, 110, 50, 70, 85, 95, 40, 65],
        "updated_at": [NOW - timedelta(hours=1)] * 10,
    }
)


def test_not_null():
    result = check(TEST_DF, checks={"name": ["not_null"]})
    c = result.checks[0]
    assert c.fail_count == 3


def test_not_negative():
    result = check(TEST_DF, checks={"amount": ["not_negative"]})
    c = result.checks[0]
    assert c.fail_count == 2


def test_between():
    result = check(TEST_DF, checks={"score": [{"between": {"min": 0, "max": 100}}]})
    c = result.checks[0]
    assert c.fail_count == 1


def test_in_set():
    result = check(TEST_DF, checks={"status": [{"in_set": {"values": ["active", "pending"]}}]})
    c = result.checks[0]
    assert c.fail_count == 2


def test_regex():
    result = check(TEST_DF, checks={"code": [{"regex": {"pattern": r"^[A-Z]{3}\d{2}$"}}]})
    c = result.checks[0]
    assert c.fail_count == 5


def test_is_email():
    result = check(TEST_DF, checks={"email": ["is_email"]})
    c = result.checks[0]
    assert c.fail_count == 3


def test_min_length():
    result = check(TEST_DF, checks={"code": [{"min_length": {"min": 5}}]})
    c = result.checks[0]
    assert c.fail_count == 4


def test_max_length():
    result = check(TEST_DF, checks={"name": [{"max_length": {"max": 4}}]})
    c = result.checks[0]
    assert c.fail_count == 2


def test_not_missing():
    result = check(TEST_DF, checks={"name": ["not_missing"]})
    c = result.checks[0]
    assert c.fail_count == 4


def test_unique():
    result = check(TEST_DF, checks={"status": ["unique"]})
    c = result.checks[0]
    assert c.fail_count > 0


def test_row_count():
    result = check(
        TEST_DF,
        checks={
            "name": ["not_null"],
            "__table__": [{"row_count": {"min": 5, "max": 20}}],
        },
    )
    c = next(c for c in result.checks if c.name == "row_count")
    assert c.status == "pass"
    assert result.total_rows == 10


def test_freshness():
    result = check(
        TEST_DF,
        checks={"updated_at": [{"freshness": {"max_age": "48h"}}]},
    )
    c = next(c for c in result.checks if c.name == "freshness")
    assert c.status == "pass"


def test_cross_column():
    result = check(
        TEST_DF,
        checks={"__table__": [{"cross_column": {"column_a": "score", "column_b": "amount"}}]},
    )
    c = next(c for c in result.checks if c.name == "cross_column")
    assert c.fail_count == 6


def test_all_checks_combined():
    result = check(
        TEST_DF,
        checks={
            "name": ["not_null", "not_missing", {"max_length": {"max": 4}}],
            "email": ["is_email"],
            "amount": ["not_negative"],
            "status": [{"in_set": {"values": ["active", "pending"]}}],
            "code": [{"regex": {"pattern": r"^[A-Z]{3}\d{2}$"}}, {"min_length": {"min": 5}}],
            "score": [{"between": {"min": 0, "max": 100}}],
        },
    )
    failed = [c for c in result.checks if c.status == "fail"]
    passed = [c for c in result.checks if c.status == "pass"]
    assert len(failed) == 9
    assert len(passed) == 0 or all(c.fail_count == 0 for c in passed)


def test_from_parquet():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.parquet"
        TEST_DF.write_parquet(path)
        result = check(str(path), checks={"name": ["not_null"], "amount": ["not_negative"]})
        assert result.total_rows == 10
        not_null = next(c for c in result.checks if c.name == "not_null")
        assert not_null.fail_count == 3


def test_from_csv():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.csv"
        TEST_DF.drop("updated_at").write_csv(path)
        result = check(str(path), checks={"name": ["not_null"], "amount": ["not_negative"]})
        assert result.total_rows == 10


def test_from_pandas():
    pytest.importorskip("pandas")
    pdf = TEST_DF.to_pandas()
    result = check(pdf, checks={"name": ["not_null"], "amount": ["not_negative"]})
    assert result.total_rows == 10
    not_null = next(c for c in result.checks if c.name == "not_null")
    assert not_null.fail_count == 3


def test_samples_collected():
    result = check(TEST_DF, checks={"name": ["not_null"]}, samples_limit=5)
    key = "name:not_null"
    assert key in result.samples
    sample_df = result.samples[key]
    assert len(sample_df) <= 5


def test_result_api():
    result = check(TEST_DF, checks={"name": ["not_null"]})
    assert not result.passed()
    assert result.exit_code != 0
    d = result.to_dict()
    assert "checks" in d
    assert "total_rows" in d
    s = result.summary()
    assert "fail" in s.lower() or "10" in s
