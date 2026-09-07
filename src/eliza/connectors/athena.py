"""Athena connector — pip install eliza-dq[athena]"""

import threading


class AthenaConnector:
    dialect = "athena"

    def __init__(self, config):
        from pyathena import connect

        self._connect = connect
        self._config = {
            "region_name": config.get("region", config.get("region_name", "us-east-1")),
            "s3_staging_dir": config.get("s3_staging_dir", config.get("staging_dir")),
            "schema_name": config.get("schema", config.get("database")),
            "catalog_name": config.get("catalog", "AwsDataCatalog"),
            "work_group": config.get("work_group", "primary"),
        }
        self._local = threading.local()

    def _get_conn(self):
        if not hasattr(self._local, "conn"):
            self._local.conn = self._connect(**self._config)
        return self._local.conn

    def execute(self, sql):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def close(self):
        if hasattr(self._local, "conn"):
            self._local.conn.close()
