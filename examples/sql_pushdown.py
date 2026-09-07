"""SQL pushdown: run checks directly on a warehouse without downloading data."""

from eliza import check

# Option 1: YAML config with connection block
# See eliza_checks/warehouse_example.yaml
result = check(config="warehouse_example")

# Option 2: Bring your own executor
from google.cloud import bigquery

client = bigquery.Client(project="my-project")


def run_sql(sql):
    return [dict(row) for row in client.query(sql).result()]


result = check(
    engine="sql",
    executor=run_sql,
    table="my-project.dataset.orders",
    dialect="bigquery",
    checks={
        "order_id": ["not_null", "unique"],
        "amount": ["not_negative"],
    },
    samples=True,
    samples_limit=10,
)

print(result.summary())
