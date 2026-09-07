"""Send Slack alerts and generate PDF reports."""

from eliza import check
from eliza.alert import send_slack
from eliza.report import generate_pdf

result = check("data/orders.parquet", checks={
    "order_id": ["not_null"],
    "amount": ["not_negative"],
})

# PDF report (pip install eliza-dq[report])
path = generate_pdf(result, name="orders")
print(f"Report: {path}")

# Slack with PDF attachment
if not result.passed():
    send_slack(
        result,
        token="xoxb-your-token",
        channel="C0123456789",
        pdf=True,
        name="orders",
    )
