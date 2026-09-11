"""SQL pushdown runner — executes checks on warehouse via parallel queries."""

import concurrent.futures
import time

from .checks_sql import get_check_expr, get_sample_filter, get_separate_query
from .loader import load_config, parse_inline_checks
from .result import CheckResult, ElizaResult


def check_sql(
    source=None,
    *,
    config=None,
    checks=None,
    checks_list=None,
    executor=None,
    table=None,
    dialect="bigquery",
    samples=True,
    sample_id=None,
    sample_columns=None,
    samples_limit=10,
    partition_filter=None,
):
    """Run DQ checks via SQL pushdown on a warehouse.

    Args:
        source: callable(sql) -> list[dict], or use executor=
        executor: alias for source
        table: fully qualified table name
        dialect: bigquery|athena|snowflake|postgres|clickhouse|mysql|databricks|redshift
    """
    t_start = time.perf_counter()
    run = executor or source

    if checks_list is not None:
        cfg = {}
    elif config is not None and isinstance(config, str):
        cfg = load_config(config)
        checks_list = cfg.get("checks", [])
        if table is None:
            table = cfg.get("table") or cfg.get("source")
    elif checks is not None:
        cfg = {}
        checks_list = parse_inline_checks(checks)
    else:
        raise ValueError("Provide config='name' or checks={...}")

    if table is None:
        raise ValueError("table= is required for SQL pushdown")

    if partition_filter is None and cfg:
        partition_filter = cfg.get("filter")

    where_clause = f" WHERE {partition_filter}" if partition_filter else ""

    agg_exprs = []
    agg_meta = []
    separate_queries = []

    for c in checks_list:
        check_name = c["check"]
        col = c.get("column")
        alias = f"{col}_{check_name}" if col else check_name
        severity = c.get("on_failure", "fail")

        sep_sql = get_separate_query(check_name, col, c, table, dialect)
        if sep_sql is not None:
            separate_queries.append(
                {
                    "name": check_name,
                    "column": col,
                    "alias": alias,
                    "severity": severity,
                    "config": c,
                    "sql": sep_sql,
                }
            )
            continue

        expr = get_check_expr(check_name, col, c, dialect)
        if expr is None:
            agg_meta.append(
                {
                    "name": check_name,
                    "column": col,
                    "error": f"Unknown SQL check: {check_name}",
                }
            )
            continue

        agg_exprs.append(f"{expr} AS {alias}")
        agg_meta.append(
            {
                "name": check_name,
                "column": col,
                "alias": alias,
                "severity": severity,
                "config": c,
            }
        )

    all_queries = {}
    if agg_exprs:
        all_queries["aggregation"] = f"SELECT COUNT(*) AS total_rows, {', '.join(agg_exprs)} FROM {table}{where_clause}"
    for sq in separate_queries:
        all_queries[sq["alias"]] = sq["sql"]

    query_results = _run_parallel(run, all_queries)

    results = []
    total_rows = 0

    if "aggregation" in query_results:
        agg_row = query_results["aggregation"]
        if isinstance(agg_row, dict) and "error" in agg_row:
            for m in agg_meta:
                results.append(
                    CheckResult(
                        name=m.get("name", m.get("check_name", "unknown")),
                        column=m.get("column"),
                        status="error",
                        fail_count=0,
                        total_rows=0,
                        error=agg_row["error"],
                    )
                )
        else:
            if isinstance(agg_row, list):
                agg_row = agg_row[0] if agg_row else {}
            if not isinstance(agg_row, dict):
                agg_row = {}
            total_rows = int(agg_row.get("total_rows", 0))
            for m in agg_meta:
                if "error" in m:
                    results.append(
                        CheckResult(
                            name=m["name"],
                            column=m.get("column"),
                            status="error",
                            fail_count=0,
                            total_rows=total_rows,
                            error=m["error"],
                        )
                    )
                    continue
                count = int(agg_row.get(m["alias"], 0))
                status = "pass" if count == 0 else m["severity"]
                results.append(
                    CheckResult(
                        name=m["name"],
                        column=m["column"],
                        status=status,
                        fail_count=count,
                        total_rows=total_rows,
                    )
                )

    for sq in separate_queries:
        r = query_results.get(sq["alias"], {})
        if isinstance(r, dict) and "error" in r:
            results.append(
                CheckResult(
                    name=sq["name"],
                    column=sq["column"],
                    status="error",
                    fail_count=0,
                    total_rows=total_rows,
                    error=r["error"],
                )
            )
            continue
        if isinstance(r, list) and r:
            r = r[0]

        if sq["name"] == "unique":
            count = int(r.get("dup_count", 0)) if isinstance(r, dict) else 0
            results.append(
                CheckResult(
                    name="unique",
                    column=sq["column"],
                    status="pass" if count == 0 else sq["severity"],
                    fail_count=count,
                    total_rows=total_rows,
                )
            )
        elif sq["name"] == "freshness":
            age_hours = float(r.get("age_hours", 0)) if isinstance(r, dict) else 0
            max_age = sq["config"].get("max_age", "24h")
            from .runner import _parse_duration_hours

            threshold = _parse_duration_hours(max_age)
            failed = age_hours > threshold
            results.append(
                CheckResult(
                    name="freshness",
                    column=sq["column"],
                    status=sq["severity"] if failed else "pass",
                    fail_count=1 if failed else 0,
                    total_rows=total_rows,
                )
            )
        elif sq["name"] == "row_count":
            count = int(r.get("row_count", 0)) if isinstance(r, dict) else 0
            if total_rows == 0:
                total_rows = count
            min_rows = sq["config"].get("min", 0)
            max_rows = sq["config"].get("max", float("inf"))
            failed = count < min_rows or count > max_rows
            results.append(
                CheckResult(
                    name="row_count",
                    column=None,
                    status=sq["severity"] if failed else "pass",
                    fail_count=1 if failed else 0,
                    total_rows=count,
                )
            )
        elif sq["name"] == "reference":
            count = int(r.get("orphan_count", 0)) if isinstance(r, dict) else 0
            results.append(
                CheckResult(
                    name="reference",
                    column=sq["column"],
                    status="pass" if count == 0 else sq["severity"],
                    fail_count=count,
                    total_rows=total_rows,
                )
            )

    all_samples = {}
    if samples:
        _sample_id = sample_id or (cfg.get("sample_id") if cfg else None)
        _sample_cols = sample_columns or (cfg.get("sample_columns") if cfg else None)
        sample_queries = {}
        for r in results:
            if r.fail_count > 0:
                cfg_match = next(
                    (c for c in checks_list if c.get("column") == r.column and c["check"] == r.name),
                    {},
                )
                filt = get_sample_filter(r.name, r.column, cfg_match, dialect)
                if filt:
                    if _sample_cols:
                        cols = list(_sample_cols)
                        if r.column and r.column not in cols:
                            cols.append(r.column)
                        sample_col_sql = ", ".join(cols)
                    elif _sample_id:
                        cols = [_sample_id]
                        if r.column and r.column != _sample_id:
                            cols.append(r.column)
                        sample_col_sql = ", ".join(cols)
                    else:
                        all_checked = list(dict.fromkeys(c.get("column") for c in checks_list if c.get("column")))
                        sample_col_sql = ", ".join(all_checked) if all_checked else "*"
                    sample_queries[f"{r.column}:{r.name}"] = (
                        f"SELECT {sample_col_sql} FROM {table} WHERE {filt} LIMIT {samples_limit}"
                    )
        if sample_queries:
            sample_results = _run_parallel(run, sample_queries)
            for name, rows in sample_results.items():
                if isinstance(rows, list):
                    all_samples[name] = rows

    elapsed_ms = (time.perf_counter() - t_start) * 1000

    return ElizaResult(
        checks=results,
        total_rows=total_rows,
        elapsed_ms=elapsed_ms,
        samples=all_samples,
    )


def _run_parallel(executor, queries):
    """Execute queries in parallel, return {name: result} dict."""
    if not queries:
        return {}
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(queries), 8)) as pool:
        futures = {pool.submit(executor, sql): name for name, sql in queries.items()}
        for f in concurrent.futures.as_completed(futures):
            name = futures[f]
            try:
                results[name] = f.result()
            except Exception as e:
                results[name] = {"error": str(e)}
    return results
