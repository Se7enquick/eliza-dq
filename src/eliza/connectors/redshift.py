"""Redshift connector — pip install eliza-dq[redshift]"""

from concurrent.futures import ThreadPoolExecutor


class RedshiftConnector:
    dialect = "redshift"

    def __init__(self, config):
        import redshift_connector

        self.conn = redshift_connector.connect(
            host=config["host"],
            port=config.get("port", 5439),
            database=config.get("database"),
            user=config.get("user"),
            password=config.get("password"),
            ssl=config.get("ssl", True),
        )
        self.conn.autocommit = True

    def execute(self, sql):
        cursor = self.conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def execute_parallel(self, queries):
        with ThreadPoolExecutor(max_workers=min(len(queries), 8)) as pool:
            return list(pool.map(self.execute, queries))

    def close(self):
        self.conn.close()
