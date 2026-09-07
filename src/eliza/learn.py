"""Auto-generate check config from data profiling."""

from pathlib import Path

import polars as pl
import yaml

from .compat import resolve_source

EMAIL_PATTERN = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$"
URL_PATTERN = r"^https?://[^\s]+$"


def learn(source, name=None, output_path=None):
    """Scan data and generate YAML checks config.

    Usage:
        learn("data.parquet")                    # creates eliza_checks/data.yaml
        learn(df, name="orders")                 # creates eliza_checks/orders.yaml
        config = learn(df, output_path=False)    # returns dict, no file
    """
    lf = resolve_source(source)
    schema = lf.collect_schema()

    # Collect stats in one scan
    stat_exprs = [pl.len().alias("__rows__")]
    for col_name in schema:
        stat_exprs.append(pl.col(col_name).null_count().alias(f"_null_{col_name}"))
        stat_exprs.append(pl.col(col_name).n_unique().alias(f"_nuniq_{col_name}"))
        if schema[col_name].is_numeric():
            stat_exprs.append(pl.col(col_name).min().alias(f"_min_{col_name}"))
            stat_exprs.append(pl.col(col_name).max().alias(f"_max_{col_name}"))

    stats = lf.select(stat_exprs).collect(engine="streaming").row(0, named=True)
    total = stats["__rows__"]

    # Check string columns for patterns (sample 1000 for speed)
    sample = lf.head(1000).collect()
    string_patterns = {}
    for col_name in schema:
        if schema[col_name] == pl.String:
            col_data = sample[col_name].drop_nulls()
            if len(col_data) > 0:
                email_match = col_data.str.contains(EMAIL_PATTERN).mean()
                url_match = col_data.str.contains(URL_PATTERN).mean()
                if email_match > 0.9:
                    string_patterns[col_name] = "is_email"
                elif url_match > 0.9:
                    string_patterns[col_name] = "is_url"

    # Generate checks
    checks = []
    for col_name in schema:
        null_count = stats[f"_null_{col_name}"]
        n_unique = stats[f"_nuniq_{col_name}"]

        # not_null: suggest if 0% nulls
        if null_count == 0:
            checks.append({"column": col_name, "check": "not_null"})

        # unique: suggest if all values unique and column looks like ID
        if n_unique == total and null_count == 0:
            checks.append({"column": col_name, "check": "unique"})

        # not_negative: suggest if numeric and min >= 0
        if schema[col_name].is_numeric():
            min_key = f"_min_{col_name}"
            max_key = f"_max_{col_name}"
            if min_key in stats and stats[min_key] is not None:
                min_val = stats[min_key]
                max_val = stats[max_key]
                if min_val >= 0:
                    checks.append({"column": col_name, "check": "not_negative"})
                # between: suggest range with 10% buffer
                buffer = (max_val - min_val) * 0.1 if max_val != min_val else abs(max_val) * 0.1 or 1
                checks.append(
                    {
                        "column": col_name,
                        "check": "between",
                        "min": round(float(min_val - buffer), 2),
                        "max": round(float(max_val + buffer), 2),
                    }
                )

        # in_set: suggest if low cardinality (< 20 unique values)
        if n_unique <= 20 and n_unique > 0 and schema[col_name] in (pl.String, pl.Categorical):
            values = lf.select(pl.col(col_name).drop_nulls().unique()).collect()[col_name].to_list()
            checks.append({"column": col_name, "check": "in_set", "values": sorted(values)})

        # Semantic: is_email / is_url
        if col_name in string_patterns:
            checks.append({"column": col_name, "check": string_patterns[col_name]})

    config = {"checks": checks}

    # Output
    if output_path is False:
        return config

    if output_path is None:
        output_path = Path.cwd() / "eliza_checks"
    output_path = Path(output_path)
    output_path.mkdir(exist_ok=True)

    if name is None:
        if isinstance(source, (str, Path)):
            name = Path(str(source)).stem
        else:
            name = "learned"

    yaml_path = output_path / f"{name}.yaml"
    yaml_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))

    return config, yaml_path
