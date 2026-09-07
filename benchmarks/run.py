"""Reproduce Eliza DQ benchmarks.

Downloads NYC Yellow Taxi data and runs identical checks across all libraries.
Results are printed as a table you can paste into a GitHub issue or README.

Usage:
    pip install eliza-dq cuallee pandera great_expectations
    python benchmarks/run.py

Optional (file streaming benchmarks need more data):
    python benchmarks/run.py --full
"""

import argparse
import gc
import glob
import os
import sys
import time
import urllib.request

import polars as pl


PARQUET_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-{month:02d}.parquet"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def download(months):
    os.makedirs(DATA_DIR, exist_ok=True)
    paths = []
    for m in months:
        path = os.path.join(DATA_DIR, f"yellow_tripdata_2024-{m:02d}.parquet")
        if not os.path.exists(path):
            url = PARQUET_URL.format(month=m)
            print(f"  Downloading 2024-{m:02d}...", end=" ", flush=True)
            urllib.request.urlretrieve(url, path)
            print("done")
        paths.append(path)
    return paths


def measure(fn, runs=3):
    try:
        fn()
    except Exception:
        pass
    gc.collect()
    times = []
    for _ in range(runs):
        gc.collect()
        t0 = time.perf_counter()
        try:
            fn()
        except Exception:
            pass
        times.append((time.perf_counter() - t0) * 1000)
    return min(times)


# -- Check functions (5 identical checks) ------------------------------------

def run_eliza(df):
    from eliza import check
    return check(df, checks={
        "fare_amount": ["not_null", "not_negative"],
        "total_amount": ["not_negative"],
        "tip_amount": ["not_negative"],
        "trip_distance": ["not_negative"],
    }, samples=False)


def run_cuallee(df):
    from cuallee import Check, CheckLevel
    c = Check(CheckLevel.WARNING, "b")
    c.is_complete("fare_amount")
    c.is_greater_or_equal_than("fare_amount", 0)
    c.is_greater_or_equal_than("total_amount", 0)
    c.is_greater_or_equal_than("tip_amount", 0)
    c.is_greater_or_equal_than("trip_distance", 0)
    return c.validate(df)


def run_pandera(df):
    import pandera.polars as pa
    schema = pa.DataFrameSchema({
        "fare_amount": pa.Column(nullable=False, checks=[pa.Check.ge(0)]),
        "total_amount": pa.Column(checks=[pa.Check.ge(0)]),
        "tip_amount": pa.Column(checks=[pa.Check.ge(0)]),
        "trip_distance": pa.Column(checks=[pa.Check.ge(0)]),
    })
    try:
        return schema.validate(df)
    except Exception:
        return None


def run_gx(pdf):
    import great_expectations as gx
    n = f"t{int(time.time() * 1000)}"
    context = gx.get_context()
    ds = context.data_sources.add_pandas(n)
    da = ds.add_dataframe_asset(f"{n}_d")
    batch = da.add_batch_definition_whole_dataframe(f"{n}_b").get_batch(
        batch_parameters={"dataframe": pdf}
    )
    suite = gx.ExpectationSuite(name=f"{n}_s")
    suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="fare_amount"))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToBeBetween(column="fare_amount", min_value=0))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToBeBetween(column="total_amount", min_value=0))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToBeBetween(column="tip_amount", min_value=0))
    suite.add_expectation(gx.expectations.ExpectColumnValuesToBeBetween(column="trip_distance", min_value=0))
    return batch.validate(suite)


def run_eliza_files(files):
    from eliza import check
    return check(files, checks={
        "fare_amount": ["not_null", "not_negative"],
        "total_amount": ["not_negative"],
        "tip_amount": ["not_negative"],
        "trip_distance": ["not_negative"],
    }, samples=True, samples_limit=10,
    extra_columns="ignore", missing_columns="insert")


def try_import(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def fmt(ms):
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


# -- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Eliza DQ benchmark")
    parser.add_argument("--full", action="store_true", help="Download all 12 months for streaming benchmarks")
    args = parser.parse_args()

    has_cuallee = try_import("cuallee")
    has_pandera = try_import("pandera")
    has_gx = try_import("great_expectations")

    print("Eliza DQ Benchmark")
    print(f"Python {sys.version.split()[0]}, Polars {pl.__version__}")
    print(f"Libraries: eliza=yes, cuallee={has_cuallee}, pandera={has_pandera}, gx={has_gx}")
    print()

    months = list(range(1, 13)) if args.full else [1, 2, 3]
    print(f"Downloading NYC Yellow Taxi 2024 ({len(months)} months)...")
    paths = download(months)

    # -- In-memory benchmark --------------------------------------------------
    print()
    print("=" * 70)
    print("  IN-MEMORY DataFrame (pre-loaded Polars DataFrame)")
    print("  5 checks, warmup + 3 runs, min time")
    print("=" * 70)

    header = f"{'Rows':>12} | {'Eliza':>10}"
    if has_cuallee:
        header += f" | {'Cuallee':>10}"
    if has_pandera:
        header += f" | {'Pandera':>10}"
    if has_gx:
        header += f" | {'GX':>10}"
    print(header)
    print("-" * len(header))

    scales = [("3M", [paths[0]])]
    if len(paths) >= 3:
        scales.append(("10M", paths[:3]))
    if len(paths) >= 12:
        scales.append(("41M", paths))

    for label, files in scales:
        dfs = [
            pl.read_parquet(f).cast(
                {"tpep_pickup_datetime": pl.Datetime("us"), "tpep_dropoff_datetime": pl.Datetime("us")},
                strict=False,
            )
            for f in files
        ]
        df = pl.concat(dfs, how="diagonal_relaxed") if len(dfs) > 1 else dfs[0]
        del dfs
        rows = len(df)

        row = f"{rows:>12,} | {fmt(measure(lambda: run_eliza(df))):>10}"
        if has_cuallee:
            row += f" | {fmt(measure(lambda: run_cuallee(df))):>10}"
        if has_pandera:
            row += f" | {fmt(measure(lambda: run_pandera(df))):>10}"
        if has_gx and rows <= 5_000_000:
            pdf = df.to_pandas()
            row += f" | {fmt(measure(lambda: run_gx(pdf))):>10}"
            del pdf
        elif has_gx:
            row += f" |    pandas*"
        print(row)
        del df
        gc.collect()

    if has_gx:
        print("* GX requires pandas conversion (adds seconds of overhead)")

    # -- File streaming benchmark ---------------------------------------------
    if len(paths) >= 3:
        print()
        print("=" * 70)
        print("  FILE STREAMING (from disk, total wall time)")
        print("  Eliza streams via LazyFrame. Others load all into RAM first.")
        print("=" * 70)

        header = f"{'Files':>12} | {'Eliza':>10}"
        if has_cuallee:
            header += f" | {'Cuallee':>10}"
        print(header)
        print("-" * len(header))

        stream_scales = [("3 files", paths[:3])]
        if len(paths) >= 12:
            stream_scales.append(("12 files", paths))

        for label, files in stream_scales:
            eliza_ms = measure(lambda: run_eliza_files(files))
            row = f"{label:>12} | {fmt(eliza_ms):>10}"

            if has_cuallee:
                def cuallee_from_files():
                    dfs = [
                        pl.read_parquet(f).cast(
                            {"tpep_pickup_datetime": pl.Datetime("us"), "tpep_dropoff_datetime": pl.Datetime("us")},
                            strict=False,
                        )
                        for f in files
                    ]
                    df = pl.concat(dfs, how="diagonal_relaxed")
                    run_cuallee(df)

                row += f" | {fmt(measure(cuallee_from_files)):>10}"
            print(row)

    print()
    print("Done. Run with --full for 12-month (41M row) benchmarks.")


if __name__ == "__main__":
    main()
