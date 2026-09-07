"""Eliza — fastest open-source data quality engine."""

__version__ = "0.1.0"

from .runner import check
from .sql_runner import check_sql

__all__ = ["check", "check_sql"]
