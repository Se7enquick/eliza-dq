"""SQL check expressions for warehouse pushdown.

Supported dialects: bigquery, athena, snowflake, postgres, clickhouse,
                    mysql, databricks, redshift.
"""


def _sql_quote(value):
    """Quote a value for SQL, preventing injection."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace("'", "''")
    return f"'{s}'"


def _sanitize_regex(pattern):
    """Escape characters that could break out of a SQL string literal.
    Preserves backslashes (needed for \\d, \\w, etc.) — only escapes quotes."""
    return pattern.replace("'", "''").replace('"', '\\"')


# -- Dialect-specific helpers -----------------------------------------------

_REGEX_FN = {
    "bigquery": lambda col, pat: f'NOT REGEXP_CONTAINS(SAFE_CAST({col} AS STRING), r"{pat}")',
    "athena": lambda col, pat: f"NOT REGEXP_LIKE(CAST({col} AS VARCHAR), '{pat}')",
    "snowflake": lambda col, pat: f"NOT REGEXP_LIKE(CAST({col} AS VARCHAR), '{pat}')",
    "postgres": lambda col, pat: f"NOT (CAST({col} AS TEXT) ~ '{pat}')",
    "redshift": lambda col, pat: f"NOT (CAST({col} AS VARCHAR) ~ '{pat}')",
    "clickhouse": lambda col, pat: f"NOT match(CAST({col} AS String), '{pat}')",
    "mysql": lambda col, pat: f"NOT (CAST({col} AS CHAR) REGEXP '{pat}')",
    "databricks": lambda col, pat: f"NOT REGEXP_LIKE(CAST({col} AS STRING), '{pat}')",
}

_FRESHNESS_SQL = {
    "bigquery": lambda col, table: (
        f"SELECT MAX({col}) AS max_val, TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX({col}), HOUR) AS age_hours FROM {table}"
    ),
    "athena": lambda col, table: (
        f"SELECT MAX({col}) AS max_val, date_diff('hour', MAX({col}), current_timestamp) AS age_hours FROM {table}"
    ),
    "snowflake": lambda col, table: (
        f"SELECT MAX({col}) AS max_val, TIMESTAMPDIFF(HOUR, MAX({col}), CURRENT_TIMESTAMP()) AS age_hours FROM {table}"
    ),
    "postgres": lambda col, table: (
        f"SELECT MAX({col}) AS max_val, EXTRACT(EPOCH FROM (NOW() - MAX({col}))) / 3600 AS age_hours FROM {table}"
    ),
    "redshift": lambda col, table: (
        f"SELECT MAX({col}) AS max_val, DATEDIFF(HOUR, MAX({col}), GETDATE()) AS age_hours FROM {table}"
    ),
    "clickhouse": lambda col, table: (
        f"SELECT MAX({col}) AS max_val, dateDiff('hour', MAX({col}), now()) AS age_hours FROM {table}"
    ),
    "mysql": lambda col, table: (
        f"SELECT MAX({col}) AS max_val, TIMESTAMPDIFF(HOUR, MAX({col}), NOW()) AS age_hours FROM {table}"
    ),
    "databricks": lambda col, table: (
        f"SELECT MAX({col}) AS max_val, TIMESTAMPDIFF(HOUR, MAX({col}), CURRENT_TIMESTAMP()) AS age_hours FROM {table}"
    ),
}

_EMAIL_PAT = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
_URL_PAT = r"^https?://[^\s]+$"


# -- Check definitions ------------------------------------------------------


def get_check_expr(check_name, col, v, dialect="bigquery"):
    """Get a SQL expression for an inline aggregation check."""
    fn = _INLINE_CHECKS.get(check_name)
    if fn is None:
        return None
    return fn(col, v, dialect)


def get_separate_query(check_name, col, v, table, dialect="bigquery"):
    """Get a standalone SQL query for checks that need their own query."""
    fn = _SEPARATE_CHECKS.get(check_name)
    if fn is None:
        return None
    return fn(col, v, table, dialect)


def _regex_not_match(col, pattern, dialect):
    pat = _sanitize_regex(pattern)
    fn = _REGEX_FN.get(dialect, _REGEX_FN["bigquery"])
    return fn(col, pat)


# Inline checks — return a SUM(CASE...) expression for the aggregation query
_INLINE_CHECKS = {
    "not_null": lambda col, v, d: f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END)",
    "not_negative": lambda col, v, d: f"SUM(CASE WHEN {col} < 0 THEN 1 ELSE 0 END)",
    "between": lambda col, v, d: (
        f"SUM(CASE WHEN {col} < {v.get('min', 'NULL')} OR {col} > {v.get('max', 'NULL')} THEN 1 ELSE 0 END)"
        if "min" in v and "max" in v
        else f"SUM(CASE WHEN {col} < {v['min']} THEN 1 ELSE 0 END)"
        if "min" in v
        else f"SUM(CASE WHEN {col} > {v['max']} THEN 1 ELSE 0 END)"
    ),
    "in_set": lambda col, v, d: (
        f"SUM(CASE WHEN {col} NOT IN ({','.join(_sql_quote(x) for x in v.get('values', []))}) THEN 1 ELSE 0 END)"
    ),
    "regex": lambda col, v, d: f"SUM(CASE WHEN {_regex_not_match(col, v.get('pattern', ''), d)} THEN 1 ELSE 0 END)",
    "is_email": lambda col, v, d: f"SUM(CASE WHEN {_regex_not_match(col, _EMAIL_PAT, d)} THEN 1 ELSE 0 END)",
    "is_url": lambda col, v, d: f"SUM(CASE WHEN {_regex_not_match(col, _URL_PAT, d)} THEN 1 ELSE 0 END)",
    "cross_column": lambda col, v, d: f"SUM(CASE WHEN {v['column_a']} > {v['column_b']} THEN 1 ELSE 0 END)",
    "not_missing": lambda col, v, d: (
        f"SUM(CASE WHEN {col} IS NULL OR CAST({col} AS VARCHAR) IN "
        f"({','.join(_sql_quote(x) for x in v.get('missing_values', ['', 'NULL', 'null', 'None', 'N/A', 'n/a', 'NA', 'NaN']))}) "
        f"THEN 1 ELSE 0 END)"
    ),
    "min_length": lambda col, v, d: (
        f"SUM(CASE WHEN LENGTH(CAST({col} AS VARCHAR)) < {v.get('min', 0)} THEN 1 ELSE 0 END)"
    ),
    "max_length": lambda col, v, d: (
        f"SUM(CASE WHEN LENGTH(CAST({col} AS VARCHAR)) > {v.get('max', 255)} THEN 1 ELSE 0 END)"
    ),
    "custom_sql": lambda col, v, d: v.get("expression", "0"),
}

# Separate checks — return a full SQL query
_SEPARATE_CHECKS = {
    "unique": lambda col, v, table, d: (
        f"WITH freq AS (SELECT {col}, COUNT(*) c FROM {table} "
        f"WHERE {col} IS NOT NULL GROUP BY {col} HAVING c > 1) "
        f"SELECT COUNT(*) AS dup_count FROM freq"
    ),
    "freshness": lambda col, v, table, d: _FRESHNESS_SQL.get(d, _FRESHNESS_SQL["bigquery"])(col, table),
    "row_count": lambda col, v, table, d: f"SELECT COUNT(*) AS row_count FROM {table}",
    "reference": lambda col, v, table, d: (
        f"SELECT COUNT(*) AS orphan_count FROM {table} a "
        f"LEFT JOIN {v['reference_table']} b ON a.{col} = b.{v.get('reference_column', col)} "
        f"WHERE b.{v.get('reference_column', col)} IS NULL AND a.{col} IS NOT NULL"
    ),
}


def get_sample_filter(check_name, col, v, dialect="bigquery"):
    """Get a WHERE clause for sampling failed rows."""
    fn = _SAMPLE_FILTERS.get(check_name)
    if fn is None:
        return None
    return fn(col, v, dialect)


_SAMPLE_FILTERS = {
    "not_null": lambda col, v, d: f"{col} IS NULL",
    "not_negative": lambda col, v, d: f"{col} < 0",
    "between": lambda col, v, d: (
        f"({col} < {v.get('min', 'NULL')} OR {col} > {v.get('max', 'NULL')})"
        if "min" in v and "max" in v
        else f"{col} < {v['min']}"
        if "min" in v
        else f"{col} > {v['max']}"
    ),
    "in_set": lambda col, v, d: f"{col} NOT IN ({','.join(_sql_quote(x) for x in v.get('values', []))})",
    "regex": lambda col, v, d: _regex_not_match(col, v.get("pattern", ""), d),
    "is_email": lambda col, v, d: _regex_not_match(col, _EMAIL_PAT, d),
    "is_url": lambda col, v, d: _regex_not_match(col, _URL_PAT, d),
    "cross_column": lambda col, v, d: f"{v['column_a']} > {v['column_b']}",
    "not_missing": lambda col, v, d: (
        f"({col} IS NULL OR CAST({col} AS VARCHAR) IN "
        f"({','.join(_sql_quote(x) for x in v.get('missing_values', ['', 'NULL', 'null', 'None', 'N/A', 'n/a', 'NA', 'NaN']))}))"
    ),
    "min_length": lambda col, v, d: f"LENGTH(CAST({col} AS VARCHAR)) < {v.get('min', 0)}",
    "max_length": lambda col, v, d: f"LENGTH(CAST({col} AS VARCHAR)) > {v.get('max', 255)}",
}
