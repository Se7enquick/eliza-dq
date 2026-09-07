"""MySQL connector — pip install eliza-dq[mysql]"""

import threading


class MySQLConnector:
    dialect = "mysql"

    def __init__(self, config):
        import pymysql

        self._pymysql = pymysql
        self._config = {
            "host": config.get("host", "localhost"),
            "port": config.get("port", 3306),
            "user": config.get("user"),
            "password": config.get("password"),
            "database": config.get("database"),
            "charset": config.get("charset", "utf8mb4"),
        }
        self._local = threading.local()

    def _get_conn(self):
        if not hasattr(self._local, "conn"):
            self._local.conn = self._pymysql.connect(**self._config)
        return self._local.conn

    def execute(self, sql):
        cursor = self._get_conn().cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def close(self):
        if hasattr(self._local, "conn"):
            self._local.conn.close()
