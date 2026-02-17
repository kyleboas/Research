"""Publish finalized reports to GitHub repository paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import base64
import json
import re
from typing import Any
from urllib import error, parse, request


@dataclass(frozen=True)
class GithubPublishResult:
    """Result details for a GitHub publish attempt."""

    path: str
    html_url: str
    committed: bool
    sha: str | None = None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "report"


def build_report_path(*, report_title: str, report_created_at: datetime) -> str:
    """Build deterministic report path in the repository."""

    day = report_created_at.strftime("%Y-%m-%d")
    slug = _slugify(report_title)
    return f"reports/{day}-{slug}.md"


def _github_api_request(
    *,
    method: str,
    token: str,
    owner: str,
    repo: str,
    path: str,
    branch: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    encoded_path = parse.quote(path, safe="/")
    endpoint = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}"
    if method == "GET":
        endpoint = f"{endpoint}?ref={parse.quote(branch)}"

    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    req = request.Request(endpoint, data=body, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if body is not None:
        req.add_header("Content-Type", "application/json")

    with request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))


def publish_report_markdown(
    *,
    report_markdown: str,
    report_title: str,
    report_created_at: datetime,
    github_token: str,
    github_owner: str,
    github_repo: str,
    github_branch: str,
    dry_run: bool = False,
) -> GithubPublishResult:
    """Commit or update report markdown in GitHub using deterministic report path."""

    path = build_report_path(report_title=report_title, report_created_at=report_created_at)
    html_url = f"https://github.com/{github_owner}/{github_repo}/blob/{github_branch}/{path}"

    if dry_run:
        return GithubPublishResult(path=path, html_url=html_url, committed=False)

    existing_sha: str | None = None
    try:
        get_response = _github_api_request(
            method="GET",
            token=github_token,
            owner=github_owner,
            repo=github_repo,
            path=path,
            branch=github_branch,
        )
        existing_sha = get_response.get("sha")
    except error.HTTPError as exc:
        if exc.code != 404:
            raise

    payload: dict[str, Any] = {
        "message": f"Publish report: {report_title}",
        "content": base64.b64encode(report_markdown.encode("utf-8")).decode("utf-8"),
        "branch": github_branch,
        "committer": {"name": "research-bot", "email": "research-bot@users.noreply.github.com"},
    }
    if existing_sha is not None:
        payload["sha"] = existing_sha

    put_response = _github_api_request(
        method="PUT",
        token=github_token,
        owner=github_owner,
        repo=github_repo,
        path=path,
        branch=github_branch,
        payload=payload,
    )

    committed_sha = None
    commit_data = put_response.get("commit")
    if isinstance(commit_data, dict):
        committed_sha = commit_data.get("sha")

    return GithubPublishResult(path=path, html_url=html_url, committed=True, sha=committed_sha)
