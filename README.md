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
result = check(
    "data.parquet",
    checks={
        "order_id": ["not_null", "unique"],
        "amount": ["not_null", "not_negative"],
        "email": ["is_email"],
    },
)
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

- **Smart sampling saves you money** - `sample_id` lets you choose which columns appear in sample queries. Soda runs `SELECT *` for every failing check. On a 48-column table, Eliza scans 24x less data per sample. BQ/Athena charge per byte — fewer columns = lower bill
- **3-19x faster on SQL** than Soda Core on BigQuery (5B rows, 48 cols). Advantage grows with more failing checks — Eliza runs samples in parallel, Soda runs them one by one
- **10-20x faster on DataFrames** than Pandera. Streams 259M rows from disk in 1.3s with constant memory — Pandera, GX, and Dataframely OOM
- **Lightweight** - 2 dependencies (polars + pyyaml) vs 30+ for Soda/GX
- **Works with any source** - same API for 8 warehouse connectors, parquet/CSV files, Polars/pandas DataFrames, and production databases
- **PDF reports and Slack alerts built-in**

## Benchmarks

### SQL Pushdown (Eliza vs Soda Core)

Both tools batch metric checks into a single `SELECT`. The difference is in what happens after: sample queries for failed rows.

- **Eliza:** `SELECT id, failing_col` — 2 columns, LIMIT 10, **parallel** execution
- **Soda:** `SELECT *` — all columns, LIMIT 100, **sequential** execution

On per-byte warehouses (BigQuery, Athena), fewer columns = less data scanned = lower cost.

**BigQuery on-demand, 5B rows, 48 columns:**

| Checks | Failing | Eliza | Soda Core | Ratio |
|--------|---------|-------|-----------|-------|
| 4 | 3 | **800ms** | 2.7s | 3.4x |
| 8 | 5 | **864ms** | 4.3s | 5.0x |
| 16 | 12 | **726ms** | 8.0s | 11x |
| 25 | 21 | **707ms** | 13.7s | 19x |

<sub>Soda grows linearly with failing checks because it runs `SELECT * LIMIT 100` sequentially per failure. Eliza runs `SELECT id, col LIMIT 10` in parallel.</sub>

**BigQuery on-demand, different production tables:**

| Rows | Columns | Checks | Failing | Eliza | Soda Core | Ratio |
|------|---------|--------|---------|-------|-----------|-------|
| **52M** | 14 | 6 | 0 | 1.1s | 1.1s | 1.0x |
| **74M** | 16 | 11 | 5 | **7.2s** | 8.7s | 1.2x |
| **46M** | 32 | 24 | 23 | **5.7s** | 18.7s | 3.3x |
| **5B** | 48 | 8 | 5 | **2.7s** | 3.6s | 1.4x |

<sub>With 0 failures both tools are equally fast — no sample queries run. As failures increase, Eliza's parallel `SELECT id, col` pulls ahead of Soda's sequential `SELECT *`. On 23 failing checks (32-col table), Eliza is 3.3x faster.</sub>

**AWS Athena (Iceberg):**

| Rows | Columns | Eliza | Soda Core |
|------|---------|-------|-----------|
| **179M** | 10 | **13.8s** | 27.1s |
| **492M** | 20 | **18.3s** | 38.4s |

**DuckDB (local, reproducible by anyone):**

| Rows | Eliza | Soda Core | Ratio |
|------|-------|-----------|-------|
| **3M** | **15ms** | 31ms | 2.1x |
| **10M** | **33ms** | 70ms | 2.1x |
| **20M** | **63ms** | 156ms | 2.5x |
| **41M** | **179ms** | 318ms | 1.8x |

<sub>Reproducible: `pip install eliza-dq soda-core-duckdb && python benchmarks/sql_local.py`</sub>

**Smart sampling saves money on per-byte warehouses:**

Soda runs `SELECT *` for every failing check — on a 48-column table that's 24x more data than Eliza's `SELECT id, failing_col`. BQ/Athena charge per byte scanned, LIMIT doesn't reduce cost.

| | Eliza + `sample_id` | Soda Core |
|---|---|---|
| Sample query | `SELECT id, col WHERE col IS NULL LIMIT 10` | `SELECT * WHERE col IS NULL LIMIT 100` |
| Columns scanned per sample | **2** | All (48 in this table) |
| Sample cost ratio | **1x** | **24x** |

<sub>Aggregation query cost is the same for both tools — only the checked columns are scanned. The cost difference is entirely in sample queries. With `sample_id`, Eliza scans 2 columns per sample. Without it, Eliza scans only the checked columns (still fewer than `SELECT *`).</sub>

**Example: daily DQ on a 1TB, 50-column table with 10 failing checks (BQ on-demand $6.25/TB):**

| | Soda Core | Eliza + `sample_id` |
|---|---|---|
| Aggregation | 1TB | 1TB |
| Samples | 10 × 1TB (`SELECT *`) = 10TB | 10 × 0.04TB (2 cols) = 0.4TB |
| **Daily cost** | **$68.75** | **$8.75** |
| **Annual cost** | **$25,000** | **$3,200** |
| **Savings** | | **$21,800/year (87%)** |

<sub>On wider tables or more failing checks, savings grow proportionally. A 50-column table with 20 failing checks: Soda samples cost 20 × full table scan = $125/day ($45K/year). Eliza `sample_id`: 20 × 2 columns = $5/day ($1.8K/year).</sub>

### DataFrame Engine

NYC Yellow Taxi (Parquet). 5 checks, warmup + 3 runs, min time.

**When the DataFrame is already in memory** (notebook, mid-pipeline step):

All tools check everything (Pandera with `lazy=True`). Eliza returns fail counts, fail rates, and sample rows. Others raise an exception or return less detail.

| Rows | Eliza | Pandera | Dataframely | Pointblank | GX |
|------|-------|---------|-------------|------------|-----|
| **3M** | **2ms** | 21ms | 10ms | 44ms | 1.2s |
| **10M** | **4ms** | 60ms | 26ms | 104ms | 2.2s |
| **41M** | **14ms** | 257ms | 161ms | 2.5s | 91.8s |
| **109M** | **35ms** | 711ms | 1.2s | 939ms | 60.1s |

<sub>Eliza is 10-20x faster than Pandera, 5-34x faster than Dataframely, and 600-6500x faster than GX. 109M tested with 4 columns to fit competitors in RAM. GX includes pandas conversion (real-world usage). Reproducible: `python benchmarks/dataframe.py`</sub>

**What you get back when checks fail:**

| | Eliza | Pandera | Dataframely | Pointblank | GX |
|---|---|---|---|---|---|
| Fail count per check | Yes | No | No | Yes | Yes |
| Fail rate per check | Yes | No | No | Yes | No |
| Sample failing rows | Yes | No | Yes (all) | No | No |
| Structured result | Yes | Exception | Tuple | Report | Result |
| JSON / dict export | Yes | No | No | No | Yes |
| Exit code for CI | Yes | No | No | No | No |

**When reading from files** (S3, CI runner, Lambda, cron job):

Competitors need the entire dataset in memory as a DataFrame before running checks. Eliza streams via Polars LazyFrames and never loads the full dataset.

| Rows | Eliza | Eliza peak RAM | Full dataset size |
|------|-------|----------------|-------------------|
| **10M** (3 files) | **27ms** | ~200 MB | 1.2 GB |
| **41M** (12 files) | **109ms** | ~500 MB | 5.2 GB |
| **126M** (24 files) | **535ms** | ~860 MB | 3.8 GB (4 cols) |
| **259M** (72 files) | **1.3s** | ~820 MB | 7.6+ GB |

> Eliza's peak RAM stays under 1 GB at all tested scales -- data streams through in chunks via Polars LazyFrames. Competitors must load all files into a single DataFrame first. At 259M rows with all columns that's 7.6+ GB, enough to OOM an 8 GB Lambda or CI runner. Streaming is a feature of Polars; Eliza's value is that 17 checks, fail counts, sample rows, and reports come on top of it. Reproducible: `python benchmarks/dataframe.py --full`

## Eliza vs Soda Core

| | Eliza | Soda Core |
|---|---|---|
| **BQ speed (5B rows)** | **707ms - 2.8s** | 2.7s - 13.7s |
| **Athena speed** | **2x faster** (parallel samples + 20ms cold start) | Sequential samples, ~350ms cold start |
| **Sample queries** | `SELECT id, col LIMIT 10` — parallel | `SELECT * LIMIT 100` — sequential |
| **Sample cost (48-col table)** | **2 columns per sample** | **48 columns per sample (24x more)** |
| **Failed rows in CLI** | Built-in, always visible | Hidden by default (DefaultSampler discards rows) |
| **Failed rows in Slack/PDF** | Built-in | No |
| **DataFrames** | Polars streaming, 259M in 1.3s | No |
| **Dependencies** | 2 (polars + pyyaml) | 30+ |
| **Check batching** | Single SELECT | Single SELECT |

<sub>On per-byte warehouses (BQ, Athena), LIMIT doesn't reduce cost — price is determined by columns in SELECT, not rows returned. One `SELECT *` sample on a 48-column table costs the same as scanning all 48 columns. Eliza scans 2 columns per sample with `sample_id`, or only the checked columns by default.</sub>

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

result.raise_on_fail()  # RuntimeError (Airflow, Dagster, Prefect)
result.exit_code  # 0/1/2 (bash, CLI, GitHub Actions)
result.to_dict()  # dict (XCom, metadata)
result.to_json()  # JSON string (APIs)
result.summary()  # "3 passed, 1 failed (1M rows, 42ms)"
```

## Architecture

**SQL pushdown:** All inline checks batched into one `SELECT` (single table scan). Separate checks (unique, freshness) and sample queries run in parallel via `ThreadPoolExecutor` with thread-local connections. Samples use `SELECT column_list` with `LIMIT N` instead of `SELECT *`.

**Polars engine:** Streaming with per-column grouping. Files scanned as LazyFrames - data streams through without loading into RAM. Failed row samples via `.filter().head(N).collect(engine="streaming")`.

**OLTP mode:** `engine: local` pulls data through the connector, checks locally with Polars. Safe for production databases.

## License

MIT
