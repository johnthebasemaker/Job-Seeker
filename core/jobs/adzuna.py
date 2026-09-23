"""Adzuna - free developer key, good coverage in India, the UK and Singapore.

Adzuna has no board for the Gulf states, so ``available_for`` returns False
there and the run quietly falls back to JSearch and Jooble.
"""

from __future__ import annotations

import requests

from .. import config
from .base import Job, classify_apply, html_to_text, parse_date

ENDPOINT = "https://api.adzuna.com/v1/api/jobs/{cc}/search/1"


def available_for(country_code: str) -> bool:
    app_id, app_key = config.adzuna_credentials()
    country = config.COUNTRIES.get(country_code.upper())
    return bool(app_id and app_key and country and country.adzuna)


def search(query: str, country_code: str = "IN", location: str | None = None,
           *, results: int = 30, max_days_old: int = 14) -> list[Job]:
    if not available_for(country_code):
        return []
    app_id, app_key = config.adzuna_credentials()
    country = config.COUNTRIES[country_code.upper()]
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": min(results, 50),
        "what": query,
        "max_days_old": max_days_old,
        "content-type": "application/json",
    }
    if location and location.lower() != "remote":
        params["where"] = location
    response = requests.get(ENDPOINT.format(cc=country.adzuna), params=params, timeout=30)
    if response.status_code == 429:
        return []
    response.raise_for_status()
    return [_to_job(item, country.code) for item in response.json().get("results", [])]


def _salary(item: dict) -> str | None:
    low, high = item.get("salary_min"), item.get("salary_max")
    if not low and not high:
        return None
    span = " - ".join(f"{int(v):,}" for v in (low, high) if v)
    return span or None


def _to_job(item: dict, country_code: str) -> Job:
    url = item.get("redirect_url")
    apply_kind, is_indeed = classify_apply(url)
    company = (item.get("company") or {}).get("display_name")
    location = (item.get("location") or {}).get("display_name")
    description = html_to_text(item.get("description"))
    return Job(
        source="adzuna",
        source_label="Adzuna",
        publisher="Adzuna",
        is_indeed=is_indeed,
        title=item.get("title") or "Untitled role",
        company=company,
        location=location,
        country=country_code,
        is_remote="remote" in (location or "").lower(),
        employment_type=item.get("contract_time"),
        salary_text=_salary(item),
        description=description,
        apply_url=url,
        apply_kind=apply_kind,
        posted_at=parse_date(item.get("created")),
    )
