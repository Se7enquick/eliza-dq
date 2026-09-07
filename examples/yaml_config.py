"""Run checks from a YAML config file."""

from eliza import check

# Reads eliza_checks/orders.yaml and runs checks.
# Source can be defined in YAML or passed here.
result = check(config="orders", source="data/orders.parquet")

print(result.summary())
print(result.to_json())
