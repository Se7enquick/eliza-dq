<div align="center">

# Eliza DQ

**Swiss knife of data quality.**

*One library. Any source. Warehouse SQL, Polars DataFrame, parquet, CSV, pandas.*

[![CI](https://github.com/Se7enquick/eliza-dq/actions/workflows/ci.yml/badge.svg)](https://github.com/Se7enquick/eliza-dq/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/eliza-dq)](https://pypi.org/project/eliza-dq/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://pypi.org/project/eliza-dq/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

---

Eliza DQ validates any data source with a single API. Point it at a warehouse table, a parquet file, a pandas DataFrame, or a database URI and get results in milliseconds.

```bash
pip install eliza-dq
```

### On a warehouse (BigQuery, Athena, Snowflake, ...)

```yaml
# eliza_checks/orders.yaml
connection:
  type: bigquery
  project: my-project-123

table: my-project-123.analytics.orders
sample_id: order_id    # optional: cheaper sample queries on wide tables

checks:
  - column: order_id
    check: not_null
  - column: amount
    check: not_negative
  - column: updated_at
    check: freshness
    max_age: 24h
```

```bash
pip install eliza-dq[bigquery]
eliza check --config orders
```

### On a DataFrame or file

```python
from eliza import check

# Polars DataFrame, pandas DataFrame, parquet, CSV, ndjson - all work
result = check("data.parquet", checks={
    "order_id": ["not_null", "unique"],
    "amount":   ["not_null", "not_negative"],
    "email":    ["is_email"],
})
result.raise_on_fail()
```

### On a production database (without running heavy queries on prod)

```yaml
connection:
  type: postgres
  host: prod-db.internal
  user: readonly
  password: ${DB_PASSWORD}
  database: production

engine: local    # pulls data, checks locally with Polars
table: orders
filter: "created_at >= '2024-01-01'"

checks:
  - column: order_id
    check: not_null
```

---

## Why Eliza

- **You control what gets scanned** - `sample_id` and `sample_columns` let you choose exactly which columns appear in sample queries. On per-byte warehouses (BQ, Athena) this cuts sample costs by up to 92% on wide tables. Soda always runs `SELECT *`
- **Optimized SQL** - parallel sample collection, `COUNT(CASE...THEN 1 END)` aggregation, `HAVING COUNT(*)` for cross-dialect compatibility. 1.1-2.2x faster than Soda across 10 tested tables without any caching
- **Handles datasets that crash other tools** - Polars LazyFrame streaming validates 259M rows from disk in 1.9s with constant memory. Pandera and GX OOM
- **2-3x faster on DataFrames** than Pandera at constant memory
- **Lightweight** - 2 dependencies (polars + pyyaml) vs 30+ for Soda/GX
- **Works with any source** - same API for 8 warehouse connectors, parquet/CSV files, Polars/pandas DataFrames, and production databases
- **PDF reports and Slack alerts built-in**

## Benchmarks

### SQL Pushdown (Eliza vs Soda Core)

8 identical `not_null` checks + failed row samples. Both tools batch checks into a single `SELECT`. Both use `LIMIT` on sample queries. All measurements with `use_query_cache=False`. 3 interleaved runs, median time.

**AWS Athena (Iceberg):**

| Rows | Columns | Eliza | Soda Core |
|------|---------|-------|-----------|
| **179M** | 10 | **11.4s** | 20.4s |
| **236M** | 12 | **13.5s** | 21.4s |
| **492M** | 20 | **16.2s** | 29.2s |

Eliza is 1.6-1.8x faster on Athena. Advantage comes from parallel sample collection and lighter client (~176ms init vs ~350ms). On Athena, each query has fixed overhead (Glue metadata, S3 listing, queue), and parallel execution avoids paying it sequentially.

**BigQuery on-demand (fresh tables, `use_query_cache=False`):**

| Rows | Columns | Eliza | Soda Core | Ratio |
|------|---------|-------|-----------|-------|
| **137M** | 28 | **4.5s** | 9.9s | 2.2x |
| **175M** | 3 | **2.6s** | 4.4s | 1.7x |
| **227M** | 62 | **2.0s** | 3.8s | 1.9x |
| **428M** | 21 | **5.8s** | 6.2s | 1.1x |
| **623M** | 9 | **9.8s** | 11.8s | 1.2x |
| **1.2B** | 56 | **7.9s** | 10.6s | 1.3x |

**DWH cost with `sample_id` (BQ on-demand $6.25/TB, Athena $5/TB):**

| Rows | Columns | Failing | Eliza + `sample_id` | Soda / Eliza default | Savings |
|------|---------|---------|---------------------|---------------------|---------|
| **1.2B** | 56 | 6 | **$1.60** | $20.36 | 92% |
| **137M** | 28 | 3 | **$0.22** | $1.97 | 89% |
| **428M** | 21 | 1 | **$0.59** | $1.15 | 48% |

<sub>Eliza gives you control over what gets scanned in sample queries. With `sample_id`, samples scan only 2 columns (ID + failing column) instead of `SELECT *` over all columns. BQ/Athena charge per byte scanned, so fewer columns = proportionally cheaper. On a 56-column table with 6 failing checks: 6 queries x 56 cols vs 6 queries x 2 cols = 28x less data scanned. You can also use `sample_columns` to pick exactly which columns to include. Aggregation cost is always the same -- both tools scan only the checked columns. Without `sample_id`, Eliza and Soda cost the same.</sub>

### DataFrame Engine (Eliza vs Pandera, Dataframely, GX)

NYC Yellow Taxi (Parquet). 5 checks, warmup + 3 runs, min time. Reproducible: `python benchmarks/dataframe.py --full`

**In-memory (pre-loaded Polars DataFrame):**

| Rows | Eliza | Pandera | GX |
|------|-------|---------|----|
| **3M** | **2.3ms** | 11.4ms | 1,151ms |
| **10M** | **4.4ms** | 15.0ms | 1,975ms |
| **41M** | **15ms** | 43ms | 8,066ms |
| **126M** | **50ms** | 130ms | 17,802ms |

**Streaming from disk (constant memory):**

| Rows | Eliza | Pandera | GX |
|------|-------|---------|----|
| **41M** (12 files) | **699ms** | 966ms | 9,122ms |
| **126M** (24 files) | **1.3s** | 4.2s | 48.8s |
| **259M** (72 files) | **1.9s** | 12.5s | 201s |

> At 259M rows, competitors need 7.6+ GB just to hold the data and OOM in constrained environments (Lambda, CI runners, containers). Eliza streams via Polars LazyFrames with constant memory.

## Eliza vs Soda Core

| | Eliza | Soda Core |
|---|---|---|
| **Speed (no cache)** | **1.1-2.2x faster** (10 tables, BQ + Athena) | Baseline |
| **Cost with `sample_id`** | **Up to 92% cheaper** | Always `SELECT *` |
| **Cost without `sample_id`** | Same | Same |
| **Why faster** | Parallel samples + optimized aggregation + lighter client (2 deps, ~176ms) | Sequential samples, 30+ deps, ~350ms init |
| **Why cheaper** | You choose: `sample_id`, `sample_columns`, `samples_limit` | No control over sample queries |
| **DataFrames** | Polars streaming, 259M in 1.9s, constant memory | No DataFrame support |
| **PDF reports** | Built-in | No |
| **Slack alerts** | Built-in | Built-in |
| **Check batching** | Single SELECT | Single SELECT |

## Features

| | Eliza | Soda | GX | Pandera |
|---|:---:|:---:|:---:|:---:|
| SQL pushdown | 8 DWH | Yes | Yes | - |
| Parallel samples | Yes | - | - | - |
| Sample column control | Yes | - | - | - |
| Polars native | Yes | - | - | Yes |
| LazyFrame streaming | Yes | - | - | - |
| YAML config | Yes | Yes | Yes | - |
| Inline dict API | Yes | - | - | Yes |
| CLI | Yes | Yes | Yes | - |
| PDF report | Yes | - | - | - |
| Slack alerting | Yes | Yes | - | - |
| Auto-learn | Yes | - | Yes | Yes |
| Schema check | Yes | Yes | Yes | Yes |
| FK reference | Yes | Yes | Yes | - |
| Core deps | **2** | 30+ | 30+ | 7+ |

## Checks

17 built-in checks, all work on both Polars and SQL:

| Check | What it does |
|-------|-------------|
| `not_null` | No NULL values |
| `not_missing` | No NULLs or custom values ("", "N/A", "null") |
| `unique` | All values distinct |
| `not_negative` | No values below zero |
| `between` | Values within min/max range |
| `in_set` | Values in allowed list |
| `regex` | Match a pattern |
| `is_email` | Valid email format |
| `is_url` | Valid URL format |
| `min_length` | String minimum length |
| `max_length` | String maximum length |
| `freshness` | Data not older than threshold |
| `row_count` | Row count within range |
| `cross_column` | Compare two columns |
| `schema` | Validate column names and types |
| `reference` | FK integrity across tables |
| `custom_sql` | Your own SQL expression |

## Warehouse Connectors

Install only what you need:

```bash
pip install eliza-dq[bigquery]
pip install eliza-dq[athena]
pip install eliza-dq[snowflake]
pip install eliza-dq[postgres]
pip install eliza-dq[clickhouse]
pip install eliza-dq[mysql]
pip install eliza-dq[databricks]
pip install eliza-dq[redshift]
```

<details>
<summary>Connection examples for all warehouses</summary>

```yaml
# BigQuery
connection:
  type: bigquery
  project: my-project
  location: US

# Athena
connection:
  type: athena
  region: us-east-1
  schema: my_database
  s3_staging_dir: s3://bucket/athena-results/

# Snowflake
connection:
  type: snowflake
  account: xy12345.us-east-1
  user: eliza_user
  password: ${SF_PASSWORD}
  warehouse: COMPUTE_WH
  database: ANALYTICS
  schema: PUBLIC

# PostgreSQL
connection:
  type: postgres
  host: localhost
  port: 5432
  user: postgres
  password: ${PG_PASSWORD}
  database: mydb

# MySQL
connection:
  type: mysql
  host: localhost
  user: root
  password: ${MYSQL_PASSWORD}
  database: mydb

# ClickHouse
connection:
  type: clickhouse
  host: localhost
  port: 8123
  user: default
  database: mydb

# Databricks
connection:
  type: databricks
  host: adb-123.azuredatabricks.net
  http_path: /sql/1.0/warehouses/abc
  token: ${DBX_TOKEN}

# Redshift
connection:
  type: redshift
  host: cluster.region.redshift.amazonaws.com
  database: analytics
  user: eliza_user
  password: ${RS_PASSWORD}
```

</details>

## Alerting & Reporting

```python
from eliza import check
from eliza.alert import send_slack, send_webhook
from eliza.report import generate_pdf

result = check(config="orders")

# Slack - choose any channel, attach PDF
send_slack(
    result,
    token="xoxb-...",
    channel="C0ALERTS",
    pdf=True,
    name="orders",
)

# PDF report
generate_pdf(result, name="orders")

# Generic webhook (Discord, Teams, PagerDuty)
send_webhook(result, url="https://your-webhook-url/...")
```

```bash
pip install eliza-dq[report]  # for PDF reports
```

<table>
<tr>
<td width="50%">

**Slack Alert**

<img src="docs/assets/slack_alert.png" width="100%" alt="Slack alert">

</td>
<td width="50%">

**PDF Report**

<img src="docs/assets/pdf_report.png" width="100%" alt="PDF report">

</td>
</tr>
</table>

## Orchestrator Integration

### Airflow

```python
@task
def dq_check():
    from eliza import check
    from eliza.alert import send_slack

    result = check(config="orders")

    if not result.passed():
        send_slack(result, token="xoxb-...", channel="C...", pdf=True, name="orders")

    result.raise_on_fail()
    return result.to_dict()
```

### Dagster

```python
@asset_check(asset=orders)
def orders_quality():
    from eliza import check
    result = check(config="orders")
    return AssetCheckResult(
        passed=result.passed(),
        metadata={"summary": result.summary()},
    )
```

### GitHub Actions

```yaml
steps:
  - run: pip install eliza-dq
  - run: eliza check --config orders --source data/orders.parquet
```

### Any orchestrator

```python
result = check(config="orders")

result.raise_on_fail()   # RuntimeError (Airflow, Dagster, Prefect)
result.exit_code         # 0/1/2 (bash, CLI, GitHub Actions)
result.to_dict()         # dict (XCom, metadata)
result.to_json()         # JSON string (APIs)
result.summary()         # "3 passed, 1 failed (1M rows, 42ms)"
```

## Architecture

**SQL pushdown:** All inline checks batched into one `SELECT` (single table scan). Separate checks (unique, freshness) and sample queries run in parallel via `ThreadPoolExecutor` with thread-local connections. Samples use `SELECT column_list` with `LIMIT N` instead of `SELECT *`.

**Polars engine:** Streaming with per-column grouping. Files scanned as LazyFrames - data streams through without loading into RAM. Failed row samples via `.filter().head(N).collect(engine="streaming")`.

**OLTP mode:** `engine: local` pulls data through the connector, checks locally with Polars. Safe for production databases.

## License

MIT
