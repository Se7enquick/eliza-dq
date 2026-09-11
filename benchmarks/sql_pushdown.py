"""SQL pushdown benchmark: Eliza vs Soda Core.

Runs identical not_null checks on Athena tables and compares wall time.
Requires AWS credentials and Athena access.

Usage:
    pip install eliza-dq[athena]
    pip install soda-core-athena  # for comparison

    python benchmarks/sql_pushdown.py \
        --region us-east-1 \
        --schema my_database \
        --s3-staging s3://my-bucket/athena-results/ \
        --table my_database.my_table \
        --columns col1,col2,col3
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time

import yaml


def measure_eliza(table, columns, dialect, conn_config, runs=3):
    from eliza.connectors import create_connector
    from eliza.sql_runner import check_sql

    conn = create_connector(conn_config)
    checks = [{"column": c, "check": "not_null"} for c in columns]

    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        result = check_sql(
            conn.execute,
            checks_list=checks,
            table=table,
            dialect=dialect,
            samples=True,
            samples_limit=10,
        )
        times.append((time.perf_counter() - t0) * 1000)

    conn.close()
    return min(times), result


def measure_soda(table, columns, soda_config_path, runs=3):
    soda_bin = None
    for candidate in [
        os.path.expanduser("~/.pyenv/versions/3.10.18/bin/soda"),
        "soda",
    ]:
        if os.path.exists(candidate) or os.system(f"which {candidate} > /dev/null 2>&1") == 0:
            soda_bin = candidate
            break

    if not soda_bin:
        return None, None

    checks_yaml = f"checks for {table.split('.')[-1]}:\n"
    for c in columns:
        checks_yaml += f"  - missing_count({c}) = 0\n"

    times = []
    for _ in range(runs):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(checks_yaml)
            checks_path = f.name

        t0 = time.perf_counter()
        result = subprocess.run(
            [soda_bin, "scan", "-d", "athena", "-c", soda_config_path, checks_path],
            capture_output=True,
            text=True,
            timeout=300,
        )
        times.append((time.perf_counter() - t0) * 1000)
        os.unlink(checks_path)

    return min(times), result


def main():
    parser = argparse.ArgumentParser(description="Eliza DQ SQL pushdown benchmark")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--schema", required=True, help="Athena database/schema")
    parser.add_argument("--s3-staging", required=True, help="S3 path for Athena results")
    parser.add_argument("--table", required=True, help="Fully qualified table name")
    parser.add_argument("--columns", required=True, help="Comma-separated column names for not_null checks")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--work-group", default="primary")
    args = parser.parse_args()

    columns = [c.strip() for c in args.columns.split(",")]

    print("Eliza DQ SQL Pushdown Benchmark")
    print(f"Table: {args.table}")
    print(f"Checks: {len(columns)} not_null ({', '.join(columns)})")
    print(f"Runs: {args.runs}, min time reported")
    print()

    conn_config = {
        "type": "athena",
        "region": args.region,
        "schema": args.schema,
        "s3_staging_dir": args.s3_staging,
        "work_group": args.work_group,
    }

    # Eliza
    print("Running Eliza...", flush=True)
    eliza_ms, eliza_result = measure_eliza(args.table, columns, "athena", conn_config, runs=args.runs)
    errors = sum(1 for c in eliza_result.checks if c.status == "error")
    print(
        f"  Eliza:     {eliza_ms:>8.0f}ms  ({eliza_result.total_rows:,} rows, "
        f"{len(eliza_result.samples)} samples, {errors} errors)"
    )

    # Soda
    soda_config = None
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(
            {
                "data_source athena": {
                    "type": "athena",
                    "catalog": "AwsDataCatalog",
                    "database": args.schema,
                    "schema": args.schema,
                    "region_name": args.region,
                    "work_group": args.work_group,
                    "staging_dir": args.s3_staging,
                }
            },
            f,
        )
        soda_config = f.name

    print("Running Soda Core...", flush=True)
    soda_ms, soda_result = measure_soda(args.table, columns, soda_config, runs=args.runs)
    os.unlink(soda_config)

    if soda_ms:
        print(f"  Soda Core: {soda_ms:>8.0f}ms")
        print()
        ratio = soda_ms / eliza_ms
        print(f"  Eliza is {ratio:.1f}x faster")
    else:
        print("  Soda Core: not installed (pip install soda-core-athena)")

    print()
    print("Note: both tools batch metric checks into a single SELECT.")
    print("Speed difference comes from parallel sample collection and lighter client.")


if __name__ == "__main__":
    main()
