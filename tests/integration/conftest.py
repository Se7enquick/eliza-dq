"""Shared test data and helpers for integration tests.

10 rows with deterministic failures for every check type.
Expected fail counts are exact — CI catches regressions by asserting them.
"""

INLINE_CHECKS = [
    ("not_null", "name", {}, 3),
    ("not_negative", "amount", {}, 2),
    ("between", "score", {"min": 0, "max": 100}, 1),
    ("in_set", "status", {"values": ["active", "pending"]}, 2),
    ("regex", "code", {"pattern": r"^[A-Z]{3}\d{2}$"}, 5),
    ("is_email", "email", {}, 3),
    ("min_length", "code", {"min": 5}, 4),
    ("max_length", "name", {"max": 4}, 2),
    ("not_missing", "name", {}, 4),
    ("custom_sql", None, {"expression": "COUNT(CASE WHEN amount > 200 THEN 1 END)"}, 1),
]

TOTAL_ROWS = 10


def make_check_config(check_name, column, params):
    cfg = {"check": check_name, **params}
    if column:
        cfg["column"] = column
    return cfg


def find_check(result, name, column=None):
    for c in result.checks:
        if c.name == name and c.column == column:
            return c
    return None
