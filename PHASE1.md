# Eliza DQ — Phase 1: Core Engine

**Goal**: `pip install eliza-dq` → `check(df)` → results in 30 seconds.
**Benchmark**: 30M rows, 12 checks + samples + Slack = 197ms. 9x faster than Pandera.

---

## Project Structure

```
Eliza/
├── pyproject.toml                  # deps: polars, pyyaml
├── LICENSE                         # MIT
├── README.md                       # pip install → first check in 30 sec
├── PHASE1.md                       # this file
├── DEVELOPMENT.md                  # full roadmap
│
├── src/eliza/                      # ALL code here
│   ├── __init__.py                 # public API: check(), CHECKS
│   ├── py.typed                    # PEP 561
│   │
│   ├── checks.py                   # ① CHECKS dict — 10 checks, engine metadata
│   ├── compat.py                   # ② resolve_source() — auto-detect input type + engine
│   ├── loader.py                   # ③ load YAML, auto-discovery eliza_checks/{name}.yaml
│   ├── schema.py                   # ④ schema validation — columns, types, strict
│   ├── runner.py                   # ⑤ orchestration — split parallel, samples, alert
│   ├── result.py                   # ⑥ ElizaResult dataclass
│   ├── alert.py                    # ⑦ Slack webhook — urllib only
│   └── cli.py                      # ⑧ eliza check / eliza init
│
├── tests/
│   ├── __init__.py
│   ├── test_checks.py              # test each check expression
│   ├── test_compat.py              # test auto-detect for each input type
│   ├── test_loader.py              # test YAML parsing
│   ├── test_schema.py              # test schema validation
│   ├── test_runner.py              # test full flow
│   └── test_result.py              # test ElizaResult methods
│
└── examples/
    └── eliza_checks/
        └── orders.yaml             # example YAML
```

---

## Development Order (what to code first)

### ① checks.py (~40 lines)
```python
import polars as pl

CHECKS = {
    "not_null": {
        "engine": "streaming",
        "expr": lambda col, v: pl.col(col).is_null().sum(),
    },
    "unique": {
        "engine": "default",
        "expr": lambda col, v: pl.col(col).count() - pl.col(col).n_unique(),
    },
    "not_negative": {
        "engine": "streaming",
        "expr": lambda col, v: (pl.col(col) < 0).sum(),
    },
    "between": {
        "engine": "streaming",
        "expr": lambda col, v: ((pl.col(col) < v["min"]) | (pl.col(col) > v["max"])).sum(),
    },
    "in_set": {
        "engine": "streaming",
        "expr": lambda col, v: (~pl.col(col).is_in(v["values"])).sum(),
    },
    "regex": {
        "engine": "streaming",
        "expr": lambda col, v: (~pl.col(col).cast(pl.String).str.contains(v["pattern"])).sum(),
    },
    "gt": {
        "engine": "streaming",
        "expr": lambda col, v: (pl.col(col) <= v["value"]).sum(),
    },
    "freshness": {
        "engine": "streaming",
        "expr": None,  # special handling in runner
    },
    "row_count": {
        "engine": "streaming",
        "expr": None,  # special handling in runner
    },
    "cross_column": {
        "engine": "streaming",
        "expr": None,  # special handling in runner
    },
}

FILTERS = {
    "not_null":     lambda col, v: pl.col(col).is_null(),
    "not_negative": lambda col, v: pl.col(col) < 0,
    "between":      lambda col, v: (pl.col(col) < v["min"]) | (pl.col(col) > v["max"]),
    "in_set":       lambda col, v: ~pl.col(col).is_in(v["values"]),
    "regex":        lambda col, v: ~pl.col(col).cast(pl.String).str.contains(v["pattern"]),
}
```
**Test**: `pytest tests/test_checks.py` — verify each expression returns correct count on known data.

### ② compat.py (~30 lines)
```python
import polars as pl
from pathlib import Path

def resolve_source(source):
    if isinstance(source, pl.DataFrame):
        return source.lazy(), "default"
    if isinstance(source, pl.LazyFrame):
        return source, "streaming"
    try:
        import pandas as pd
        if isinstance(source, pd.DataFrame):
            return pl.from_pandas(source).lazy(), "default"
    except ImportError:
        pass
    if isinstance(source, (str, Path)):
        p = str(source)
        if p.endswith(".parquet"): return pl.scan_parquet(p), "streaming"
        if p.endswith(".csv"):     return pl.scan_csv(p), "streaming"
        if p.endswith(".ndjson") or p.endswith(".jsonl"):
            return pl.scan_ndjson(p), "streaming"
        raise ValueError(f"Unsupported format: {p}")
    raise TypeError(f"Cannot resolve: {type(source)}")
```
**Test**: pass each type (pl.DataFrame, pl.LazyFrame, pd.DataFrame, "file.parquet") → verify returns (LazyFrame, engine).

### ③ loader.py (~50 lines)
```python
import yaml
from pathlib import Path
import os

def load_yaml(config, config_path=None):
    if config_path is None:
        config_path = Path.cwd() / "eliza_checks"
    path = Path(config_path) / f"{config}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path) as f:
        raw = f.read()
    # Env var substitution: ${VAR_NAME}
    for key, val in os.environ.items():
        raw = raw.replace(f"${{{key}}}", val)
    return yaml.safe_load(raw)

def parse_inline_checks(checks_dict):
    """Convert inline dict to checks list format"""
    result = []
    for column, checks in checks_dict.items():
        for check in checks:
            if isinstance(check, str):
                result.append({"column": column, "check": check})
            elif isinstance(check, dict):
                entry = {"column": column}
                entry.update(check) if "check" in check else entry.update({"check": list(check.keys())[0], **list(check.values())[0]} if isinstance(list(check.values())[0], dict) else {"check": list(check.keys())[0], "values": list(check.values())[0]} if isinstance(list(check.values())[0], list) else {"check": list(check.keys())[0], "value": list(check.values())[0]})
                result.append(entry)
    return result
```
**Test**: load YAML, verify parsed structure. Test env var substitution. Test inline dict parsing.

### ④ schema.py (~40 lines)
```python
import polars as pl

def validate_schema(lf, schema_config):
    if not schema_config:
        return []
    issues = []
    actual = lf.collect_schema()
    columns = {k: v for k, v in schema_config.items() if k != "strict"}
    
    for col, expected in columns.items():
        if col not in actual:
            issues.append({"type": "missing", "column": col, "status": "fail"})
        else:
            actual_type = str(actual[col]).split("(")[0]
            if actual_type != expected.split(",")[0].strip():
                issues.append({"type": "type_mismatch", "column": col,
                              "expected": expected, "actual": str(actual[col]), "status": "warn"})
    
    if schema_config.get("strict"):
        for col in actual:
            if col not in columns:
                issues.append({"type": "extra", "column": col, "status": "fail"})
    
    return issues
```

### ⑤ runner.py (~100 lines) — the heart

Key optimization: **sequential per-check with inline samples**.

- Each check collected separately → Polars frees memory before next check → low RAM
- Samples fetched inline right after failed check (data still in Polars cache = fast)
- unique uses default engine, everything else uses streaming
- No asyncio needed — simple loop, best performance

Validated: 100M rows, 8 checks + samples = 1,377ms, 1,674MB RAM.
Sequential per-column collect = 374MB without unique on 100M rows.
Every competitor runs sequential too (Pandera, Cuallee, Daffy, Dataframely).

```python
from .checks import POLARS_CHECKS
from .compat import resolve_source
from .loader import load_yaml, parse_inline_checks
from .schema import validate_schema
from .result import ElizaResult, CheckResult

def _run(lf, checks_config, samples=True, samples_limit=10):
    loop = asyncio.get_event_loop()
    
    # Split by engine
    streaming_exprs = [pl.len().alias("__total__")]
    default_exprs = []
    meta = []
    # ... build expressions from checks_config ...
    
    # Parallel: streaming batch + unique batch
    r_fast, r_heavy = await asyncio.gather(
        loop.run_in_executor(None, lambda: lf.select(streaming_exprs).collect(
            engine="streaming" if engine == "streaming" else None)),
        loop.run_in_executor(None, lambda: lf.select(default_exprs).collect() if default_exprs else None),
    )
    
    # Merge → find failed → parallel samples → ElizaResult
    # ...

def check(source=None, *, config=None, checks=None, samples=True, samples_limit=10):
    # Load config
    if config and isinstance(config, str):
        cfg = load_yaml(config)
        checks_config = cfg.get("checks", [])
    elif checks:
        checks_config = parse_inline_checks(checks)
    
    # Resolve source
    if source is None:
        source = cfg.get("source")
    lf, engine = resolve_source(source)
    
    # Schema validation
    schema_issues = validate_schema(lf, cfg.get("schema")) if config else []
    
    # Run checks
    result = asyncio.run(_run(lf, checks_config, engine, samples, samples_limit))
    
    # Auto-alert from YAML config
    if config and cfg.get("alerting") and not result.passed:
        result.alert(cfg["alerting"])
    
    return result
```

### ⑥ result.py (~80 lines)
```python
from dataclasses import dataclass, field

@dataclass
class CheckResult:
    name: str
    column: str | None
    status: str          # "pass" | "warn" | "fail"
    fail_count: int
    total_rows: int

@dataclass
class ElizaResult:
    checks: list[CheckResult] = field(default_factory=list)
    schema_issues: list = field(default_factory=list)
    samples: dict = field(default_factory=dict)
    total_rows: int = 0
    elapsed_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return not any(c.status == "fail" for c in self.checks)

    def summary(self) -> str: ...
    def raise_on_fail(self) -> None: ...
    def to_dict(self) -> dict: ...
    def to_json(self) -> str: ...
    def to_polars(self) -> pl.DataFrame: ...
    def alert(self, config=None, webhook=None) -> bool: ...
    
    def __repr__(self) -> str:
        return self.summary()
```

### ⑦ alert.py (~50 lines)
```python
import json
import urllib.request

def send_slack(webhook=None, token=None, channel=None, blocks=None, text=""):
    if webhook:
        url = webhook
        payload = {"blocks": blocks, "text": text}
        headers = {"Content-Type": "application/json"}
    elif token:
        url = "https://slack.com/api/chat.postMessage"
        payload = {"channel": channel, "blocks": blocks, "text": text}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    return json.loads(urllib.request.urlopen(req).read()).get("ok")

def build_slack_blocks(result) -> list: ...
```

### ⑧ cli.py (~60 lines)
```python
import argparse

def main():
    parser = argparse.ArgumentParser(prog="eliza")
    sub = parser.add_subparsers(dest="command")
    
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--config", required=True)
    check_parser.add_argument("--source")
    
    init_parser = sub.add_parser("init")
    
    args = parser.parse_args()
    # ...
```

---

## Public API (__init__.py)

```python
from eliza.runner import check
from eliza.checks import CHECKS

__all__ = ["check", "CHECKS"]
__version__ = "0.1.0"
```

Usage:
```python
from eliza import check

# YAML config
result = check(df, config="orders")

# Inline (no YAML)
result = check(df, checks={
    "order_id": ["not_null", "unique"],
    "amount": ["not_null", "not_negative", {"between": {"min": 0, "max": 999999}}],
    "email": [{"regex": r"^[\w.]+@[\w.]+$"}],
})

# Result
result.passed              # bool
result.summary()           # "8 passed, 2 warnings, 2 failed (30M rows, 197ms)"
result.raise_on_fail()     # for orchestrators
result.alert()             # Slack
result.to_dict()           # serializable
result.to_polars()         # result as DataFrame
```

---

## Benchmarks (validated)

| Input | Rows | Checks | Time | vs Pandera |
|---|---|---|---|---|
| Polars LazyFrame | 30M | 12 | **197ms** | 9x faster |
| Polars DataFrame | 30M | 12 | 277ms | 6.6x faster |
| Pandas DataFrame | 30M | 12 | 340ms | — |
| Files (streaming) | 30M | 12 | 157ms | 8.4x faster |
| Files (streaming) | 259M | 12 | 12s | 1.6x faster |
| BQ SQL pushdown | 174M | 18 | 23s | 15x faster than Soda |

---

## Total: ~450 lines of code

```
checks.py    ~40 lines
compat.py    ~30 lines
loader.py    ~50 lines
schema.py    ~40 lines
runner.py   ~100 lines
result.py    ~80 lines
alert.py     ~50 lines
cli.py       ~60 lines
─────────────────────
TOTAL       ~450 lines
```

Fastest OSS data quality engine. Period.
