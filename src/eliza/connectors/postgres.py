"""PostgreSQL connector — pip install eliza-dq[postgres]"""

import threading


class PostgresConnector:
    dialect = "postgres"

    def __init__(self, config):
        import psycopg2

        self._psycopg2 = psycopg2
        self._config = {
            "host": config.get("host", "localhost"),
            "port": config.get("port", 5432),
            "user": config.get("user"),
            "password": config.get("password"),
            "dbname": config.get("database"),
            "sslmode": config.get("sslmode", "prefer"),
        }
        self._local = threading.local()

    def _get_conn(self):
        if not hasattr(self._local, "conn"):
            self._local.conn = self._psycopg2.connect(**self._config)
            self._local.conn.autocommit = True
        return self._local.conn

    def execute(self, sql):
        cursor = self._get_conn().cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def close(self):
        if hasattr(self._local, "conn"):
            self._local.conn.close()
