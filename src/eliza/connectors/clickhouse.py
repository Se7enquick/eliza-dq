"""ClickHouse connector — pip install eliza-dq[clickhouse]"""

import threading


class ClickHouseConnector:
    dialect = "clickhouse"

    def __init__(self, config):
        import clickhouse_connect

        self._cc = clickhouse_connect
        self._config = {
            "host": config.get("host", "localhost"),
            "port": config.get("port", 8123),
            "username": config.get("user", "default"),
            "password": config.get("password", ""),
            "database": config.get("database", "default"),
            "secure": config.get("secure", False),
        }
        self._local = threading.local()

    def _get_client(self):
        if not hasattr(self._local, "client"):
            self._local.client = self._cc.get_client(**self._config)
        return self._local.client

    def execute(self, sql):
        result = self._get_client().query(sql)
        columns = result.column_names
        return [dict(zip(columns, row)) for row in result.result_rows]

    def close(self):
        if hasattr(self._local, "client"):
            self._local.client.close()
