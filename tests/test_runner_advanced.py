"""Tests for advanced runner features: new checks, partition filter, schema, reference, multi-file."""

import polars as pl
import pytest

from eliza import check


class TestNotMissing:
    def test_detects_empty_and_na(self):
        df = pl.DataFrame({"a": ["hello", "", "N/A", None, "ok", "null"]})
        result = check(df, checks={"a": ["not_missing"]}, samples=False)
        assert result.checks[0].fail_count == 4

    def test_custom_missing_values(self):
        df = pl.DataFrame({"a": ["hello", "UNKNOWN", "-", "ok"]})
        result = check(
            df,
            checks={
                "a": [{"not_missing": {"missing_values": ["UNKNOWN", "-"]}}],
            },
            samples=False,
        )
        assert result.checks[0].fail_count == 2

    def test_clean(self):
        df = pl.DataFrame({"a": ["hello", "world"]})
        result = check(df, checks={"a": ["not_missing"]}, samples=False)
        assert result.passed()

    def test_samples(self):
        df = pl.DataFrame({"a": ["hello", "", None, "ok"]})
        result = check(df, checks={"a": ["not_missing"]}, samples=True)
        assert "a:not_missing" in result.samples
        assert len(result.samples["a:not_missing"]) == 2


class TestStringLength:
    def test_min_length_fail(self):
        df = pl.DataFrame({"a": ["ab", "a", "abc"]})
        result = check(df, checks={"a": [{"min_length": {"min": 2}}]}, samples=False)
        assert result.checks[0].fail_count == 1

    def test_min_length_pass(self):
        df = pl.DataFrame({"a": ["abc", "de", "fgh"]})
        result = check(df, checks={"a": [{"min_length": {"min": 2}}]}, samples=False)
        assert result.passed()

    def test_max_length_fail(self):
        df = pl.DataFrame({"a": ["ab", "abcdef", "abc"]})
        result = check(df, checks={"a": [{"max_length": {"max": 4}}]}, samples=False)
        assert result.checks[0].fail_count == 1

    def test_max_length_pass(self):
        df = pl.DataFrame({"a": ["ab", "abc"]})
        result = check(df, checks={"a": [{"max_length": {"max": 5}}]}, samples=False)
        assert result.passed()

    def test_min_length_samples(self):
        df = pl.DataFrame({"a": ["ab", "a", "abc"]})
        result = check(df, checks={"a": [{"min_length": {"min": 2}}]}, samples=True)
        assert "a:min_length" in result.samples


class TestPartitionFilter:
    def test_filter_reduces_rows(self):
        df = pl.DataFrame(
            {
                "value": [10, -5, 20, -3, 15],
                "cat": ["A", "A", "B", "B", "A"],
            }
        )
        lf = df.lazy().filter(pl.col("cat") == "A")
        result = check(lf, checks={"value": ["not_negative"]}, samples=False)
        assert result.total_rows == 3
        assert result.checks[0].fail_count == 1

    def test_filter_no_failures(self):
        df = pl.DataFrame(
            {
                "value": [10, -5, 20, -3, 15],
                "cat": ["A", "B", "A", "B", "A"],
            }
        )
        lf = df.lazy().filter(pl.col("cat") == "A")
        result = check(lf, checks={"value": ["not_negative"]}, samples=False)
        assert result.passed()


class TestSchema:
    def test_schema_columns_present(self):
        df = pl.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        schema = df.lazy().collect_schema()
        assert "id" in schema.names()
        assert "name" in schema.names()

    def test_schema_type_detection(self):
        df = pl.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        schema = df.lazy().collect_schema()
        assert str(schema["id"]) == "Int64"
        assert str(schema["name"]) == "String"

    def test_schema_missing_column(self):
        df = pl.DataFrame({"id": [1]})
        schema = df.lazy().collect_schema()
        expected = {"id": "Int64", "name": "String"}
        missing = [c for c in expected if c not in schema.names()]
        assert missing == ["name"]


class TestReference:
    def test_no_orphans(self, tmp_path):
        ref_df = pl.DataFrame({"id": [1, 2, 3, 4, 5]})
        ref_path = str(tmp_path / "ref.parquet")
        ref_df.write_parquet(ref_path)

        main_df = pl.DataFrame({"dept_id": [1, 2, 3]})
        from eliza.compat import resolve_source

        ref_lf = resolve_source(ref_path)
        ref_vals = ref_lf.select(pl.col("id").unique()).collect(engine="streaming").to_series()
        orphans = (
            main_df.lazy()
            .filter(pl.col("dept_id").is_not_null() & ~pl.col("dept_id").is_in(ref_vals))
            .select(pl.len())
            .collect(engine="streaming")
            .item()
        )
        assert orphans == 0

    def test_with_orphans(self, tmp_path):
        ref_df = pl.DataFrame({"id": [1, 2, 3]})
        ref_path = str(tmp_path / "ref.parquet")
        ref_df.write_parquet(ref_path)

        main_df = pl.DataFrame({"dept_id": [1, 2, 99, 100]})
        from eliza.compat import resolve_source

        ref_lf = resolve_source(ref_path)
        ref_vals = ref_lf.select(pl.col("id").unique()).collect(engine="streaming").to_series()
        orphans = (
            main_df.lazy()
            .filter(pl.col("dept_id").is_not_null() & ~pl.col("dept_id").is_in(ref_vals))
            .select(pl.len())
            .collect(engine="streaming")
            .item()
        )
        assert orphans == 2


class TestMultiFile:
    def test_list_source(self, tmp_path):
        df1 = pl.DataFrame({"a": [1, 2, None]})
        df2 = pl.DataFrame({"a": [4, None, 6]})
        p1, p2 = str(tmp_path / "f1.parquet"), str(tmp_path / "f2.parquet")
        df1.write_parquet(p1)
        df2.write_parquet(p2)

        result = check([p1, p2], checks={"a": ["not_null"]}, samples=False)
        assert result.total_rows == 6
        assert result.checks[0].fail_count == 2

    def test_empty_list(self):
        from eliza.compat import resolve_source

        with pytest.raises(ValueError, match="Empty"):
            resolve_source([])


class TestSamplesConfig:
    def test_samples_limit(self):
        df = pl.DataFrame({"a": [None] * 20 + [1] * 5})
        result = check(df, checks={"a": ["not_null"]}, samples=True, samples_limit=3)
        assert len(result.samples["a:not_null"]) == 3

    def test_samples_disabled(self):
        df = pl.DataFrame({"a": [None, 1, 2]})
        result = check(df, checks={"a": ["not_null"]}, samples=False)
        assert len(result.samples) == 0

    def test_no_samples_on_pass(self):
        df = pl.DataFrame({"a": [1, 2, 3]})
        result = check(df, checks={"a": ["not_null"]}, samples=True)
        assert len(result.samples) == 0
