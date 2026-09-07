# Eliza DQ — Development Roadmap

Lightweight, decorator-first data quality checks. Best DX from every competitor in one tool.

**Core deps**: `polars`, `pyyaml`
**Architecture**: IR + Compiler pattern. Check defined once → compiled to Polars expr or SQL.
**Two orthogonal axes**: Engine (auto from source) × Scope (full / sample / partition)
**Multi-engine**: Polars (small/local) → Iceberg metadata (zero-scan) → DuckDB (large/streaming) → SQL pushdown (DWH)

---

## Phase 0: Scaffolding ✅

- [x] pyproject.toml (polars, pyyaml, hatchling)
- [x] src/eliza/__init__.py, py.typed
- [x] tests/, LICENSE, .gitignore
- [x] examples/mini_mvp/ — working proof of concept

---

## Phase 1: Core Engine — "it works"

Goal: `result = check(df, config="orders")` works end-to-end.

### Step 1.1 — compat.py (source resolution)
```python
resolve_source(source) → pl.LazyFrame
```
- DataFrame (Polars/Pandas) → `pl.LazyFrame`
- File path (.parquet/.csv/.ndjson) → `pl.scan_*`
- Source from YAML → auto-resolve
- Scope handling: `full` / `sample:N%` / `partition` filter

### Step 1.2 — checks.py (IR + top 20 checks)
Each check = IR definition with metadata + Polars compiler.

**Top 20 checks for v0.1 (covers 90% of production needs):**

Tier 1 — every table needs:
```
not_null          — column has no NULLs
unique            — no duplicate values
row_count         — between(min, max)
in_set            — values from allowed list only
between           — numeric/date in range
freshness         — max(col) within max_age of now()
schema            — columns exist with correct types
```

Tier 2 — catches most bugs:
```
not_negative      — no negative values
regex             — custom pattern match
is_email          — valid email (built-in pattern)
compound_unique   — unique on column combination
column_a_gt_b     — cross-column (end_date > start_date)
not_null_percent  — allow some nulls (mostly: 0.95)
distinct_count    — expected cardinality range
```

Tier 3 — production polish:
```
is_url            — valid URL format
string_length     — length_between(min, max)
is_iso_date       — valid YYYY-MM-DD
mean_between      — average in expected range
is_uuid           — valid UUID format
row_count_change  — volume anomaly vs previous run
```

Each check declares metadata:
```python
{
    "samplable": True/False,
    "requires_full_scan": False,
    "supported_engines": ["polars", "sql"],
}
```
Planner rejects impossible combos (e.g. `unique` + `sample:1%` → ERROR with explanation).

Custom checks:
```python
from eliza import register_check
register_check("my_rule", lambda col, v: pl.col(col).str.len() > v["min"])
```

### Step 1.3 — loader.py (YAML parsing)
```
eliza_checks/
├── orders.yaml
├── users.yaml
└── crossref_silver.yaml
```
- Auto-discovery: `eliza_checks/{name}.yaml` in cwd
- Parses: source, scope, defaults, schema, checks, alerting sections
- Env var substitution: `${SLACK_WEBHOOK}`
- `for_each` support: loop over columns

### Step 1.4 — schema.py (schema validation)
```yaml
schema:
  order_id: int64, not_null, unique
  amount: float64, not_null
  status: string
  strict: true
```
- Column presence + type matching
- Strict mode (reject extra columns)
- Schema evolution detection (vs previous scan)

### Step 1.5 — runner.py (orchestration)
```
source → resolve → auto-select engine → scope filter → schema → checks → collect → result
```
- **Auto engine selection** (user doesn't choose):
  - DataFrame <10M → Polars expressions
  - Local file → Polars scan_* + streaming
  - Iceberg metadata-solvable → PyIceberg manifest stats (zero scan)
  - Iceberg row-level → scan().to_duckdb() (streaming, spill-to-disk)
  - DWH source → SQL pushdown
- All Polars check expressions in ONE `lf.select([...]).collect(engine='streaming')`
- Severity: skip / warn / fail per check
- Thresholds: 3-tier `(warn, fail, critical)` like Pointblank
- Collected errors: show ALL problems, not fail-fast (Patito pattern)
- Auto side-effects from YAML (alerting, history)

### Step 1.6 — result.py (ElizaResult)
```python
result = check(df, config="orders")

result.passed           # bool
result.summary()        # "17 passed, 2 warnings, 1 failed (41M rows, 2.3s)"
result.raise_on_fail()  # raises ElizaCheckError
result.to_dict()        # serializable (Airflow XCom)
result.to_json()        # JSON string
result.to_polars()      # result AS DataFrame (Cuallee pattern) — inspectable, joinable
result.passed_df        # clean rows
result.quarantine_df    # failed rows + metadata (Dataframely .filter() pattern)
result.checks           # list of CheckResult details
```

### Step 1.7 — Public API (__init__.py)
```python
from eliza import check, register_check

# From YAML source
result = check(config="orders")

# Override source
result = check(config="orders", source="s3://bucket/orders.parquet")

# Pass DataFrame
result = check(df, config="orders")

# Inline (no YAML)
result = check(df, rules={"amount": ["not_null", "positive"], "email": ["is_email"]})

# Pipe-friendly (Wimsey pattern)
df.pipe(eliza.check, config="orders")
```

**Milestone: `pip install -e .` → write YAML → `check()` → see results.**

---

## Phase 2: Developer Experience

### Step 2.1 — decorator.py
```python
@eliza(check='orders')
def process_orders(df):
    return df.with_columns(...)

clean_df = process_orders(raw_df)
report = eliza.last_result()
```

### Step 2.2 — cli.py
```bash
eliza init                                  # create eliza_checks/ with example
eliza check --config orders                 # run checks
eliza check --config orders --tag critical  # filter by tag
eliza profile data.parquet                  # data profiling
eliza learn data.parquet                    # auto-generate checks (TFDV-inspired)
```
Exit codes: 0=pass, 1=fail, 2=error. `rich` for colored output (optional dep `[cli]`).

### Step 2.3 — Scope config
```yaml
source: s3://bucket/orders.parquet
scope: partition                   # full | sample:1% | partition
partition_by: _loaded_at
partition_window: 1d
```
Engine auto-detected from source. Scope = user choice. Planner validates combos.

### Step 2.4 — Tags + for_each
```yaml
# Tags
checks:
  - column: amount
    check: not_null
    tags: [critical, billing]

# for_each — eliminates YAML repetition (Soda pattern)
for_each:
  columns: [amount, price, total, tax]
  checks:
    - check: not_null
    - check: not_negative
```
`eliza check --tag critical` in prod, all in dev.

### Step 2.5 — Cross-table checks (Soda reference pattern)
```yaml
# FK integrity
reference:
  column: user_id
  other_table: users
  other_column: id

# Row count comparison
cross_check:
  row_count_equals: other_table
```

**Milestone: CLI, decorator, scope, tags, for_each, cross-table — production-ready.**

---

## Phase 3: Observability

### Step 3.1 — history.py
SQLite `.eliza/history.db`. Stores check results between runs.

### Step 3.2 — alert.py
Slack Block Kit via `urllib.request` (zero deps). Primary report channel.
```yaml
alerting:
  webhook: ${ELIZA_SLACK_WEBHOOK}
  on_fail: full_report
  on_warn: summary
  on_pass: silent
```
Phase 4+: Slack Bot Token (xoxb-*), multi-channel routing, thread replies.

### Step 3.3 — report.py
Jinja2 HTML (optional dep `[report]`). Inline CSS, SVG sparklines from history.

### Step 3.4 — Anomaly detection + change-over-time
- Current metric vs rolling mean ± N stddev (Elementary pattern)
- Change thresholds: `change avg last 7 between -10% and 10%` (Soda pattern)
- Distribution checks: KS / Chi-square / PSI tests

### Step 3.5 — Group by (Soda pattern)
```yaml
group_by: country
checks:
  - check: row_count
    min: 100
```
Checks per category — catches per-segment issues.

### Step 3.6 — Schema evolution
Auto-detect schema changes vs previous scan (Soda pattern):
```yaml
schema:
  warn:
    when_schema_changes: any
  fail:
    when_required_column_missing: [pk, amount]
```

**Milestone: history, trends, Slack alerts, anomaly detection, schema evolution.**

---

## Phase 4: Multi-Engine

### Step 4.1 — Iceberg metadata tier (zero-scan)
PyIceberg manifest stats: `null_value_counts`, `lower_bounds`, `upper_bounds`, `record_count`.
Covers not_null, row_count, between, freshness — without reading data. <1 sec.

### Step 4.2 — DuckDB embedded engine
`scan().to_duckdb()` → local SQL execution with streaming + spill-to-disk.
279M rows on 4GB RAM. No warehouse needed. Optional dep `[duckdb]`.

### Step 4.3 — SQL pushdown
IR → SQL compiler + SQLGlot for dialect transpilation.
BQ/Snowflake/Postgres/Athena. TABLESAMPLE for sampling.

**Architecture**: hybrid query strategy, user chooses detail level:
```yaml
samples: false  # default — 1 query, cheapest, numbers only
samples: true   # 1 query + N sample queries (LIMIT 100) for failed checks
```

**Step 1** (always): One batched SELECT with all SUM/COUNT/MAX aggregations → one table scan.
**Step 2** (only if samples: true AND checks failed): Parallel queries per failed check with LIMIT 100 → concrete failing rows for debugging.

Uses SAFE.REGEXP_CONTAINS (BQ) to prevent one bad regex from killing all checks.

**Validated benchmarks on BQ (174M rows, payments_events):**
| Mode | Time | Queries | BQ Cost |
|---|---|---|---|
| Eliza samples: false | 21s | 1 | ~$0.015 |
| Eliza samples: true | 23s | 1 + 2 samples | ~$0.05 |
| Soda Core | 350s (5:50) | 3 sequential | ~$0.15 |

**Eliza = 15x faster, 3x cheaper, more checks than Soda.**

Soda runs 3 sequential queries always (aggregation + duplicate CTE + schema). Eliza batches into 1 query + optional parallel samples. Soda pays 3x table scan cost.

Supported DWH connectors:
- BigQuery — `google-cloud-bigquery` (optional dep `[bigquery]`)
- Snowflake — `snowflake-connector-python` (optional dep `[snowflake]`)
- Athena — `boto3` (optional dep `[athena]`)
- PostgreSQL — ConnectorX (optional dep `[postgres]`)

### Step 4.4 — Conformance test suite
One fixture dataset with edge cases. Results must match across all engines.
"Same semantics everywhere, here's the test."

**Milestone: one YAML, four engines, same results.**

---

## Phase 5: Advanced Features

### JSON schema drift (UNCONTESTED)
`str.json_decode()` → Polars struct → diff vs baseline

### Data profiling
`eliza profile <file>` → per-column stats

### `eliza learn` (TFDV-inspired)
Auto-generate checks from data profiling — run once on good data, get YAML

### Quarantine enhancements
Write failed rows to S3/local/DWH with metadata

### Vector / Embedding checks (UNCONTESTED)
`vector_dim`, `vector_normalized`, `vector_no_nan`

### Reconciliation (Soda pattern)
Source → target validation across data sources

### 41+ valid formats
`is_money`, `is_percentage`, `is_time_12h/24h`, `is_phone_intl`, etc.

---

## Phase 6: Cloud + Integrations

### Integrations
`eliza-airflow`, `eliza-dagster`, `eliza-dbt`

### Sidecar mode
Persistent container next to pipeline pods — self-contained, no cloud dependency

### Eliza Cloud
```
Eliza lib (on-prem) → eliza cloud push → Cloud API
Dashboard, history, alerts, SSO/RBAC, scheduled runs
Data never leaves customer — only metadata/results
```

---

## Performance Benchmarks (validated)

| Scenario | Rows | Checks | Time | RAM |
|---|---|---|---|---|
| In-memory DataFrame | 2M | 6 | 48ms | minimal |
| Parquet streaming (NYC Taxi) | 41M | 20 | 2.3s | 0.1 MB |
| Parquet quarantine split | 41M | 4 | 0.7s | 0.1 MB |
| Iceberg sample (3 random files) | 100k/179M | 9 | 23ms | ~500 MB |
| Iceberg batch streaming (Lambda) | 279M | 4 | 11 min | 4 GB |
| SQL pushdown (Athena) | 179M | 6 | 12s | 0 MB |
| SQL pushdown full table (Athena) | 279M | 11 | 38s | 0 MB |

---

## Competitive Position

### DX stolen from the best

| From | What we take |
|---|---|
| **Soda** | YAML readability, for_each, reference checks, schema evolution, group_by, change-over-time |
| **GX** | Cross-table checks, distribution tests, full expectations catalog |
| **Dataframely** | `.filter()` → (good, bad) quarantine split |
| **Cuallee** | Result as inspectable DataFrame |
| **Wimsey** | `.pipe()` integration — zero friction |
| **Pointblank** | 3-tier thresholds (warn/fail/critical) |
| **Patito** | Collected errors — show ALL problems |
| **Pandera** | `@check_types` on function annotations |
| **WhyLogs** | Sketch-based profiling (fixed RAM any size) |
| **TFDV** | `eliza learn` — auto-generate checks from data |
| **DQOps** | Rule mining / auto-suggest |

### Uncontested features (no competitor has)

- JSON column schema drift detection
- Semantic checks built-in (is_email, is_url, is_uuid — 41+ formats)
- Vector/embedding quality checks
- Configurable sampling in OSS (`sample: 10%`)
- Zero-scan metadata tier (Iceberg/Parquet stats)
- Auto engine selection (Polars/DuckDB/SQL — user doesn't choose)
- Webhook alerting in OSS (Soda = cloud-only)
- `eliza learn` — auto-generate checks from data
- PyIceberg incremental scan (only new data since last snapshot)

### Competitor execution comparison

| Tool | Lines to first check | Can check files? | Can check DataFrames? | Alerting OSS? |
|---|---|---|---|---|
| **Eliza** | 1 (`check(df, config="x")`) | ✅ | ✅ | ✅ |
| Soda | 6 + 2 YAML files + DB config | ❌ SQL-only | ❌ | ❌ cloud |
| GX | 15+ method calls, 6 objects | ❌ | ✅ Pandas only | ❌ |
| Dataframely | 8 (class definition) | ❌ | ✅ Polars only | ❌ |
| Cuallee | 4 | ❌ | ✅ | ❌ |
| Daffy | 3 (decorator) | ❌ | ✅ | ❌ |
| Pointblank | 5 | ❌ | ✅ | ❌ |
| Pandera | 6 | ❌ | ✅ | ❌ |

Start small. Nail the core. Community comes.
