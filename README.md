<div align="center">

# Eliza DQ

**The fastest open-source data quality engine for Python.**

*259M rows. 17 checks. Samples. 1.5 seconds.*

[![CI](https://github.com/Se7enquick/eliza/actions/workflows/ci.yml/badge.svg)](https://github.com/Se7enquick/eliza/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://pypi.org/project/eliza-dq/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

---

Eliza DQ validates DataFrames and warehouse tables with streaming execution, parallel SQL pushdown, and instant failure sampling. It runs on Polars, connects to 8 warehouses, and ships with 2 dependencies.

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

## Why Eliza?

| | Eliza | Soda | GX | Pandera | Cuallee |
|---|---|---|---|---|---|
| **126M rows** | **40ms** | SQL only | 4,400ms | 118ms | 89ms |
| **259M rows** | **1.5s** | SQL only | OOM | OOM | OOM |
| Streaming from disk | Yes | No | No | No | No |
| Parallel SQL | Yes | No | No | No | No |
| Sample failed rows | `LIMIT N` | Fetches ALL | No | No | No |
| Polars native | Yes | No | No | Yes | Yes |
| SQL pushdown | 8 warehouses | Yes | Yes | No | No |
| YAML + inline API | Both | YAML only | Code only | Code only | Code only |
| Core dependencies | **2** | 30+ | 30+ | 7+ | 3+ |

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

## Checks

| Check | Description | Polars | SQL |
|-------|-------------|--------|-----|
| `not_null` | No NULL values | Yes | Yes |
| `not_missing` | No NULLs or custom missing values ("", "N/A", etc.) | Yes | Yes |
| `unique` | All values unique | Yes | Yes |
| `not_negative` | No values < 0 | Yes | Yes |
| `between` | Values within min/max range | Yes | Yes |
| `in_set` | Values in allowed set | Yes | Yes |
| `regex` | Values match regex pattern | Yes | Yes |
| `is_email` | Valid email format | Yes | Yes |
| `is_url` | Valid URL format | Yes | Yes |
| `min_length` | String min length | Yes | Yes |
| `max_length` | String max length | Yes | Yes |
| `freshness` | Column not older than threshold | Yes | Yes |
| `row_count` | Row count within range | Yes | Yes |
| `cross_column` | Column A > Column B | Yes | Yes |
| `schema` | Validate column names and types | Yes | - |
| `reference` | FK integrity across tables/files | Yes | Yes |
| `custom_sql` | Custom SQL expression | - | Yes |

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

Each connector auto-detects dialect and runs queries in parallel:

```yaml
# eliza_checks/athena_orders.yaml
connection:
  type: athena
  region: us-east-1
  schema: production
  s3_staging_dir: s3://my-bucket/athena-results/

table: production.orders

checks:
  - column: id
    check: not_null
```

```python
result = check(config="athena_orders")
```

Or bring your own executor:

```python
result = check(
    config="orders",
    engine="sql",
    executor=my_query_fn,
    table="schema.orders",
    dialect="postgres",
)
```

## Alerting & Reporting

```python
from eliza import check
from eliza.alert import send_slack
from eliza.report import generate_pdf

result = check(config="orders")

# Slack message + PDF attachment
send_slack(result, token="xoxb-...", channel="C...", pdf=True, name="orders")

# PDF report with charts
generate_pdf(result, name="orders")
# -> eliza_orders_2026-09-07.pdf
```

```bash
pip install eliza-dq[report]  # for PDF reports
```

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

Eliza uses two execution strategies depending on the source:

**Polars native** (DataFrames, files): Streaming engine with per-column grouping. Each column group runs one `collect(engine="streaming")` call. Samples use `.filter().head(N).collect(engine="streaming")` for instant results without materializing all failures.

**SQL pushdown** (warehouses): All inline checks batched into one `SELECT COUNT(*), SUM(CASE WHEN ...) FROM table`. Separate checks (unique, freshness) and sample queries run in parallel via `ThreadPoolExecutor` with thread-local connections.

## License

MIT
