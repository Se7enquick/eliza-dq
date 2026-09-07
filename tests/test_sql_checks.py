"""Tests for SQL check expressions and dialect support."""

from eliza.checks_sql import (
    _sanitize_regex,
    _sql_quote,
    get_check_expr,
    get_sample_filter,
    get_separate_query,
)


class TestSqlQuote:
    def test_none(self):
        assert _sql_quote(None) == "NULL"

    def test_bool(self):
        assert _sql_quote(True) == "1"
        assert _sql_quote(False) == "0"

    def test_int(self):
        assert _sql_quote(42) == "42"

    def test_float(self):
        assert _sql_quote(3.14) == "3.14"

    def test_string(self):
        assert _sql_quote("hello") == "'hello'"

    def test_injection(self):
        assert _sql_quote("'; DROP TABLE --") == "'''; DROP TABLE --'"


class TestSanitizeRegex:
    def test_clean(self):
        assert _sanitize_regex("^test.*$") == "^test.*$"

    def test_escapes_quotes(self):
        result = _sanitize_regex("test'; DROP TABLE --")
        assert "'" not in result or "''" in result

    def test_preserves_backslashes(self):
        assert r"\d" in _sanitize_regex(r"^\d{3}$")
        assert r"\." in _sanitize_regex(r"^[a-z]+\.[a-z]+$")


class TestInlineChecks:
    def test_not_null(self):
        expr = get_check_expr("not_null", "col", {}, "bigquery")
        assert "IS NULL" in expr

    def test_not_negative(self):
        expr = get_check_expr("not_negative", "col", {}, "bigquery")
        assert "< 0" in expr

    def test_between(self):
        expr = get_check_expr("between", "col", {"min": 0, "max": 100}, "bigquery")
        assert "< 0" in expr
        assert "> 100" in expr

    def test_in_set(self):
        expr = get_check_expr("in_set", "col", {"values": ["a", "b"]}, "bigquery")
        assert "NOT IN" in expr
        assert "'a'" in expr

    def test_not_missing(self):
        expr = get_check_expr("not_missing", "col", {}, "bigquery")
        assert "IS NULL" in expr
        assert "N/A" in expr

    def test_min_length(self):
        expr = get_check_expr("min_length", "col", {"min": 3}, "bigquery")
        assert "LENGTH" in expr
        assert "3" in expr

    def test_max_length(self):
        expr = get_check_expr("max_length", "col", {"max": 100}, "bigquery")
        assert "LENGTH" in expr
        assert "100" in expr

    def test_custom_sql(self):
        expr = get_check_expr(
            "custom_sql", None, {"expression": "SUM(CASE WHEN x > 100 THEN 1 ELSE 0 END)"}, "bigquery"
        )
        assert "x > 100" in expr

    def test_unknown_check(self):
        assert get_check_expr("nonexistent", "col", {}, "bigquery") is None


class TestRegexDialects:
    def test_bigquery(self):
        expr = get_check_expr("regex", "col", {"pattern": "test"}, "bigquery")
        assert "REGEXP_CONTAINS" in expr

    def test_athena(self):
        expr = get_check_expr("regex", "col", {"pattern": "test"}, "athena")
        assert "REGEXP_LIKE" in expr

    def test_postgres(self):
        expr = get_check_expr("regex", "col", {"pattern": "test"}, "postgres")
        assert "~" in expr

    def test_clickhouse(self):
        expr = get_check_expr("regex", "col", {"pattern": "test"}, "clickhouse")
        assert "match(" in expr

    def test_mysql(self):
        expr = get_check_expr("regex", "col", {"pattern": "test"}, "mysql")
        assert "REGEXP" in expr

    def test_snowflake(self):
        expr = get_check_expr("regex", "col", {"pattern": "test"}, "snowflake")
        assert "REGEXP_LIKE" in expr

    def test_databricks(self):
        expr = get_check_expr("regex", "col", {"pattern": "test"}, "databricks")
        assert "REGEXP_LIKE" in expr


class TestFreshnessDialects:
    def test_bigquery(self):
        sql = get_separate_query("freshness", "ts", {}, "t", "bigquery")
        assert "TIMESTAMP_DIFF" in sql

    def test_athena(self):
        sql = get_separate_query("freshness", "ts", {}, "t", "athena")
        assert "date_diff" in sql

    def test_postgres(self):
        sql = get_separate_query("freshness", "ts", {}, "t", "postgres")
        assert "EXTRACT(EPOCH" in sql

    def test_snowflake(self):
        sql = get_separate_query("freshness", "ts", {}, "t", "snowflake")
        assert "TIMESTAMPDIFF" in sql

    def test_clickhouse(self):
        sql = get_separate_query("freshness", "ts", {}, "t", "clickhouse")
        assert "dateDiff" in sql

    def test_mysql(self):
        sql = get_separate_query("freshness", "ts", {}, "t", "mysql")
        assert "TIMESTAMPDIFF" in sql

    def test_redshift(self):
        sql = get_separate_query("freshness", "ts", {}, "t", "redshift")
        assert "DATEDIFF" in sql


class TestSeparateChecks:
    def test_unique(self):
        sql = get_separate_query("unique", "col", {}, "t", "bigquery")
        assert "GROUP BY" in sql
        assert "HAVING COUNT(*) > 1" in sql

    def test_row_count(self):
        sql = get_separate_query("row_count", None, {}, "t", "bigquery")
        assert "COUNT(*)" in sql

    def test_reference(self):
        sql = get_separate_query(
            "reference",
            "dept_id",
            {
                "reference_table": "departments",
                "reference_column": "id",
            },
            "orders",
            "bigquery",
        )
        assert "LEFT JOIN departments" in sql
        assert "orphan_count" in sql

    def test_unknown(self):
        assert get_separate_query("nonexistent", "c", {}, "t", "bigquery") is None


class TestSampleFilters:
    def test_not_null(self):
        assert "IS NULL" in get_sample_filter("not_null", "c", {}, "bigquery")

    def test_not_negative(self):
        assert "< 0" in get_sample_filter("not_negative", "c", {}, "bigquery")

    def test_in_set(self):
        filt = get_sample_filter("in_set", "c", {"values": [1, 2]}, "bigquery")
        assert "NOT IN" in filt

    def test_not_missing(self):
        filt = get_sample_filter("not_missing", "c", {}, "bigquery")
        assert "IS NULL" in filt

    def test_min_length(self):
        filt = get_sample_filter("min_length", "c", {"min": 5}, "bigquery")
        assert "LENGTH" in filt

    def test_regex_dialect(self):
        filt_bq = get_sample_filter("regex", "c", {"pattern": "x"}, "bigquery")
        filt_pg = get_sample_filter("regex", "c", {"pattern": "x"}, "postgres")
        assert "REGEXP_CONTAINS" in filt_bq
        assert "~" in filt_pg

    def test_unknown(self):
        assert get_sample_filter("nonexistent", "c", {}, "bigquery") is None


class TestSqlRunnerErrorHandling:
    def test_failed_aggregation_query_gives_error_status(self):
        """A failed SQL query must produce status='error', not status='pass'."""
        from eliza.sql_runner import check_sql

        def failing_executor(sql):
            raise RuntimeError("syntax error: REGEXP_CONTAINS not supported")

        result = check_sql(
            failing_executor,
            checks_list=[
                {"column": "code", "check": "regex", "pattern": r"^\d{3}$"},
                {"column": "email", "check": "is_email"},
            ],
            table="test_table",
            dialect="postgres",
        )
        assert not result.passed()
        assert result.exit_code == 2
        for c in result.checks:
            assert c.status == "error"
            assert c.fail_count == 0
            assert c.error is not None
