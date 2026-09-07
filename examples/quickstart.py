"""Quickstart: validate a DataFrame in 3 lines."""

import polars as pl

from eliza import check

df = pl.DataFrame(
    {
        "id": [1, 2, 3, 4, 5],
        "amount": [10.0, -5.0, 20.0, 0.0, 100.0],
        "email": ["alice@test.com", "bad", "bob@test.io", "carol@x.org", "nope"],
        "status": ["ok", "ok", "bad", "ok", "ok"],
    }
)

result = check(
    df,
    checks={
        "id": ["not_null", "unique"],
        "amount": ["not_null", "not_negative"],
        "email": ["is_email"],
        "status": [{"in_set": {"values": ["ok", "pending"]}}],
    },
)

print(result.summary())
for c in result.checks:
    icon = "PASS" if c.status == "pass" else "FAIL"
    print(f"  [{icon}] {c.column}:{c.name} — {c.fail_count} failures")

# Exit code: 0=pass, 1=fail, 2=error
print(f"\nExit code: {result.exit_code}")
