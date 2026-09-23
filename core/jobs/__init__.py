"""Job discovery: fan out to the configured sources, then dedupe.

Free tiers are measured in a few hundred calls a month, so the call budget is
capped here rather than at the call site: at most three titles by two
locations, one page each.
"""

from __future__ import annotations

from typing import Any, Callable

from . import adzuna, ats, jooble, jsearch
from .base import Job, dedupe, html_to_text, normalise_title

MAX_TITLES = 3
MAX_LOCATIONS = 2

Logger = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def build_queries(prefs: dict[str, Any]) -> list[tuple[str, str | None]]:
    """(query, location) pairs, trimmed to the call budget."""
    titles = [t for t in prefs.get("titles", []) if t.strip()][:MAX_TITLES]
    if not titles:
        titles = ["jobs"]
    locations = [loc for loc in prefs.get("locations", []) if loc.strip()][:MAX_LOCATIONS]
    if prefs.get("remote_only") or not locations:
        locations = ["Remote"] if prefs.get("remote_only") else [None]
    return [(title, location) for title in titles for location in locations]


def matches_filters(job: Job, prefs: dict[str, Any]) -> bool:
    haystack = f"{job.title} {job.description}".lower()
    for term in prefs.get("exclude", []):
        if term.strip() and term.strip().lower() in haystack:
            return False
    if prefs.get("indeed_only") and not job.is_indeed:
        return False
    if prefs.get("remote_only") and not (job.is_remote or "remote" in haystack[:400]):
        return False
    return True


def _board_is_relevant(job: Job, prefs: dict[str, Any]) -> bool:
    """Company boards list every open role; keep the ones worth showing."""
    wanted = {w for title in prefs.get("titles", []) for w in normalise_title(title).split()}
    wanted |= {k.lower() for k in prefs.get("keywords", [])}
    wanted = {w for w in wanted if len(w) > 2}
    if not wanted:
        return True
    hay = f"{normalise_title(job.title)} {job.description[:1500].lower()}"
    return any(word in hay for word in wanted)


def discover(prefs: dict[str, Any], *, log: Logger = _noop) -> list[Job]:
    country = (prefs.get("country") or "IN").upper()
    sources = prefs.get("sources") or {}
    enabled = lambda name: sources.get(name, True)  # noqa: E731
    collected: list[Job] = []

    for title, location in build_queries(prefs):
        query = f"{title} in {location}" if location else title

        if enabled("jsearch") and jsearch.available():
            try:
                found = jsearch.search(query, country, remote_only=bool(prefs.get("remote_only")))
                log(f"JSearch '{query}': {len(found)}")
                collected += found
            except Exception as exc:  # one dead source must not kill the run
                log(f"JSearch failed for '{query}': {exc}")

        if enabled("adzuna") and adzuna.available_for(country):
            try:
                found = adzuna.search(title, country, location)
                log(f"Adzuna '{title}': {len(found)}")
                collected += found
            except Exception as exc:
                log(f"Adzuna failed for '{title}': {exc}")

        if enabled("jooble") and jooble.available_for(country):
            try:
                found = jooble.search(title, country, location)
                log(f"Jooble '{title}': {len(found)}")
                collected += found
            except Exception as exc:
                log(f"Jooble failed for '{title}': {exc}")

    if enabled("ats"):
        for entry in prefs.get("ats_companies", [])[:12]:
            board, slug = entry.get("board"), entry.get("slug")
            if not board or not slug:
                continue
            found = [job for job in ats.fetch(board, slug, country) if _board_is_relevant(job, prefs)]
            log(f"{board}/{slug}: {len(found)}")
            collected += found

    kept = [job for job in collected if matches_filters(job, prefs)]
    return dedupe(kept)


__all__ = ["Job", "discover", "build_queries", "dedupe", "html_to_text",
           "adzuna", "ats", "jooble", "jsearch"]
