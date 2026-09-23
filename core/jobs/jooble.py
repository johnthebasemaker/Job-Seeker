"""Jooble - free API key, covers India and the Gulf, and often re-lists Indeed.

Jooble only returns a snippet, not the full description, so its jobs score on
title and keywords and the full text is fetched from the apply page only if
the user opens it.
"""

from __future__ import annotations

import requests

from .. import config
from .base import Job, classify_apply, html_to_text, parse_date

ENDPOINT = "https://{cc}.jooble.org/api/{key}"
FALLBACK = "https://jooble.org/api/{key}"


def available_for(country_code: str) -> bool:
    country = config.COUNTRIES.get(country_code.upper())
    return bool(config.jooble_api_key() and country and country.jooble)


def search(query: str, country_code: str = "IN", location: str | None = None,
           *, page: int = 1) -> list[Job]:
    if not available_for(country_code):
        return []
    key = config.jooble_api_key()
    country = config.COUNTRIES[country_code.upper()]
    payload = {"keywords": query, "page": str(page)}
    if location and location.lower() != "remote":
        payload["location"] = location

    for url in (ENDPOINT.format(cc=country.jooble, key=key), FALLBACK.format(key=key)):
        try:
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code >= 400:
                continue
            return [_to_job(item, country.code) for item in response.json().get("jobs", [])]
        except requests.RequestException:
            continue
    return []


def _to_job(item: dict, country_code: str) -> Job:
    url = item.get("link")
    publisher = item.get("source")
    apply_kind, is_indeed = classify_apply(url, publisher)
    label = f"{publisher} (via Jooble)" if publisher else "Jooble"
    return Job(
        source="jooble",
        source_label=label,
        publisher=publisher,
        is_indeed=is_indeed,
        title=item.get("title") or "Untitled role",
        company=item.get("company"),
        location=item.get("location"),
        country=country_code,
        is_remote="remote" in (item.get("location") or "").lower(),
        employment_type=item.get("type"),
        salary_text=item.get("salary") or None,
        description=html_to_text(item.get("snippet")),
        apply_url=url,
        apply_kind=apply_kind,
        posted_at=parse_date(item.get("updated")),
    )
