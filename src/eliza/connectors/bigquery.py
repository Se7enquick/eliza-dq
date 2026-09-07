"""BigQuery connector — pip install eliza-dq[bigquery]"""

from concurrent.futures import ThreadPoolExecutor


class BigQueryConnector:
    dialect = "bigquery"

    def __init__(self, config):
        from google.cloud import bigquery

        self.project = config.get("project")
        self.dataset = config.get("dataset")
        self.location = config.get("location")
        self.client = bigquery.Client(
            project=self.project,
            location=self.location,
        )

    def execute(self, sql):
        rows = self.client.query(sql).result()
        return [dict(row) for row in rows]

    def execute_parallel(self, queries):
        with ThreadPoolExecutor(max_workers=min(len(queries), 8)) as pool:
            return list(pool.map(self.execute, queries))

    @property
    def default_table(self):
        return f"{self.project}.{self.dataset}" if self.dataset else None

    def close(self):
        self.client.close()
