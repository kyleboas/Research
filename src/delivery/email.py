"""Email delivery helpers for finalized report summaries."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import base64
import json
import os
import smtplib
from typing import Any
from urllib import request


@dataclass(frozen=True)
class EmailDeliveryResult:
    provider: str
    delivered: bool


def _build_email_message(*, subject: str, body_text: str, from_email: str, to_emails: list[str], report_markdown: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = ", ".join(to_emails)
    message.set_content(body_text)
    message.add_attachment(report_markdown.encode("utf-8"), maintype="text", subtype="markdown", filename="report.md")
    return message


def _send_via_smtp(*, message: EmailMessage) -> None:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    if host == "":
        raise ValueError("SMTP_HOST must be configured when DELIVERY_EMAIL_PROVIDER=smtp")

    with smtplib.SMTP(host, port, timeout=30) as server:
        if use_tls:
            server.starttls()
        if username:
            server.login(username, password)
        server.send_message(message)


def _send_via_sendgrid(*, to_emails: list[str], subject: str, body_text: str, from_email: str, report_markdown: str) -> None:
    api_key = os.getenv("SENDGRID_API_KEY", "")
    if api_key == "":
        raise ValueError("SENDGRID_API_KEY must be configured when DELIVERY_EMAIL_PROVIDER=sendgrid")

    payload: dict[str, Any] = {
        "personalizations": [{"to": [{"email": address} for address in to_emails]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body_text}],
        "attachments": [
            {
                "content": base64.b64encode(report_markdown.encode("utf-8")).decode("utf-8"),
                "filename": "report.md",
                "type": "text/markdown",
                "disposition": "attachment",
            }
        ],
    }

    req = request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with request.urlopen(req):
        return


def send_summary_email(
    *,
    report_title: str,
    summary: str,
    report_url: str,
    report_markdown: str,
    dry_run: bool = False,
) -> EmailDeliveryResult:
    """Send report summary with URL and markdown attachment using configured provider."""

    provider = os.getenv("DELIVERY_EMAIL_PROVIDER", "smtp").strip().lower()
    from_email = os.getenv("DELIVERY_EMAIL_FROM", "")
    recipients_raw = os.getenv("DELIVERY_EMAIL_TO", "")
    to_emails = [address.strip() for address in recipients_raw.split(",") if address.strip()]

    if from_email == "" or not to_emails:
        raise ValueError("DELIVERY_EMAIL_FROM and DELIVERY_EMAIL_TO must be configured for email delivery")

    subject = f"Research report: {report_title}"
    body_text = f"{summary}\n\nReport URL: {report_url}\n"
    message = _build_email_message(
        subject=subject,
        body_text=body_text,
        from_email=from_email,
        to_emails=to_emails,
        report_markdown=report_markdown,
    )

    if dry_run:
        return EmailDeliveryResult(provider=provider, delivered=False)

    if provider == "smtp":
        _send_via_smtp(message=message)
    elif provider == "sendgrid":
        _send_via_sendgrid(
            to_emails=to_emails,
            subject=subject,
            body_text=body_text,
            from_email=from_email,
            report_markdown=report_markdown,
        )
    else:
        raise ValueError(f"Unsupported DELIVERY_EMAIL_PROVIDER: {provider}")

    return EmailDeliveryResult(provider=provider, delivered=True)
