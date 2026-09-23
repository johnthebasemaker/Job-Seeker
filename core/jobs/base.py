"""The normalised job record every source is converted into."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_COMPANY_NOISE = re.compile(
    r"\b(pvt|private|ltd|limited|llp|inc|llc|corp|corporation|technologies|"
    r"technology|solutions|services|systems|india|group|co)\b",
    re.I,
)
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")

APPLY_KINDS = {
    "indeed.com": "indeed_easy_apply",
    "greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "ashbyhq.com": "ashby",
}


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = unescape(_TAG_RE.sub("\n", raw))
    text = _WS_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _slug(value: str | None) -> str:
    if not value:
        return ""
    return _PUNCT_RE.sub(" ", value.lower()).strip()


def normalise_company(value: str | None) -> str:
    return _WS_RE.sub(" ", _COMPANY_NOISE.sub(" ", _slug(value))).strip()


def normalise_title(value: str | None) -> str:
    cleaned = _slug(value)
    # Drop the req-id / location noise recruiters bolt onto titles.
    cleaned = re.sub(r"\b(job id|req|requisition|jr|id)\s*\d+\b", " ", cleaned)
    return _WS_RE.sub(" ", cleaned).strip()


def classify_apply(url: str | None, publisher: str | None = None) -> tuple[str, bool]:
    """Return (apply_kind, is_indeed) for an apply link."""
    low = (url or "").lower()
    for host, kind in APPLY_KINDS.items():
        if host in low:
            return kind, kind == "indeed_easy_apply"
    if publisher and "indeed" in publisher.lower():
        return "external", True
    return "external", False


@dataclass
class Job:
    source: str
    source_label: str
    title: str
    company: str | None = None
    location: str | None = None
    country: str | None = None
    description: str = ""
    apply_url: str | None = None
    apply_kind: str = "external"
    publisher: str | None = None
    is_indeed: bool = False
    is_remote: bool = False
    employment_type: str | None = None
    salary_text: str | None = None
    posted_at: datetime | None = None
    score: int = 0
    score_detail: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Same role from two boards collapses to one row."""
        key = "|".join([
            normalise_company(self.company),
            normalise_title(self.title),
            _slug((self.location or "").split(",")[0]),
        ])
        return hashlib.sha1(key.encode("utf-8")).hexdigest()

    def to_row(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "source": self.source,
            "source_label": self.source_label,
            "publisher": self.publisher,
            "is_indeed": self.is_indeed,
            "title": self.title[:300],
            "company": (self.company or "")[:200] or None,
            "location": (self.location or "")[:200] or None,
            "country": self.country,
            "is_remote": self.is_remote,
            "employment_type": self.employment_type,
            "salary_text": self.salary_text,
            # Descriptions are the bulk of the row; 12k chars is plenty for
            # both keyword scoring and the tailoring prompt.
            "description": (self.description or "")[:12000],
            "apply_url": self.apply_url,
            "apply_kind": self.apply_kind,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "score": self.score,
            "score_detail": self.score_detail,
        }


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    for parse in (datetime.fromisoformat,):
        try:
            parsed = parse(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def dedupe(jobs: list[Job]) -> list[Job]:
    """Keep one job per fingerprint, preferring Indeed then the richer record."""
    best: dict[str, Job] = {}
    for job in jobs:
        current = best.get(job.fingerprint)
        if current is None:
            best[job.fingerprint] = job
            continue
        better = (job.is_indeed and not current.is_indeed) or (
            job.is_indeed == current.is_indeed
            and len(job.description) > len(current.description)
        )
        if better:
            best[job.fingerprint] = job
    return list(best.values())
