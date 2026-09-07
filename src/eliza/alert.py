"""Alert integrations — Slack, webhook, Discord, Teams."""

import json
import os
import tempfile
import urllib.parse
import urllib.request


def send_slack(result, webhook=None, token=None, channel=None, pdf=False, name=None):
    """Send DQ report to Slack via webhook or bot token.

    Args:
        result: ElizaResult from check()
        webhook: Slack incoming webhook URL
        token: Slack bot token (xoxb-...)
        channel: Slack channel ID (required with token)
        pdf: Attach PDF report (requires token + channel, webhooks can't upload files)
        name: Model/config name for PDF filename and title
    """
    blocks = _build_slack_blocks(result)
    text = result.summary()

    if webhook:
        payload = {"blocks": blocks, "text": text}
        ok = _post_json(webhook, payload)
        if pdf:
            import sys as _sys

            print(
                "Warning: Slack webhooks don't support file uploads. Use token= + channel= for PDF attachments.",
                file=_sys.stderr,
            )
        return ok

    if not (token and channel):
        raise ValueError("Provide webhook= or token= + channel=")

    payload = {"channel": channel, "blocks": blocks, "text": text}
    msg_ok = _post_json(
        "https://slack.com/api/chat.postMessage",
        payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    if pdf:
        _upload_pdf_to_slack(result, token, channel, name)

    return msg_ok


def send_webhook(result, url):
    """Send DQ report to any webhook (Discord, Teams, PagerDuty, custom)."""
    return _post_json(url, result.to_dict())


def _upload_pdf_to_slack(result, token, channel, name=None):
    """Generate PDF and upload to Slack channel."""
    from .report import generate_pdf

    with tempfile.TemporaryDirectory() as tmp:
        path = generate_pdf(result, path=f"{tmp}/report.pdf", name=name)
        filename = f"eliza_{name or 'report'}.pdf"

        params = urllib.parse.urlencode(
            {
                "filename": filename,
                "length": _file_size(path),
            }
        )
        req = urllib.request.Request(
            f"https://slack.com/api/files.getUploadURLExternal?{params}",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            url_resp = json.loads(resp.read())
        except Exception:
            return False

        if not url_resp.get("ok"):
            return False

        upload_url = url_resp["upload_url"]
        file_id = url_resp["file_id"]

        # Step 2: Upload file content
        with open(path, "rb") as f:
            file_data = f.read()

        req = urllib.request.Request(upload_url, data=file_data, method="POST")
        req.add_header("Content-Type", "application/octet-stream")
        try:
            urllib.request.urlopen(req, timeout=30)
        except Exception:
            return False

        # Step 3: Complete upload and share to channel
        status = result.summary().split("(")[0].strip()
        complete_payload = {
            "files": [{"id": file_id, "title": f"Eliza DQ: {name or 'report'} - {status}"}],
            "channel_id": channel,
        }
        return _post_json(
            "https://slack.com/api/files.completeUploadExternal",
            complete_payload,
            headers={"Authorization": f"Bearer {token}"},
        )


def _file_size(path):
    return os.path.getsize(path)


def _build_slack_blocks(result):
    emoji = "\U0001f534" if not result.passed() else "\U0001f7e2"
    title = f"{emoji} Eliza DQ ({result.total_rows:,} rows, {result.elapsed_ms:.0f}ms)"

    checks_text = ""
    for c in result.checks:
        icon = "✅" if c.status == "pass" else "⚠️" if c.status == "warn" else "❌"
        col = f"{c.column}:" if c.column else ""
        checks_text += f"{icon} `{col}{c.name}` — {c.fail_count:,} ({c.fail_rate:.1%})\n"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": checks_text}},
    ]

    if result.samples:
        samples_text = ""
        for sample_key, sdf in list(result.samples.items())[:3]:
            cnt = next((c.fail_count for c in result.checks if f"{c.column}:{c.name}" == sample_key), 0)
            samples_text += f"\n*{sample_key}* ({cnt:,}):\n"
            rows = sdf.head(2).iter_rows(named=True) if hasattr(sdf, "head") else sdf[:2]
            for row in rows:
                compact = {k: str(v)[:25] for k, v in row.items() if v is not None}
                samples_text += f"```{compact}```\n"

        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Samples:*{samples_text}"}})

    blocks.append(
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Eliza DQ v0.1 | {result.elapsed_ms:.0f}ms"}]}
    )

    return blocks


def _post_json(url, payload, headers=None):
    """POST JSON to URL. Returns parsed response or True on success."""
    all_headers = {"Content-Type": "application/json"}
    if headers:
        all_headers.update(headers)

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=all_headers)

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        body = json.loads(resp.read())
        if isinstance(body, dict) and "ok" in body:
            return body if body["ok"] else False
        return body
    except Exception:
        return False
