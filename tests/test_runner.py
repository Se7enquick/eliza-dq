"""Tests for the check runner — full integration."""

import polars as pl
import pytest

from eliza import check


@pytest.fixture
def sample_df():
    return pl.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "amount": [10.0, -5.0, 20.0, 0.0, 100.0],
            "status": ["ok", "ok", "bad", "ok", "ok"],
            "email": ["a@b.com", "bad", "c@d.io", "e@f.org", "nope"],
        }
    )


def test_inline_checks_pass(sample_df):
    result = check(sample_df, checks={"id": ["not_null"]}, samples=False)
    assert result.passed()
    assert result.checks[0].fail_count == 0


def test_inline_checks_fail(sample_df):
    result = check(sample_df, checks={"amount": ["not_negative"]}, samples=False)
    assert not result.passed()
    assert result.checks[0].fail_count == 1  # -5.0


def test_multiple_checks_same_column(sample_df):
    result = check(
        sample_df,
        checks={
            "amount": ["not_null", "not_negative"],
        },
        samples=False,
    )
    assert len(result.checks) == 2
    assert result.checks[0].fail_count == 0  # not_null
    assert result.checks[1].fail_count == 1  # not_negative


def test_in_set(sample_df):
    result = check(
        sample_df,
        checks={
            "status": [{"in_set": ["ok"]}],
        },
        samples=False,
    )
    assert result.checks[0].fail_count == 1  # "bad"


def test_regex(sample_df):
    result = check(
        sample_df,
        checks={
            "email": [{"regex": r"^.+@.+\..+$"}],
        },
        samples=False,
    )
    assert result.checks[0].fail_count == 2  # "bad" and "nope"


def test_is_email(sample_df):
    result = check(
        sample_df,
        checks={
            "email": ["is_email"],
        },
        samples=False,
    )
    assert result.checks[0].fail_count == 2


def test_between(sample_df):
    result = check(
        sample_df,
        checks={
            "amount": [{"between": {"min": 0, "max": 50}}],
        },
        samples=False,
    )
    assert result.checks[0].fail_count == 2  # -5.0 and 100.0 > 50


def test_unique(sample_df):
    result = check(sample_df, checks={"id": ["unique"]}, samples=False)
    assert result.checks[0].fail_count == 0


def test_unique_with_dupes():
    df = pl.DataFrame({"id": [1, 2, 3, 2, 1]})
    result = check(df, checks={"id": ["unique"]}, samples=False)
    assert result.checks[0].fail_count > 0


def test_samples_collected(sample_df):
    result = check(sample_df, checks={"amount": ["not_negative"]}, samples=True)
    assert len(result.samples) > 0


def test_samples_not_collected_on_pass(sample_df):
    result = check(sample_df, checks={"id": ["not_null"]}, samples=True)
    assert len(result.samples) == 0


def test_result_summary(sample_df):
    result = check(
        sample_df,
        checks={
            "id": ["not_null"],
            "amount": ["not_negative"],
        },
        samples=False,
    )
    summary = result.summary()
    assert "passed" in summary
    assert "failed" in summary


def test_result_to_json(sample_df):
    result = check(sample_df, checks={"id": ["not_null"]}, samples=False)
    j = result.to_json()
    assert '"passed": true' in j


def test_result_exit_code(sample_df):
    result = check(sample_df, checks={"id": ["not_null"]}, samples=False)
    assert result.exit_code == 0

    result2 = check(sample_df, checks={"amount": ["not_negative"]}, samples=False)
    assert result2.exit_code == 1


def test_raise_on_fail(sample_df):
    result = check(sample_df, checks={"amount": ["not_negative"]}, samples=False)
    with pytest.raises(RuntimeError):
        result.raise_on_fail()


def test_unknown_check(sample_df):
    result = check(sample_df, checks={"id": ["nonexistent_check"]}, samples=False)
    assert result.checks[0].status == "error"


def test_parquet_source(tmp_path):
    df = pl.DataFrame({"a": [1, 2, None]})
    path = tmp_path / "test.parquet"
    df.write_parquet(path)
    result = check(str(path), checks={"a": ["not_null"]}, samples=False)
    assert result.checks[0].fail_count == 1


def test_column_grouping():
    """Checks on same column should be grouped in one collect."""
    df = pl.DataFrame({"a": [1.0, -2.0, 3.0, -4.0]})
    result = check(
        df,
        checks={
            "a": ["not_null", "not_negative", {"between": {"min": 0, "max": 10}}],
        },
        samples=False,
    )
    assert len(result.checks) == 3
    assert result.checks[0].fail_count == 0  # not_null
    assert result.checks[1].fail_count == 2  # not_negative
    assert result.checks[2].fail_count == 2  # between
