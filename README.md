<div align="center">

# Eliza DQ

**The fastest open-source data quality engine for Python.**

*259M rows. 17 checks. Failed row samples. Under 2 seconds.*

[![CI](https://github.com/Se7enquick/eliza-dq/actions/workflows/ci.yml/badge.svg)](https://github.com/Se7enquick/eliza-dq/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/eliza-dq)](https://pypi.org/project/eliza-dq/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://pypi.org/project/eliza-dq/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

---

Eliza DQ validates DataFrames and warehouse tables at any scale. It streams data through Polars LazyFrames (constant memory, no matter the dataset size), pushes checks to warehouses with parallel SQL queries, and collects failed row samples instantly via `LIMIT N`. No full materialization, no OOM, no waiting.

**Two lines to your first check:**

```bash
pip install eliza-dq
```

```python
from eliza import check

result = check("data.parquet", checks={
    "order_id": ["not_null", "unique"],
    "amount":   ["not_null", "not_negative"],
    "email":    ["is_email"],
})
print(result.summary())
# 3 passed, 0 warnings, 2 failed (1,000,000 rows, 3ms)
```

**What you get out of the box:**

- **17 built-in checks** with zero configuration (not_null, unique, regex, is_email, freshness, schema, FK reference, and more)
- **8 warehouse connectors** with one-line YAML setup (BigQuery, Athena, Snowflake, Postgres, ClickHouse, MySQL, Databricks, Redshift)
- **3 interfaces** to fit your workflow (inline dict for notebooks, YAML config for production, CLI for CI/CD)
- **Slack alerts with PDF reports** including donut charts, failure distribution bars, and sample tables
- **Auto-learn** checks from your data with `eliza learn data.parquet`
- **2 core dependencies** (polars + pyyaml). No numpy. No pandas. No bloat.

## Benchmarks

NYC Yellow Taxi dataset (Parquet). 5 identical checks. Warmup + 3 runs, min time. Apple M-series, Python 3.13.

### DataFrame Engine (in-memory)

Pre-loaded Polars DataFrame - pure check speed, no I/O.

| Rows | Eliza | Cuallee | Pandera | GX |
|------|-------|---------|---------|-----|
| **3M** | **2.3ms** | 7.1ms | 11.4ms | 1,151ms |
| **10M** | **4.4ms** | 11.5ms | 15.0ms | 1,975ms |
| **41M** | **15ms** | 36ms | 43ms | 8,066ms |
| **126M** | **50ms** | 103ms | 130ms | 17,802ms |

<sub>GX requires pandas - times include check execution only (pandas conversion adds 1-4s extra). Polars-native libraries (Eliza, Cuallee, Pandera) tested on Polars DataFrames directly.</sub>

### File Streaming (from disk)

Total wall time including file I/O - realistic workload (e.g. S3 to Lambda, local parquet files).

| Rows | Eliza | Cuallee | Pandera | GX |
|------|-------|---------|---------|-----|
| **41M** (12 files) | **699ms** | 901ms | 966ms | 9,122ms |
| **126M** (24 files) | **1.3s** | 4.1s | 4.2s | 48.8s |
| **259M** (72 files) | **1.9s** | 11.7s | 12.5s | 201s |

> Eliza streams from disk via Polars LazyFrames. Data flows through in chunks without loading the full dataset into memory. Competitors must read all files into a single in-memory DataFrame before running checks. At 259M rows, that means 7.6+ GB of RAM just to hold the data.

### SQL Pushdown Engine

AWS Athena, Iceberg tables, 8 not_null checks per table, `pyathena` connector.

| Rows | Eliza (no samples) | Eliza (+ 10 samples) | Soda Core* |
|------|-------------------|---------------------|------------|
| **179M** | **9.1s** | **13.2s** | 21.6s |
| **236M** | **13.1s** | **12.2s** | 21.9s |
| **492M** | **15.6s** | **15.1s** | 36.8s |

<sub>* Soda Core OSS does not return failed row samples. `DefaultSampler` is a Cloud-only feature (paid). Eliza returns actual failed rows via `SELECT ... WHERE ... LIMIT N`.</sub>

> Eliza batches all inline checks into one `SELECT` and runs sample queries in parallel. Soda runs all queries sequentially. Eliza with 10 sample rows is faster than Soda without any samples on every scale tested.

## Eliza vs Competitors

### Features

| Feature | Eliza | Soda | GX | Pandera | Cuallee | Dataframely |
|---------|:-----:|:----:|:--:|:-------:|:-------:|:-----------:|
| Polars native | Yes | - | - | Yes | Yes | Yes |
| LazyFrame streaming | Yes | - | - | - | - | - |
| SQL pushdown | 8 DWH | Yes | Yes | - | - | - |
| Parallel SQL queries | Yes | - | - | - | - | - |
| Failed row samples | `LIMIT N` | All rows* | - | - | - | All rows* |
| YAML config | Yes | Yes | Yes | - | - | - |
| Inline dict API | Yes | - | - | Yes | Yes | Yes |
| CLI | Yes | Yes | Yes | - | - | - |
| Auto-learn from data | Yes | - | Yes | Yes | - | - |
| PDF report | Yes | - | - | - | - | - |
| Slack alerting | Yes | Cloud** | - | - | - | - |
| Partition filter | Yes | Yes | Yes | - | - | - |
| Schema validation | Yes | Yes | Yes | Yes | - | Yes |
| FK reference check | Yes | Yes | Yes | - | - | - |
| Core dependencies | **2** | 30+ | 30+ | 7+ | 3+ | 2 |

<sub>* Materializes all failing rows in memory before truncating - causes OOM/timeout on large failures.</sub><br>
<sub>** Soda Slack alerting requires Soda Cloud (paid).</sub>

### Checks

| Check | Eliza | Soda | GX | Pandera | Cuallee |
|-------|:-----:|:----:|:--:|:-------:|:-------:|
| not_null | Yes | Yes | Yes | Yes | Yes |
| not_missing (custom) | Yes | Yes | Yes | - | - |
| unique | Yes | Yes | Yes | Yes | Yes |
| not_negative | Yes | Yes | Yes | Yes | Yes |
| between (range) | Yes | Yes | Yes | Yes | Yes |
| in_set | Yes | Yes | Yes | Yes | Yes |
| regex | Yes | Yes | Yes | Yes | Yes |
| is_email | Yes | - | - | - | - |
| is_url | Yes | - | - | - | - |
| min/max_length | Yes | Yes | Yes | - | - |
| freshness | Yes | Yes | - | - | - |
| row_count | Yes | Yes | Yes | - | - |
| cross_column | Yes | - | Yes | Yes | - |
| schema | Yes | Yes | Yes | Yes | - |
| reference (FK) | Yes | Yes | Yes | - | - |
| custom SQL | Yes | Yes | Yes | - | - |
| anomaly detection | - | Cloud | Yes | - | - |
| distribution | - | Cloud | Yes | - | - |
| change over time | - | Cloud | - | - | - |

### Warehouse Support

| Warehouse | Eliza | Soda | GX |
|-----------|:-----:|:----:|:--:|
| BigQuery | Yes | Yes | Yes |
| Athena | Yes | Yes | Yes |
| Snowflake | Yes | Yes | Yes |
| PostgreSQL | Yes | Yes | Yes |
| MySQL | Yes | Yes | Yes |
| ClickHouse | Yes | - | - |
| Databricks | Yes | Yes | Yes |
| Redshift | Yes | Yes | Yes |

```bash
pip install eliza-dq[bigquery]   # install only what you need
pip install eliza-dq[athena]
pip install eliza-dq[snowflake]
pip install eliza-dq[postgres]
pip install eliza-dq[clickhouse]
pip install eliza-dq[mysql]
pip install eliza-dq[databricks]
pip install eliza-dq[redshift]
```

**DWH (SQL pushdown)** - checks run as SQL queries directly on the warehouse:

```yaml
# eliza_checks/analytics.yaml
connection:
  type: bigquery
  project: my-project-123

table: my-project-123.analytics.orders

checks:
  - column: order_id
    check: not_null
```

**OLTP (local engine)** - data is pulled from the database, checked locally with Polars:

```yaml
# eliza_checks/prod_orders.yaml
connection:
  type: postgres
  host: prod-db.internal
  port: 5432
  user: readonly
  password: ${DB_PASSWORD}
  database: production

engine: local
table: orders
filter: "created_at >= '2024-01-01'"

checks:
  - column: order_id
    check: not_null
```

<details>
<summary>Connection examples for all warehouses</summary>

```yaml
# BigQuery
connection:
  type: bigquery
  project: my-project
  location: US    # optional

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

## Quick Start

### Inline checks (notebook / script)

```python
import polars as pl
from eliza import check

df = pl.read_parquet("orders.parquet")

result = check(df, checks={
    "order_id": ["not_null", "unique"],
    "amount":   ["not_null", "not_negative", {"between": {"min": 0, "max": 100000}}],
    "email":    ["is_email"],
    "status":   [{"in_set": {"values": ["pending", "shipped", "delivered"]}}],
    "name":     [{"min_length": {"min": 2}}, {"max_length": {"max": 100}}],
})

print(result.summary())
result.raise_on_fail()  # exit code 1 on failure
```

### YAML config (production)

```yaml
# eliza_checks/orders.yaml
connection:
  type: bigquery
  project: my-project-123

table: my-project-123.analytics.orders

filter: "created_at >= '2024-01-01'"

samples:
  limit: 20

checks:
  - column: order_id
    check: not_null
  - column: order_id
    check: unique
  - column: amount
    check: not_negative
  - column: email
    check: not_missing
    missing_values: ["", "N/A", "null"]
  - column: updated_at
    check: freshness
    max_age: 24h
  - check: row_count
    min: 1000
```

```python
from eliza import check
result = check(config="orders")
```

### CLI

```bash
# Initialize project
eliza init

# Auto-learn checks from data
eliza learn data/orders.parquet --name orders

# Run checks (exit code: 0=pass, 1=fail, 2=error)
eliza check --config orders --source data/orders.parquet

# JSON output for orchestrators
eliza check --config orders --format json
```

## Alerting & Reporting

```python
from eliza import check
from eliza.alert import send_slack
from eliza.report import generate_pdf

result = check(config="orders")

# Slack message + PDF attachment
send_slack(result, token="xoxb-...", channel="C...", pdf=True, name="orders")

# PDF report with charts (donut, failure bars, sample tables)
generate_pdf(result, name="orders")
# -> eliza_orders_2026-09-07.pdf
```

```bash
pip install eliza-dq[report]  # for PDF reports
```

<table>
<tr>
<td width="50%">

**Slack Alert**

<img src="docs/assets/slack_alert.png" width="100%" alt="Slack alert with check results and failed row samples">

</td>
<td width="50%">

**PDF Report**

<img src="docs/assets/pdf_report.png" width="100%" alt="PDF report with donut chart, check table, failure distribution, and sample rows">

</td>
</tr>
</table>

## CI/CD Integration

```yaml
# .github/workflows/dq.yml
- run: pip install eliza-dq
- run: eliza check --config orders --source data/orders.parquet
```

```python
# Airflow
@task
def dq_check():
    from eliza import check
    result = check(config="orders")
    result.raise_on_fail()
    return result.to_dict()
```

## Architecture

**Polars native** (DataFrames, files): Streaming engine with per-column grouping. Files are scanned as LazyFrames - data streams through without loading into RAM. Each column group runs one `collect(engine="streaming")` call. Failed row samples use `.filter().head(N).collect(engine="streaming")` - instant, no full materialization.

**SQL pushdown** (warehouses): All inline checks batched into one `SELECT COUNT(*), SUM(CASE WHEN ...) FROM table`. Separate checks (unique, freshness) and sample queries run in parallel via `ThreadPoolExecutor` with thread-local connections. Sample queries use `LIMIT N` in SQL - never fetches all failing rows.

## License

MIT
