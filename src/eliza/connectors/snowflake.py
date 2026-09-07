"""Snowflake connector — pip install eliza-dq[snowflake]"""

import threading


class SnowflakeConnector:
    dialect = "snowflake"

    def __init__(self, config):
        import snowflake.connector

        self._sf = snowflake.connector
        self._config = {
            "account": config["account"],
            "user": config.get("user"),
            "password": config.get("password"),
            "warehouse": config.get("warehouse"),
            "database": config.get("database"),
            "schema": config.get("schema"),
            "role": config.get("role"),
            "authenticator": config.get("authenticator"),
        }
        self._local = threading.local()

    def _get_conn(self):
        if not hasattr(self._local, "conn"):
            self._local.conn = self._sf.connect(**{k: v for k, v in self._config.items() if v is not None})
        return self._local.conn

    def execute(self, sql):
        cursor = self._get_conn().cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def close(self):
        if hasattr(self._local, "conn"):
            self._local.conn.close()
