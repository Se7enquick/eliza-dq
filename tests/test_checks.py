"""Tests for check expressions."""

import polars as pl

from eliza.checks_polars import CHECKS


def _run(df, check_name, col, v=None):
    """Helper: run one check, return fail count."""
    v = v or {}
    check = CHECKS[check_name]
    if "count_expr" in check:
        return df.select(check["count_expr"](col, v).alias("v")).item()
    return df.select(check["base_expr"](col, v).sum().alias("v")).item()


def test_not_null():
    df = pl.DataFrame({"a": [1, None, 3, None, 5]})
    assert _run(df, "not_null", "a") == 2


def test_not_null_clean():
    df = pl.DataFrame({"a": [1, 2, 3]})
    assert _run(df, "not_null", "a") == 0


def test_unique_no_dupes():
    df = pl.DataFrame({"a": [1, 2, 3, 4, 5]})
    assert _run(df, "unique", "a") == 0


def test_unique_with_dupes():
    df = pl.DataFrame({"a": [1, 2, 3, 2, 1]})
    assert _run(df, "unique", "a") == 2  # count - n_unique = 5 - 3 = 2


def test_not_negative():
    df = pl.DataFrame({"a": [1.0, -2.0, 3.0, -4.0, 0.0]})
    assert _run(df, "not_negative", "a") == 2


def test_not_negative_clean():
    df = pl.DataFrame({"a": [0.0, 1.0, 100.0]})
    assert _run(df, "not_negative", "a") == 0


def test_between():
    df = pl.DataFrame({"a": [1, 5, 10, 15, 20]})
    assert _run(df, "between", "a", {"min": 5, "max": 15}) == 2  # 1 and 20


def test_between_min_only():
    df = pl.DataFrame({"a": [-1, 0, 1, 5]})
    assert _run(df, "between", "a", {"min": 0}) == 1  # -1


def test_between_max_only():
    df = pl.DataFrame({"a": [1, 5, 100, 200]})
    assert _run(df, "between", "a", {"max": 100}) == 1  # 200


def test_in_set():
    df = pl.DataFrame({"a": ["ok", "bad", "ok", "nope"]})
    assert _run(df, "in_set", "a", {"values": ["ok"]}) == 2


def test_in_set_clean():
    df = pl.DataFrame({"a": ["a", "b", "c"]})
    assert _run(df, "in_set", "a", {"values": ["a", "b", "c"]}) == 0


def test_regex():
    df = pl.DataFrame({"a": ["abc", "123", "a1b"]})
    assert _run(df, "regex", "a", {"pattern": r"^[a-z]+$"}) == 2


def test_is_email():
    df = pl.DataFrame({"a": ["user@test.com", "bad", "ok@x.io", "nope"]})
    assert _run(df, "is_email", "a") == 2


def test_is_url():
    df = pl.DataFrame({"a": ["https://x.com", "not-url", "http://a.b"]})
    assert _run(df, "is_url", "a") == 1


def test_cross_column():
    df = pl.DataFrame({"a": [10, 5, 3], "b": [5, 10, 1]})
    # Failing = where a > b
    check = CHECKS["cross_column"]
    count = df.select(check["base_expr"](None, {"column_a": "a", "column_b": "b"}).sum().alias("v")).item()
    assert count == 2  # rows 0 and 2
