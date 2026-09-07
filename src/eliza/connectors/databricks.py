"""Databricks connector — pip install eliza-dq[databricks]"""

from concurrent.futures import ThreadPoolExecutor


class DatabricksConnector:
    dialect = "databricks"

    def __init__(self, config):
        from databricks import sql

        self.conn = sql.connect(
            server_hostname=config["host"],
            http_path=config["http_path"],
            access_token=config.get("token"),
            catalog=config.get("catalog"),
            schema=config.get("schema"),
        )

    def execute(self, sql_query):
        cursor = self.conn.cursor()
        cursor.execute(sql_query)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def execute_parallel(self, queries):
        with ThreadPoolExecutor(max_workers=min(len(queries), 8)) as pool:
            return list(pool.map(self.execute, queries))

    def close(self):
        self.conn.close()
