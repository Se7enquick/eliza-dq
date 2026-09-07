"""
Eliza Mini MVP — proof of concept з 3 чеками.
Показує як check_masks dict + LazyFrame + YAML працюють разом.
Все оптимізовано: один scan, один collect, мінімум пам'яті.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
import yaml


CHECKS: dict[str, Any] = {
    "not_null": lambda col, _v: pl.col(col).is_null().sum(),
    "unique": lambda col, _v: pl.col(col).count() - pl.col(col).n_unique(),
    "gt": lambda col, v: (pl.col(col) <= v["value"]).sum(),
    "ge": lambda col, v: (pl.col(col) < v["value"]).sum(),
    "lt": lambda col, v: (pl.col(col) >= v["value"]).sum(),
    "le": lambda col, v: (pl.col(col) > v["value"]).sum(),
    "between": lambda col, v: (
        (pl.col(col) < v["min"]) | (pl.col(col) > v["max"])
    ).sum(),
    "in_set": lambda col, v: (~pl.col(col).is_in(v["values"])).sum(),
    "regex": lambda col, v: (~pl.col(col).cast(pl.String).str.contains(v["pattern"])).sum(),
    "is_email": lambda col, _v: (
        ~pl.col(col).cast(pl.String).str.contains(
            r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$"
        )
    ).sum(),
    "is_url": lambda col, _v: (
        ~pl.col(col).cast(pl.String).str.contains(
            r"^https?://[^\s<>\"{}|\\^\[\]`]+$"
        )
    ).sum(),
    "is_uuid": lambda col, _v: (
        ~pl.col(col).cast(pl.String).str.contains(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        )
    ).sum(),
    "positive": lambda col, _v: (pl.col(col) <= 0).sum(),
    "row_count_min": lambda _col, v: pl.lit(0),  # handled separately
}


@dataclass
class CheckResult:
    name: str
    column: str | None
    status: str  # "pass" | "warn" | "fail"
    fail_count: int
    total_rows: int
    severity: str

    @property
    def passed(self) -> bool:
        return self.status == "pass"


@dataclass
class ElizaResult:
    checks: list[CheckResult] = field(default_factory=list)
    total_rows: int = 0
    elapsed_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return not any(c.status == "fail" for c in self.checks)

    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.status == "pass")
        warned = sum(1 for c in self.checks if c.status == "warn")
        failed = sum(1 for c in self.checks if c.status == "fail")
        return (
            f"{passed} passed, {warned} warnings, {failed} failed "
            f"({self.total_rows} rows, {self.elapsed_ms:.1f}ms)"
        )

    def raise_on_fail(self) -> None:
        if not self.passed:
            failures = [c for c in self.checks if c.status == "fail"]
            msg = "; ".join(f"{c.column}:{c.name}({c.fail_count} rows)" for c in failures)
            raise RuntimeError(f"Eliza check failed: {msg}")

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "total_rows": self.total_rows,
            "elapsed_ms": self.elapsed_ms,
            "checks": [
                {
                    "name": c.name,
                    "column": c.column,
                    "status": c.status,
                    "fail_count": c.fail_count,
                    "severity": c.severity,
                }
                for c in self.checks
            ],
        }

    def __repr__(self) -> str:
        return self.summary()


def _resolve_source(source: str | Path | pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
    if isinstance(source, pl.LazyFrame):
        return source
    if isinstance(source, pl.DataFrame):
        return source.lazy()
    if isinstance(source, (str, Path)):
        p = str(source)
        if p.endswith(".parquet"):
            return pl.scan_parquet(p)
        if p.endswith(".csv"):
            return pl.scan_csv(p)
        if p.endswith(".ndjson") or p.endswith(".jsonl"):
            return pl.scan_ndjson(p)
        raise ValueError(f"Unsupported file format: {p}")
    try:
        import pandas as pd
        if isinstance(source, pd.DataFrame):
            return pl.from_pandas(source).lazy()
    except ImportError:
        pass
    raise TypeError(f"Cannot resolve source: {type(source).__name__}")


def _load_yaml(config: str, config_path: str | Path | None = None) -> dict:
    if config_path is None:
        config_path = Path.cwd() / "eliza_checks"
    else:
        config_path = Path(config_path)
    yaml_file = config_path / f"{config}.yaml"
    if not yaml_file.exists():
        raise FileNotFoundError(f"Check config not found: {yaml_file}")
    with open(yaml_file) as f:
        return yaml.safe_load(f)


def check(
    source: str | Path | pl.DataFrame | pl.LazyFrame | None = None,
    *,
    config: str,
    config_path: str | Path | None = None,
) -> ElizaResult:
    t0 = time.perf_counter()

    cfg = _load_yaml(config, config_path)

    if source is None:
        src = cfg.get("source")
        if src is None:
            raise ValueError("No source provided and no 'source' in YAML config")
        lf = _resolve_source(src)
    else:
        lf = _resolve_source(source)

    # збираємо ВСІ check expressions в один список — один collect на все
    exprs: list[pl.Expr] = [pl.len().alias("__total_rows__")]
    check_meta: list[dict] = []

    for rule in cfg.get("checks", []):
        col = rule.get("column")
        check_name = rule["check"]
        severity = rule.get("on_failure", cfg.get("defaults", {}).get("on_failure", "fail"))

        if check_name not in CHECKS:
            raise ValueError(f"Unknown check: {check_name}")

        expr = CHECKS[check_name](col, rule)
        alias = f"__check_{len(check_meta)}__"
        exprs.append(expr.alias(alias))
        check_meta.append({
            "name": check_name,
            "column": col,
            "severity": severity,
            "alias": alias,
        })

    # ОДИН collect — всі чеки за один прохід по даних
    result_row = lf.select(exprs).collect().row(0, named=True)

    total_rows = result_row["__total_rows__"]
    elapsed_ms = (time.perf_counter() - t0) * 1000

    checks = []
    for meta in check_meta:
        fail_count = int(result_row[meta["alias"]])
        status = "pass" if fail_count == 0 else meta["severity"]
        checks.append(CheckResult(
            name=meta["name"],
            column=meta["column"],
            status=status,
            fail_count=fail_count,
            total_rows=total_rows,
            severity=meta["severity"],
        ))

    return ElizaResult(checks=checks, total_rows=total_rows, elapsed_ms=elapsed_ms)
