"""Core runner — executes checks and returns ElizaResult."""

import time
from collections import defaultdict

import polars as pl

from .checks_polars import CHECKS
from .compat import resolve_source
from .loader import load_config, parse_inline_checks
from .result import CheckResult, ElizaResult


def check(
    source=None,
    *,
    config=None,
    checks=None,
    query=None,
    engine=None,
    executor=None,
    table=None,
    dialect=None,
    samples=True,
    samples_limit=10,
    **scan_kwargs,
):
    """Run data quality checks on any source.

    Usage:
        # Polars native (auto)
        result = check(df, config="orders")
        result = check("data.parquet", config="orders")
        result = check(df, checks={"amount": ["not_null", "not_negative"]})

        # ConnectorX (auto — detects DB URI)
        result = check("mysql://user:pass@host/db", query="SELECT * FROM orders", config="orders")

        # SQL pushdown (explicit)
        result = check(config="orders", engine="sql", executor=my_query_fn, table="schema.table")
    """
    t_start = time.perf_counter()

    if config is not None and isinstance(config, str):
        cfg = load_config(config)
        checks_list = cfg.get("checks", [])
        if source is None:
            source = cfg.get("source")
        if engine is None:
            engine = cfg.get("engine")
        if table is None:
            table = cfg.get("table")
        if dialect is None:
            dialect = cfg.get("dialect", "bigquery")
        samples_cfg = cfg.get("samples", {})
        if isinstance(samples_cfg, dict):
            if "enabled" in samples_cfg and samples is True:
                samples = samples_cfg["enabled"]
            if "limit" in samples_cfg and samples_limit == 10:
                samples_limit = samples_cfg["limit"]
        elif isinstance(samples_cfg, bool) and samples is True:
            samples = samples_cfg
    elif checks is not None:
        cfg = {}
        checks_list = parse_inline_checks(checks)
    else:
        raise ValueError("Provide config='name' or checks={...}")

    connector = None
    if cfg and cfg.get("connection") and executor is None:
        from .connectors import create_connector

        connector = create_connector(cfg["connection"])
        executor = connector.execute
        if dialect is None:
            dialect = connector.dialect
        if engine is None:
            engine = "sql"

    dialect = dialect or "bigquery"

    if engine == "sql":
        from .sql_runner import check_sql

        try:
            return check_sql(
                executor,
                checks_list=checks_list,
                table=table,
                dialect=dialect,
                samples=samples,
                samples_limit=samples_limit,
                partition_filter=cfg.get("filter") if cfg else None,
            )
        finally:
            if connector:
                connector.close()

    if source is None:
        raise ValueError("No source provided and no 'source' in YAML config")

    if query is None:
        query = cfg.get("query") if cfg else None

    lf = resolve_source(source, query=query, **scan_kwargs)

    partition_filter = cfg.get("filter") if cfg else None
    if partition_filter:
        lf = lf.filter(pl.sql_expr(partition_filter))

    results = []
    all_samples = {}
    special_checks = []

    column_groups = defaultdict(list)
    for c in checks_list:
        check_name = c["check"]
        if check_name in ("freshness", "row_count", "cross_column", "schema", "reference"):
            special_checks.append(c)
        else:
            column_groups[c.get("column")].append(c)

    total_rows = 0
    first_group = True

    for col, col_checks in column_groups.items():
        exprs = []
        meta = []

        if first_group:
            exprs.append(pl.len().alias("__total__"))

        for c in col_checks:
            check_name = c["check"]
            check_def = CHECKS.get(check_name)

            if check_def is None:
                results.append(
                    CheckResult(
                        name=check_name,
                        column=col,
                        status="error",
                        fail_count=0,
                        total_rows=total_rows,
                        error=f"Unknown check: {check_name}",
                    )
                )
                continue

            alias = f"{col}:{check_name}"
            if "count_expr" in check_def:
                exprs.append(check_def["count_expr"](col, c).alias(alias))
            elif check_def["base_expr"] is not None:
                exprs.append(check_def["base_expr"](col, c).sum().alias(alias))
            else:
                continue

            meta.append(
                {
                    "alias": alias,
                    "check_name": check_name,
                    "column": col,
                    "severity": c.get("on_failure", "fail"),
                    "config": c,
                }
            )

        if not exprs:
            continue

        try:
            row = lf.select(exprs).collect(engine="streaming").row(0, named=True)
        except Exception as e:
            for m in meta:
                results.append(
                    CheckResult(
                        name=m["check_name"],
                        column=m["column"],
                        status="error",
                        fail_count=0,
                        total_rows=total_rows,
                        error=str(e),
                    )
                )
            continue

        if first_group:
            total_rows = row.get("__total__", 0)
            first_group = False

        for m in meta:
            count = int(row[m["alias"]])
            status = "pass" if count == 0 else m["severity"]
            results.append(
                CheckResult(
                    name=m["check_name"], column=m["column"], status=status, fail_count=count, total_rows=total_rows
                )
            )

            if samples and count > 0:
                check_def = CHECKS.get(m["check_name"], {})
                if check_def.get("base_expr") is not None:
                    try:
                        sample_df = (
                            lf.filter(check_def["base_expr"](m["column"], m["config"]))
                            .head(samples_limit)
                            .collect(engine="streaming")
                        )
                        all_samples[m["alias"]] = sample_df
                    except Exception:
                        pass

    for c in special_checks:
        check_name = c["check"]
        severity = c.get("on_failure", "fail")

        if check_name == "row_count":
            min_rows = c.get("min", 0)
            max_rows = c.get("max", float("inf"))
            failed = total_rows < min_rows or total_rows > max_rows
            results.append(
                CheckResult(
                    name="row_count",
                    column=None,
                    status="fail" if failed else "pass",
                    fail_count=1 if failed else 0,
                    total_rows=total_rows,
                )
            )

        elif check_name == "freshness":
            col = c.get("column")
            max_age = c.get("max_age", "24h")
            try:
                max_val = lf.select(pl.col(col).max()).collect(engine="streaming").item()
                from datetime import datetime, timedelta

                age = datetime.now() - max_val
                hours = _parse_duration_hours(max_age)
                failed = age > timedelta(hours=hours)
                results.append(
                    CheckResult(
                        name="freshness",
                        column=col,
                        status=severity if failed else "pass",
                        fail_count=1 if failed else 0,
                        total_rows=total_rows,
                    )
                )
            except Exception as e:
                results.append(
                    CheckResult(
                        name="freshness",
                        column=col,
                        status="error",
                        fail_count=0,
                        total_rows=total_rows,
                        error=str(e),
                    )
                )

        elif check_name == "cross_column":
            col_a = c["column_a"]
            col_b = c["column_b"]
            alias = f"{col_a}>{col_b}"
            try:
                base = CHECKS["cross_column"]["base_expr"]
                count = lf.select(base(None, c).sum().alias("v")).collect(engine="streaming").item()
                results.append(
                    CheckResult(
                        name="cross_column",
                        column=f"{col_a}>{col_b}",
                        status="pass" if count == 0 else severity,
                        fail_count=count,
                        total_rows=total_rows,
                    )
                )
                if samples and count > 0:
                    sample_df = lf.filter(base(None, c)).head(samples_limit).collect(engine="streaming")
                    all_samples[alias] = sample_df
            except Exception as e:
                results.append(
                    CheckResult(
                        name="cross_column",
                        column=f"{col_a}>{col_b}",
                        status="error",
                        fail_count=0,
                        total_rows=total_rows,
                        error=str(e),
                    )
                )

        elif check_name == "schema":
            expected = c.get("columns", {})
            try:
                schema = lf.collect_schema()
                missing = [col for col in expected if col not in schema.names()]
                extra = [col for col in schema.names() if expected and col not in expected]
                type_mismatches = []
                for col_name, expected_type in expected.items():
                    if col_name in schema and str(schema[col_name]).lower() != str(expected_type).lower():
                        type_mismatches.append(col_name)
                fail_count = len(missing) + len(type_mismatches)
                if c.get("strict", False):
                    fail_count += len(extra)
                error_detail = ""
                if missing:
                    error_detail += f"missing: {missing}. "
                if type_mismatches:
                    error_detail += f"type mismatch: {type_mismatches}. "
                if c.get("strict") and extra:
                    error_detail += f"unexpected: {extra}. "
                results.append(
                    CheckResult(
                        name="schema",
                        column=None,
                        status="pass" if fail_count == 0 else severity,
                        fail_count=fail_count,
                        total_rows=total_rows,
                        error=error_detail.strip() if error_detail else None,
                    )
                )
            except Exception as e:
                results.append(
                    CheckResult(
                        name="schema",
                        column=None,
                        status="error",
                        fail_count=0,
                        total_rows=total_rows,
                        error=str(e),
                    )
                )

        elif check_name == "reference":
            col = c.get("column")
            ref_source = c.get("reference_source")
            ref_column = c.get("reference_column", col)
            try:
                ref_lf = resolve_source(ref_source, **scan_kwargs)
                ref_values = ref_lf.select(pl.col(ref_column).unique()).collect(engine="streaming").to_series()
                orphan_count = (
                    lf.filter(pl.col(col).is_not_null() & ~pl.col(col).is_in(ref_values))
                    .select(pl.len())
                    .collect(engine="streaming")
                    .item()
                )
                results.append(
                    CheckResult(
                        name="reference",
                        column=col,
                        status="pass" if orphan_count == 0 else severity,
                        fail_count=orphan_count,
                        total_rows=total_rows,
                    )
                )
                if samples and orphan_count > 0:
                    sample_df = (
                        lf.filter(pl.col(col).is_not_null() & ~pl.col(col).is_in(ref_values))
                        .head(samples_limit)
                        .collect(engine="streaming")
                    )
                    all_samples[f"{col}:reference"] = sample_df
            except Exception as e:
                results.append(
                    CheckResult(
                        name="reference",
                        column=col,
                        status="error",
                        fail_count=0,
                        total_rows=total_rows,
                        error=str(e),
                    )
                )

    elapsed_ms = (time.perf_counter() - t_start) * 1000

    return ElizaResult(
        checks=results,
        total_rows=total_rows,
        elapsed_ms=elapsed_ms,
        samples=all_samples,
    )


def _parse_duration_hours(s):
    """Parse '24h', '1d', '30m' → hours as float."""
    s = s.strip().lower()
    if s.endswith("h"):
        return float(s[:-1])
    if s.endswith("d"):
        return float(s[:-1]) * 24
    if s.endswith("m"):
        return float(s[:-1]) / 60
    return float(s)
