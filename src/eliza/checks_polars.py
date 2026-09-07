"""Check expressions for Polars data quality validation."""

import polars as pl

CHECKS = {
    "not_null": {"engine": "streaming", "samplable": True, "base_expr": lambda col, v: pl.col(col).is_null()},
    "unique": {
        "engine": "default",
        "samplable": False,
        "base_expr": lambda col, v: pl.col(col).is_duplicated(),
        "count_expr": lambda col, v: pl.col(col).count() - pl.col(col).n_unique(),
    },
    "not_negative": {
        "engine": "streaming",
        "samplable": True,
        "base_expr": lambda col, v: pl.col(col) < 0,
    },
    "between": {
        "engine": "streaming",
        "samplable": True,
        "base_expr": lambda col, v: (
            ~pl.col(col).is_between(
                lower_bound=v.get("min", float("-inf")),
                upper_bound=v.get("max", float("inf")),
            )
        ),
    },
    "in_set": {
        "engine": "streaming",
        "samplable": True,
        "base_expr": lambda col, v: ~pl.col(col).is_in(v.get("values", [])),
    },
    "regex": {
        "engine": "streaming",
        "samplable": True,
        "base_expr": lambda col, v: ~pl.col(col).cast(pl.String).str.contains(v.get("pattern", ".*")),
    },
    "is_email": {
        "engine": "streaming",
        "samplable": True,
        "base_expr": lambda col, v: (
            ~pl.col(col).cast(pl.String).str.contains(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        ),
    },
    "is_url": {
        "engine": "streaming",
        "samplable": True,
        "base_expr": lambda col, v: ~pl.col(col).cast(pl.String).str.contains(r'^https?://[^\s<>"{}|\\^\[\]`]+$'),
    },
    "freshness": {
        "engine": "streaming",
        "samplable": False,
        "base_expr": None,  # in-runner
    },
    "row_count": {
        "engine": "streaming",
        "samplable": False,
        "base_expr": None,  # in-runner
    },
    "cross_column": {
        "engine": "streaming",
        "samplable": True,
        "base_expr": lambda col, v: pl.col(v["column_a"]) > pl.col(v["column_b"]),
    },
    "not_missing": {
        "engine": "streaming",
        "samplable": True,
        "base_expr": lambda col, v: (
            pl.col(col).is_null()
            | pl.col(col)
            .cast(pl.String)
            .is_in(v.get("missing_values", ["", "NULL", "null", "None", "N/A", "n/a", "NA", "NaN"]))
        ),
    },
    "min_length": {
        "engine": "streaming",
        "samplable": True,
        "base_expr": lambda col, v: pl.col(col).cast(pl.String).str.len_chars() < v.get("min", 0),
    },
    "max_length": {
        "engine": "streaming",
        "samplable": True,
        "base_expr": lambda col, v: pl.col(col).cast(pl.String).str.len_chars() > v.get("max", 255),
    },
    "schema": {
        "engine": "streaming",
        "samplable": False,
        "base_expr": None,
    },
    "reference": {
        "engine": "streaming",
        "samplable": False,
        "base_expr": None,
    },
    "custom_sql": {
        "engine": "streaming",
        "samplable": False,
        "base_expr": None,
    },
}
