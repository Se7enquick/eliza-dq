"""Compatibility layer for resolving any input to Polars LazyFrame."""

from pathlib import Path

import polars as pl

_SCANNERS = {
    ".parquet": pl.scan_parquet,
    ".pq": pl.scan_parquet,
    ".csv": pl.scan_csv,
    ".tsv": lambda p, **kw: pl.scan_csv(p, separator="\t", **kw),
    ".ndjson": pl.scan_ndjson,
    ".jsonl": pl.scan_ndjson,
    ".ipc": pl.scan_ipc,
    ".arrow": pl.scan_ipc,
}

_DB_SCHEMES = (
    "postgresql://",
    "postgres://",
    "mysql://",
    "mariadb://",
    "sqlite://",
    "mssql://",
    "sqlserver://",
    "oracle://",
    "clickhouse://",
    "redshift://",
)


def resolve_source(source, *, format=None, query=None, **scan_kwargs) -> pl.LazyFrame:
    """Resolve any source to a Polars LazyFrame.

    Supports:
        - pl.DataFrame / pl.LazyFrame
        - pandas.DataFrame / pyarrow.Table
        - File paths (.parquet, .csv, .ndjson, .ipc, etc.)
        - Database URIs (postgresql://, mysql://, sqlite://, etc. via ConnectorX)
    """
    if isinstance(source, pl.LazyFrame):
        return source
    if isinstance(source, pl.DataFrame):
        return source.lazy()

    if isinstance(source, (list, tuple)):
        if not source:
            raise ValueError("Empty file list")
        paths = [str(p) for p in source]
        return _scan_files(paths[0], paths, format, **scan_kwargs)

    if isinstance(source, (str, Path)):
        path = str(source)
        if any(path.startswith(scheme) for scheme in _DB_SCHEMES):
            return _read_database(path, query, **scan_kwargs)
        return _scan_files(path, path, format, **scan_kwargs)

    if type(source).__module__.startswith("pandas"):
        return pl.from_pandas(source).lazy()
    if type(source).__module__.startswith("pyarrow"):
        return pl.from_arrow(source).lazy()

    raise TypeError(
        f"Unsupported source: {type(source).__name__}. Expected "
        f"LazyFrame, DataFrame, path, pandas.DataFrame, pyarrow.Table, "
        f"or database URI (postgresql://, mysql://, etc.)."
    )


def _scan_files(ref_path, source, format=None, **scan_kwargs):
    suffix = format or Path(ref_path.split("*")[0]).suffix.lower()
    scanner = _SCANNERS.get(suffix)
    if scanner is None:
        raise ValueError(
            f"Cannot infer format for {ref_path!r} (suffix {suffix!r}). "
            f"Supported: {', '.join(sorted(_SCANNERS))}. "
            f"Pass format='.parquet' to override."
        )
    return scanner(source, **scan_kwargs)


def _read_database(uri, query=None, **kwargs):
    if query is None:
        raise ValueError(
            "Database source requires query= parameter. "
            "Example: resolve_source('postgresql://...', query='SELECT * FROM orders')"
        )
    return pl.read_database_uri(query, uri, **kwargs).lazy()
