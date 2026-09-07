"""Eliza CLI — data quality checks from command line."""

import argparse
import sys

from .runner import check


def main():
    parser = argparse.ArgumentParser(
        prog="eliza",
        description="Fastest open-source data quality engine.",
    )
    sub = parser.add_subparsers(dest="command")

    # eliza check
    check_parser = sub.add_parser("check", help="Run data quality checks")
    check_parser.add_argument("--config", required=True, help="Config name (YAML in eliza_checks/)")
    check_parser.add_argument("--source", help="Override source (file path)")
    check_parser.add_argument("--no-samples", action="store_true", help="Skip sample collection")
    check_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    # eliza init
    sub.add_parser("init", help="Create eliza_checks/ with example")

    # eliza learn
    learn_parser = sub.add_parser("learn", help="Auto-generate checks from data")
    learn_parser.add_argument("source", help="Data file to profile (parquet, csv, etc.)")
    learn_parser.add_argument("--name", help="Config name (default: filename)")

    args = parser.parse_args()

    if args.command == "check":
        _run_check(args)
    elif args.command == "init":
        _run_init()
    elif args.command == "learn":
        _run_learn(args)
    else:
        parser.print_help()


def _run_check(args):
    source = args.source if args.source else None
    result = check(
        source=source,
        config=args.config,
        samples=not args.no_samples,
    )

    if args.format == "json":
        print(result.to_json())
    else:
        print(result.summary())
        print()
        for c in result.checks:
            icon = "✓" if c.status == "pass" else "⚠" if c.status == "warn" else "✗"
            rate = f"{c.fail_rate:.2%}" if c.fail_count > 0 else ""
            print(f"  {icon} {c.column or ''}:{c.name:15s} {c.fail_count:>10,} {rate}")

        if result.samples:
            print("\nFailed samples:")
            for name, sdf in result.samples.items():
                rows = sdf.head(3).iter_rows(named=True) if hasattr(sdf, "head") else sdf[:3]
                rows_list = list(rows)
                print(f"\n  {name} ({len(rows_list)} rows):")
                for row in rows_list:
                    compact = {k: str(v)[:30] for k, v in row.items() if v is not None}
                    print(f"    {compact}")

    sys.exit(result.exit_code)


def _run_init():
    from pathlib import Path

    checks_dir = Path.cwd() / "eliza_checks"
    checks_dir.mkdir(exist_ok=True)

    example = checks_dir / "example.yaml"
    if not example.exists():
        example.write_text(
            "checks:\n"
            "  - column: id\n"
            "    check: not_null\n"
            "  - column: id\n"
            "    check: unique\n"
            "  - column: amount\n"
            "    check: not_negative\n"
        )
        print(f"Created {checks_dir}/")
        print(f"Created {example}")
        print("\nRun: eliza check --config example --source data.parquet")
    else:
        print(f"{example} already exists")


def _run_learn(args):
    from .learn import learn

    result = learn(args.source, name=args.name)
    if isinstance(result, tuple):
        config, path = result
        print(f"Learned {len(config['checks'])} checks from {args.source}")
        print(f"Written to: {path}")
        print()
        for c in config["checks"]:
            col = c.get("column", "")
            check_name = c["check"]
            extras = {k: v for k, v in c.items() if k not in ("column", "check")}
            extra_str = f" {extras}" if extras else ""
            print(f"  {col}:{check_name}{extra_str}")


if __name__ == "__main__":
    main()
