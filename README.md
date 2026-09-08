<div align="center">

# Eliza DQ

**Swiss knife of data quality.**

*One library. Any source. Warehouse SQL, Polars DataFrame, parquet, CSV, pandas.*
*Optimized queries that save you money on BigQuery, Athena, and Snowflake.*

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

## Why Eliza saves you money on DWH

Most DQ tools run checks as separate sequential queries. Each query = a full table scan = you pay for it.

**Eliza batches all checks into a single `SELECT`:**

```sql
-- Eliza: ONE query, one table scan, one bill
SELECT COUNT(*) AS total,
       SUM(CASE WHEN order_id IS NULL THEN 1 ELSE 0 END) AS order_id_not_null,
       SUM(CASE WHEN amount < 0 THEN 1 ELSE 0 END) AS amount_not_negative,
       ...
FROM orders
```

**Soda runs them one by one:**

```sql
-- Soda: query 1 (scan 1, you pay)
SELECT COUNT(CASE WHEN order_id IS NULL THEN 1 END) FROM orders
-- Soda: query 2 (scan 2, you pay again)
SELECT COUNT(CASE WHEN amount < 0 THEN 1 END) FROM orders
-- ... repeat for every check
```

On BigQuery (per-byte billing), Athena (per-byte), or Soda Cloud (per-SPU), this adds up fast. 8 checks = 8x the cost with Soda vs 1x with Eliza.

Failed row samples use `SELECT * WHERE ... LIMIT 10` (one lightweight query). Soda fetches ALL failing rows into memory, then truncates. On millions of failures this means OOM or timeout, and you still pay for the full scan.

## Benchmarks

### SQL Pushdown (Eliza vs Soda)

AWS Athena, Iceberg tables, 8 not_null checks per table.

| Rows | Eliza (no samples) | Eliza (+ 10 samples) | Soda Core* |
|------|-------------------|---------------------|------------|
| **179M** | **9.1s** | **13.2s** | 21.6s |
| **236M** | **13.1s** | **12.2s** | 21.9s |
| **492M** | **15.6s** | **15.1s** | 36.8s |

<sub>* Soda Core OSS does not return failed row samples. Samples require Soda Cloud (paid). Eliza returns actual failed rows via `SELECT ... WHERE ... LIMIT N`.</sub>

### DataFrame Engine (Eliza vs Cuallee, Pandera, GX)

NYC Yellow Taxi (Parquet). 5 checks, warmup + 3 runs, min time.

**In-memory:**

| Rows | Eliza | Cuallee | Pandera | GX |
|------|-------|---------|---------|-----|
| **3M** | **2.3ms** | 7.1ms | 11.4ms | 1,151ms |
| **10M** | **4.4ms** | 11.5ms | 15.0ms | 1,975ms |
| **41M** | **15ms** | 36ms | 43ms | 8,066ms |
| **126M** | **50ms** | 103ms | 130ms | 17,802ms |

**Streaming from disk:**

| Rows | Eliza | Cuallee | Pandera | GX |
|------|-------|---------|---------|-----|
| **41M** (12 files) | **699ms** | 901ms | 966ms | 9,122ms |
| **126M** (24 files) | **1.3s** | 4.1s | 4.2s | 48.8s |
| **259M** (72 files) | **1.9s** | 11.7s | 12.5s | 201s |

<sub>Eliza streams via Polars LazyFrames (constant memory). Competitors load everything into RAM. Reproducible: `python benchmarks/run.py --full`</sub>

## Features

| | Eliza | Soda | GX | Pandera | Cuallee |
|---|:---:|:---:|:---:|:---:|:---:|
| SQL pushdown | 8 DWH | Yes | Yes | - | - |
| Parallel SQL | Yes | - | - | - | - |
| Single scan (batched) | Yes | - | - | - | - |
| Failed row samples | `LIMIT N` | Paid | - | - | - |
| Polars native | Yes | - | - | Yes | Yes |
| LazyFrame streaming | Yes | - | - | - | - |
| YAML config | Yes | Yes | Yes | - | - |
| Inline dict API | Yes | - | - | Yes | Yes |
| CLI | Yes | Yes | Yes | - | - |
| PDF report | Yes | - | - | - | - |
| Slack alerting | Yes | Paid | - | - | - |
| Auto-learn | Yes | - | Yes | Yes | - |
| Schema check | Yes | Yes | Yes | Yes | - |
| FK reference | Yes | Yes | Yes | - | - |
| Core deps | **2** | 30+ | 30+ | 7+ | 3+ |

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

**SQL pushdown:** All inline checks batched into one `SELECT` (single table scan). Separate checks (unique, freshness) and sample queries run in parallel via `ThreadPoolExecutor` with thread-local connections. Samples use `LIMIT N` - never fetches all failing rows.

**Polars engine:** Streaming with per-column grouping. Files scanned as LazyFrames - data streams through without loading into RAM. Failed row samples via `.filter().head(N).collect(engine="streaming")`.

**OLTP mode:** `engine: local` pulls data through the connector, checks locally with Polars. Safe for production databases.

## License

MIT
