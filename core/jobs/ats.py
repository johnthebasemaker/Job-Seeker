"""Company job boards: Greenhouse, Lever and Ashby.

These are public, documented endpoints, and their application forms are the
simple ones the browser helper can fill reliably. Boards return everything a
company has open, so results are filtered against the user's titles and
keywords before they are kept.
"""

from __future__ import annotations

import requests

from .base import Job, html_to_text, parse_date

BOARDS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


def check_slug(board: str, slug: str) -> tuple[bool, str]:
    """Used by the 'Check' button in the UI so nobody saves a dead slug."""
    if board not in BOARDS:
        return False, f"Unknown board '{board}'"
    try:
        response = requests.get(BOARDS[board].format(slug=slug.strip()), timeout=20)
    except requests.RequestException as exc:
        return False, f"Could not reach {board}: {exc}"
    if response.status_code == 404:
        return False, "No board with that name"
    if response.status_code >= 400:
        return False, f"{board} returned {response.status_code}"
    try:
        count = len(_extract(board, response.json()))
    except ValueError:
        return False, "Unexpected reply from the board"
    return True, f"Found {count} open roles"


def _extract(board: str, payload) -> list[dict]:
    if board == "greenhouse":
        return payload.get("jobs", [])
    if board == "lever":
        return payload if isinstance(payload, list) else []
    if board == "ashby":
        return payload.get("jobs", [])
    raise ValueError(board)


def fetch(board: str, slug: str, country_code: str = "IN") -> list[Job]:
    if board not in BOARDS:
        return []
    try:
        response = requests.get(BOARDS[board].format(slug=slug.strip()), timeout=25)
        if response.status_code >= 400:
            return []
        items = _extract(board, response.json())
    except (requests.RequestException, ValueError):
        return []
    convert = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}[board]
    return [convert(item, slug, country_code) for item in items]


def _greenhouse(item: dict, slug: str, country: str) -> Job:
    return Job(
        source="greenhouse",
        source_label=f"{slug.title()} (Greenhouse)",
        publisher="Greenhouse",
        title=item.get("title") or "Untitled role",
        company=slug.replace("-", " ").title(),
        location=(item.get("location") or {}).get("name"),
        country=country,
        description=html_to_text(item.get("content")),
        apply_url=item.get("absolute_url"),
        apply_kind="greenhouse",
        posted_at=parse_date(item.get("updated_at")),
    )


def _lever(item: dict, slug: str, country: str) -> Job:
    categories = item.get("categories") or {}
    created = item.get("createdAt")
    posted = None
    if isinstance(created, (int, float)):
        from datetime import datetime, timezone
        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
    return Job(
        source="lever",
        source_label=f"{slug.title()} (Lever)",
        publisher="Lever",
        title=item.get("text") or "Untitled role",
        company=slug.replace("-", " ").title(),
        location=categories.get("location"),
        country=country,
        employment_type=categories.get("commitment"),
        description=item.get("descriptionPlain") or html_to_text(item.get("description")),
        apply_url=item.get("hostedUrl"),
        apply_kind="lever",
        posted_at=posted,
    )


def _ashby(item: dict, slug: str, country: str) -> Job:
    return Job(
        source="ashby",
        source_label=f"{slug.title()} (Ashby)",
        publisher="Ashby",
        title=item.get("title") or "Untitled role",
        company=item.get("companyName") or slug.replace("-", " ").title(),
        location=item.get("location"),
        country=country,
        is_remote=bool(item.get("isRemote")),
        employment_type=item.get("employmentType"),
        description=item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml")),
        apply_url=item.get("jobUrl") or item.get("applyUrl"),
        apply_kind="ashby",
        posted_at=parse_date(item.get("publishedAt")),
    )
