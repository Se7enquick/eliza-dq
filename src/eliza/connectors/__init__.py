"""Built-in warehouse connectors for SQL pushdown.

Each connector is an optional dependency:
    pip install eliza-dq[bigquery]
    pip install eliza-dq[athena]
    pip install eliza-dq[snowflake]
    pip install eliza-dq[clickhouse]
    pip install eliza-dq[postgres]
    pip install eliza-dq[mysql]
    pip install eliza-dq[databricks]
    pip install eliza-dq[redshift]
"""

_REGISTRY = {
    "bigquery": (".bigquery", "BigQueryConnector"),
    "athena": (".athena", "AthenaConnector"),
    "snowflake": (".snowflake", "SnowflakeConnector"),
    "clickhouse": (".clickhouse", "ClickHouseConnector"),
    "postgres": (".postgres", "PostgresConnector"),
    "postgresql": (".postgres", "PostgresConnector"),
    "mysql": (".mysql", "MySQLConnector"),
    "databricks": (".databricks", "DatabricksConnector"),
    "redshift": (".redshift", "RedshiftConnector"),
}

_INSTALL_HINTS = {
    "bigquery": "pip install eliza-dq[bigquery]",
    "athena": "pip install eliza-dq[athena]",
    "snowflake": "pip install eliza-dq[snowflake]",
    "clickhouse": "pip install eliza-dq[clickhouse]",
    "postgres": "pip install eliza-dq[postgres]",
    "postgresql": "pip install eliza-dq[postgres]",
    "mysql": "pip install eliza-dq[mysql]",
    "databricks": "pip install eliza-dq[databricks]",
    "redshift": "pip install eliza-dq[redshift]",
}


def create_connector(config):
    """Create a connector from YAML connection config.

    Args:
        config: dict with 'type' key and connection params.

    Returns:
        Connector instance with .execute(sql) and .dialect attributes.
    """
    conn_type = config.get("type", "").lower()
    if conn_type not in _REGISTRY:
        supported = ", ".join(sorted(set(k for k in _REGISTRY if k != "postgresql")))
        raise ValueError(f"Unknown connection type: {conn_type!r}. Supported: {supported}")

    module_path, class_name = _REGISTRY[conn_type]
    try:
        import importlib

        mod = importlib.import_module(module_path, package="eliza.connectors")
        cls = getattr(mod, class_name)
    except ImportError as e:
        hint = _INSTALL_HINTS.get(conn_type, f"pip install eliza-dq[{conn_type}]")
        raise ImportError(f"{conn_type} connector requires additional dependencies: {hint}") from e

    return cls(config)
