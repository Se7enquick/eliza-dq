"""Airflow DAG: run Eliza checks after ETL."""

from airflow.decorators import dag, task
from pendulum import datetime


@dag(schedule="@daily", start_date=datetime(2024, 1, 1), catchup=False)
def dq_pipeline():

    @task
    def run_checks():
        from eliza import check

        result = check(config="orders")
        result.raise_on_fail()
        return result.to_dict()

    @task
    def alert_on_failure(result_dict):
        if not result_dict["passed"]:
            from eliza.alert import send_slack
            from eliza.result import ElizaResult

            # Reconstruct minimal result for alerting
            send_slack(
                result_dict,
                webhook="https://hooks.slack.com/services/...",
            )

    result = run_checks()
    alert_on_failure(result)


dq_pipeline()
