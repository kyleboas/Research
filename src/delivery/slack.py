"""Slack webhook notifications for report delivery."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from urllib import request


@dataclass(frozen=True)
class SlackDeliveryResult:
    delivered: bool


def post_report_summary(*, summary: str, report_url: str, dry_run: bool = False) -> SlackDeliveryResult:
    """Post a report summary and report URL to Slack via webhook."""

    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if webhook_url == "":
        raise ValueError("SLACK_WEBHOOK_URL must be configured for Slack delivery")

    if dry_run:
        return SlackDeliveryResult(delivered=False)

    payload = {
        "text": f"{summary}\n{report_url}",
    }
    req = request.Request(
        webhook_url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req):
        return SlackDeliveryResult(delivered=True)
