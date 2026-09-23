"""JSearch (RapidAPI) - aggregates Google for Jobs, which carries Indeed.

This is the main way Indeed listings reach the app without touching Indeed's
own pages. When a posting has several apply options we keep the Indeed one,
because that is the flow the browser helper knows how to fill.
"""

from __future__ import annotations

import requests

from .. import config
from .base import Job, classify_apply, parse_date

ENDPOINT = "https://jsearch.p.rapidapi.com/search"
HOST = "jsearch.p.rapidapi.com"


def available() -> bool:
    return bool(config.jsearch_api_key())


def search(query: str, country: str = "IN", *, remote_only: bool = False,
           date_posted: str = "week", pages: int = 1) -> list[Job]:
    if not available():
        return []
    jobs: list[Job] = []
    for page in range(1, max(1, pages) + 1):
        params = {
            "query": query,
            "page": str(page),
            "num_pages": "1",
            "country": country.lower(),
            "date_posted": date_posted,
        }
        if remote_only:
            params["work_from_home"] = "true"
        response = requests.get(
            ENDPOINT,
            headers={"X-RapidAPI-Key": config.jsearch_api_key(), "X-RapidAPI-Host": HOST},
            params=params,
            timeout=30,
        )
        if response.status_code == 429:
            break  # monthly free quota is gone; other sources still run
        response.raise_for_status()
        data = response.json().get("data") or []
        jobs.extend(_to_job(item, country) for item in data)
        if len(data) < 10:
            break
    return [job for job in jobs if job is not None]


def _pick_apply(item: dict) -> tuple[str | None, str | None]:
    """Prefer an Indeed apply link when the posting offers one."""
    options = item.get("apply_options") or []
    for option in options:
        if "indeed" in str(option.get("publisher", "")).lower():
            return option.get("apply_link"), option.get("publisher")
    if options:
        return options[0].get("apply_link"), options[0].get("publisher")
    return item.get("job_apply_link"), item.get("job_publisher")


def _salary(item: dict) -> str | None:
    low, high = item.get("job_min_salary"), item.get("job_max_salary")
    if not low and not high:
        return item.get("job_salary") or None
    currency = item.get("job_salary_currency") or ""
    period = item.get("job_salary_period") or ""
    span = " - ".join(f"{int(v):,}" for v in (low, high) if v)
    return f"{currency} {span} {period}".strip()


def _to_job(item: dict, country: str) -> Job:
    url, publisher = _pick_apply(item)
    apply_kind, is_indeed = classify_apply(url, publisher)
    city = item.get("job_city") or ""
    region = item.get("job_state") or ""
    location = ", ".join(part for part in (city, region) if part) or item.get("job_country")
    label = f"{publisher} (via JSearch)" if publisher else "JSearch"
    return Job(
        source="jsearch",
        source_label=label,
        publisher=publisher,
        is_indeed=is_indeed,
        title=item.get("job_title") or "Untitled role",
        company=item.get("employer_name"),
        location=location,
        country=(item.get("job_country") or country).upper()[:2],
        is_remote=bool(item.get("job_is_remote")),
        employment_type=item.get("job_employment_type"),
        salary_text=_salary(item),
        description=item.get("job_description") or "",
        apply_url=url,
        apply_kind=apply_kind,
        posted_at=parse_date(item.get("job_posted_at_datetime_utc")),
    )
