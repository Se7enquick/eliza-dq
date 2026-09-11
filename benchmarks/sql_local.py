"""SQL pushdown benchmark: Eliza vs Soda Core on DuckDB.

No cloud credentials needed — runs locally with NYC Yellow Taxi data.
DuckDB is used as a local SQL engine to compare query strategies.

Usage:
    pip install eliza-dq soda-core-duckdb
    python benchmarks/sql_local.py
"""

import gc
import glob
import os
import sys
import time
import urllib.request

import yaml

PARQUET_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{year}-{month:02d}.parquet"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

COLUMNS = [
    "fare_amount",
    "total_amount",
    "tip_amount",
    "trip_distance",
    "passenger_count",
    "payment_type",
    "VendorID",
    "store_and_fwd_flag",
]


def download(year_months):
    os.makedirs(DATA_DIR, exist_ok=True)
    paths = []
    for year, month in year_months:
        path = os.path.join(DATA_DIR, f"yellow_tripdata_{year}-{month:02d}.parquet")
        if not os.path.exists(path):
            url = PARQUET_URL.format(year=year, month=month)
            print(f"  Downloading {year}-{month:02d}...", end=" ", flush=True)
            try:
                urllib.request.urlretrieve(url, path)
                print("done")
            except Exception:
                print("skip")
                continue
        paths.append(path)
    return paths


def measure(fn, runs=3):
    fn()
    gc.collect()
    times = []
    for _ in range(runs):
        gc.collect()
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return min(times)


def fmt(ms):
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def main():
    import duckdb

    from eliza.sql_runner import check_sql

    try:
        from soda.scan import Scan

        has_soda = True
    except ImportError:
        has_soda = False

    print("Eliza DQ SQL Pushdown Benchmark (DuckDB)")
    print(f"Python {sys.version.split()[0]}")
    print(f"Libraries: eliza=yes, soda-core={has_soda}")
    print()

    year_months = [(2024, m) for m in range(1, 13)]
    print(f"Downloading NYC Yellow Taxi ({len(year_months)} files)...")
    paths = download(year_months)

    eliza_checks = [{"column": c, "check": "not_null"} for c in COLUMNS]

    cols = ["Eliza"]
    if has_soda:
        cols.append("Soda Core")
        cols.append("Ratio")

    header = f"{'Rows':>12} | " + " | ".join(f"{c:>10}" for c in cols)
    print()
    print("8 not_null checks + failed row samples. Warmup + 3 runs, min time.")
    print(header)
    print("-" * len(header))

    for i, n_files in enumerate([1, 3, 6, 12]):
        db_path = f"/tmp/eliza_bench_{i}.duckdb"
        for f in glob.glob(db_path + "*"):
            try:
                os.remove(f)
            except OSError:
                pass

        files = paths[:n_files]
        conn = duckdb.connect(db_path)
        file_list = ",".join(f"'{f}'" for f in files)
        conn.execute(f"CREATE TABLE taxi AS SELECT * FROM read_parquet([{file_list}])")
        rows = conn.execute("SELECT COUNT(*) FROM taxi").fetchone()[0]
        conn.close()

        def run_eliza(p=db_path):
            c = duckdb.connect(p)

            def executor(sql):
                cur = c.cursor()
                cur.execute(sql)
                columns = [d[0] for d in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

            result = check_sql(
                executor,
                checks_list=eliza_checks,
                table="taxi",
                dialect="postgres",
                samples=True,
                samples_limit=10,
            )
            c.close()
            return result

        parts = [f"{rows:>12,} | {fmt(measure(run_eliza)):>10}"]

        if has_soda:
            cfg = yaml.dump({"data_source bench": {"type": "duckdb", "path": db_path}})
            soda_checks = "checks for taxi:\n" + "".join(f"  - missing_count({c}) = 0\n" for c in COLUMNS)

            def run_soda(c=cfg, sc=soda_checks):
                scan = Scan()
                scan.set_data_source_name("bench")
                scan.add_configuration_yaml_str(c)
                scan.add_sodacl_yaml_str(sc)
                scan.execute()
                return scan

            e = measure(run_eliza)
            s = measure(run_soda)
            parts = [f"{rows:>12,} | {fmt(e):>10} | {fmt(s):>10} | {s / e:>9.1f}x"]

        print(" | ".join(parts) if len(parts) > 1 else parts[0])

    for i in range(4):
        for f in glob.glob(f"/tmp/eliza_bench_{i}.duckdb*"):
            try:
                os.remove(f)
            except OSError:
                pass

    print()
    print("DuckDB runs in-process — no network overhead, pure SQL engine comparison.")
    if has_soda:
        print("Both tools batch checks into a single SELECT. Eliza collects samples in parallel.")
    else:
        print("Install soda-core-duckdb for comparison: pip install soda-core-duckdb")


if __name__ == "__main__":
    main()
