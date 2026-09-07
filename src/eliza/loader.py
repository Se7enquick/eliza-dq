"""Load check configuration from YAML files or inline dicts."""

import os
from pathlib import Path

import yaml


def load_config(name, config_path=None):
    """Load YAML config by name from eliza_checks/ directory."""
    if config_path is None:
        config_path = Path.cwd() / "eliza_checks"

    path = Path(config_path) / f"{name}.yaml"

    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    raw = path.read_text()

    # Substitute ${ENV_VAR} with values from environment
    for key, val in os.environ.items():
        raw = raw.replace(f"${{{key}}}", val)

    return yaml.safe_load(raw)


def parse_inline_checks(checks_dict):
    """Convert inline dict to list of check configs.

    Input:
        {"amount": ["not_null", "not_negative", {"between": {"min": 0}}]}

    Output:
        [
            {"column": "amount", "check": "not_null"},
            {"column": "amount", "check": "not_negative"},
            {"column": "amount", "check": "between", "min": 0},
        ]
    """
    result = []
    for column, checks in checks_dict.items():
        for check in checks:
            if isinstance(check, str):
                # "not_null" → {"column": "amount", "check": "not_null"}
                result.append({"column": column, "check": check})
            elif isinstance(check, dict):
                # {"between": {"min": 0}} → {"column": "amount", "check": "between", "min": 0}
                for check_name, params in check.items():
                    entry = {"column": column, "check": check_name}
                    if isinstance(params, dict):
                        entry.update(params)
                    elif isinstance(params, list):
                        entry["values"] = params
                    elif isinstance(params, str):
                        entry["pattern"] = params
                    else:
                        entry["value"] = params
                    result.append(entry)
    return result
