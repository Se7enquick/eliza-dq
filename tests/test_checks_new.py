"""Tests for new check expressions: not_missing, min_length, max_length."""

import polars as pl

from eliza.checks_polars import CHECKS


def _run(df, check_name, col, v=None):
    v = v or {}
    check = CHECKS[check_name]
    if "count_expr" in check:
        return df.select(check["count_expr"](col, v).alias("v")).item()
    return df.select(check["base_expr"](col, v).sum().alias("v")).item()


def test_not_missing_defaults():
    df = pl.DataFrame({"a": ["hello", "", "N/A", None, "ok", "null"]})
    assert _run(df, "not_missing", "a") == 4


def test_not_missing_custom():
    df = pl.DataFrame({"a": ["hello", "UNKNOWN", "-", "ok"]})
    assert _run(df, "not_missing", "a", {"missing_values": ["UNKNOWN", "-"]}) == 2


def test_not_missing_clean():
    df = pl.DataFrame({"a": ["hello", "world"]})
    assert _run(df, "not_missing", "a") == 0


def test_min_length():
    df = pl.DataFrame({"a": ["ab", "a", "abc", "abcd"]})
    assert _run(df, "min_length", "a", {"min": 2}) == 1


def test_min_length_all_pass():
    df = pl.DataFrame({"a": ["abc", "de", "fgh"]})
    assert _run(df, "min_length", "a", {"min": 2}) == 0


def test_max_length():
    df = pl.DataFrame({"a": ["ab", "abcdef", "abc"]})
    assert _run(df, "max_length", "a", {"max": 4}) == 1


def test_max_length_all_pass():
    df = pl.DataFrame({"a": ["ab", "abc", "a"]})
    assert _run(df, "max_length", "a", {"max": 5}) == 0
