"""Tests for source resolution."""

import polars as pl
import pytest

from eliza.compat import resolve_source


def test_polars_dataframe():
    df = pl.DataFrame({"a": [1, 2]})
    lf = resolve_source(df)
    assert isinstance(lf, pl.LazyFrame)
    assert lf.collect()["a"].to_list() == [1, 2]


def test_polars_lazyframe():
    lf_in = pl.DataFrame({"a": [1]}).lazy()
    lf = resolve_source(lf_in)
    assert isinstance(lf, pl.LazyFrame)


def test_pandas_dataframe():
    pd = pytest.importorskip("pandas")
    pdf = pd.DataFrame({"a": [3, 4]})
    lf = resolve_source(pdf)
    assert isinstance(lf, pl.LazyFrame)
    assert lf.collect()["a"].to_list() == [3, 4]


def test_parquet(tmp_path):
    path = tmp_path / "test.parquet"
    pl.DataFrame({"a": [5]}).write_parquet(path)
    lf = resolve_source(str(path))
    assert lf.collect()["a"].to_list() == [5]


def test_csv(tmp_path):
    path = tmp_path / "test.csv"
    pl.DataFrame({"a": [6]}).write_csv(path)
    lf = resolve_source(str(path))
    assert lf.collect()["a"].to_list() == [6]


def test_ndjson(tmp_path):
    path = tmp_path / "test.ndjson"
    pl.DataFrame({"a": [7]}).write_ndjson(path)
    lf = resolve_source(str(path))
    assert lf.collect()["a"].to_list() == [7]


def test_path_object(tmp_path):
    path = tmp_path / "test.parquet"
    pl.DataFrame({"a": [8]}).write_parquet(path)
    lf = resolve_source(path)  # Path object, not str
    assert lf.collect()["a"].to_list() == [8]


def test_unsupported_type():
    with pytest.raises(TypeError):
        resolve_source(42)


def test_unknown_format():
    with pytest.raises(ValueError):
        resolve_source("/tmp/test.xyz")
