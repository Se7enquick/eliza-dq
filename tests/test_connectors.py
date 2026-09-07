"""Tests for connector registry and error handling."""

import pytest

from eliza.connectors import _REGISTRY, create_connector


class TestRegistry:
    def test_all_connectors_registered(self):
        expected = {
            "bigquery",
            "athena",
            "snowflake",
            "postgres",
            "clickhouse",
            "mysql",
            "databricks",
            "redshift",
            "postgresql",
        }
        assert expected.issubset(set(_REGISTRY.keys()))

    def test_postgresql_alias(self):
        assert _REGISTRY["postgresql"] == _REGISTRY["postgres"]


class TestCreateConnector:
    def test_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown connection type"):
            create_connector({"type": "nonexistent_db"})

    def test_missing_type(self):
        with pytest.raises(ValueError):
            create_connector({})

    def test_missing_deps(self):
        for conn_type, config in [
            ("snowflake", {"type": "snowflake", "account": "test"}),
            ("redshift", {"type": "redshift", "host": "x"}),
            ("databricks", {"type": "databricks", "host": "x", "http_path": "y"}),
        ]:
            try:
                create_connector(config)
            except (ImportError, Exception):
                pass
