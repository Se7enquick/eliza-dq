"""
Demo: генерує тестовий датасет і прогоняє Eliza checks.
"""

import polars as pl
import random
import string
from pathlib import Path

from eliza_mini import check

# --- Генеруємо тестовий датасет ---
N = 2_000_000  # 2М рядків

random.seed(42)

order_ids = list(range(1, N + 1))
order_ids[999_999] = order_ids[0]  # один дублікат

amounts = [round(random.uniform(-10, 500), 2) for _ in range(N)]  # деякі від'ємні

emails = []
for i in range(N):
    if i % 100 == 0:
        emails.append("not-an-email")  # кожен 100-й — невалідний
    else:
        name = "".join(random.choices(string.ascii_lowercase, k=6))
        emails.append(f"{name}@example.com")

statuses = []
for i in range(N):
    if i % 5000 == 0:
        statuses.append("unknown")  # кожен 5000-й — невалідний статус
    else:
        statuses.append(random.choice(["pending", "shipped", "delivered", "cancelled"]))

df = pl.DataFrame({
    "order_id": order_ids,
    "amount": amounts,
    "email": emails,
    "status": statuses,
})

# Зберігаємо як parquet
parquet_path = Path(__file__).parent / "orders_sample.parquet"
df.write_parquet(parquet_path)
print(f"Generated {N:,} rows → {parquet_path}")
print(f"File size: {parquet_path.stat().st_size / 1024 / 1024:.1f} MB")
print()

# --- Спосіб 1: source з YAML ---
print("=== Check з YAML source ===")
result = check(config="orders")
print(result.summary())
for c in result.checks:
    icon = "✓" if c.passed else ("⚠" if c.status == "warn" else "✗")
    print(f"  {icon} {c.column}:{c.name} — {c.fail_count} failures [{c.severity}]")
print()

# --- Спосіб 2: передати DataFrame ---
print("=== Check з DataFrame ===")
result2 = check(df, config="orders")
print(result2.summary())
print()

# --- Спосіб 3: передати LazyFrame (zero-copy) ---
print("=== Check з LazyFrame (scan_parquet) ===")
lf = pl.scan_parquet(parquet_path)
result3 = check(lf, config="orders")
print(result3.summary())
print()

# --- Спосіб 4: raise on fail ---
print("=== raise_on_fail() ===")
try:
    result.raise_on_fail()
except RuntimeError as e:
    print(f"Caught: {e}")
print()

# --- JSON output (для Airflow XCom, logging, etc) ---
print("=== JSON output ===")
import json
print(json.dumps(result.to_dict(), indent=2))

# Cleanup
parquet_path.unlink()
