"""Deterministic matching: scoring, ATS keyword coverage and skill gaps.

None of this calls an LLM. Scores are reproducible, explainable and free,
which matters when the shared API key has a daily budget. The model is only
asked to write prose, never to invent a number.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(__file__).parent / "data"

SENIORITY_WORDS = {
    "intern": ("intern", "trainee", "apprentice"),
    "junior": ("junior", "fresher", "entry level", "graduate", "associate", "jr"),
    "mid": ("mid", "engineer ii", "specialist", "executive"),
    "senior": ("senior", "sr", "lead", "principal", "staff", "architect"),
    "manager": ("manager", "head of", "director", "vp"),
}

STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "have",
    "from", "this", "that", "they", "them", "their", "who", "all", "any",
    "can", "has", "not", "but", "out", "into", "more", "than", "such", "must",
    "work", "working", "team", "teams", "role", "job", "jobs", "years", "year",
    "experience", "good", "strong", "ability", "including", "etc", "candidate",
    "candidates", "responsibilities", "requirements", "skills", "using",
}


@lru_cache(maxsize=1)
def skill_index() -> dict[str, re.Pattern[str]]:
    raw = json.loads((DATA_DIR / "skills.json").read_text(encoding="utf-8"))
    index: dict[str, re.Pattern[str]] = {}
    for canonical, aliases in raw.items():
        if canonical.startswith("_"):
            continue
        terms = [canonical, *aliases]
        # Lookarounds instead of \b so "c++" and "c#" still anchor correctly.
        alternation = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
        index[canonical] = re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.I)
    return index


@lru_cache(maxsize=1)
def learning_index() -> dict[str, list[dict[str, str]]]:
    raw = json.loads((DATA_DIR / "learning.json").read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def extract_skills(*texts: str | None) -> set[str]:
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return set()
    return {name for name, pattern in skill_index().items() if pattern.search(blob)}


def learning_links(skill: str) -> list[dict[str, str]]:
    """Curated links when we have them, honest search links when we do not."""
    curated = learning_index().get(skill.lower())
    if curated:
        return curated
    quoted = urllib.parse.quote_plus(f"{skill} full course")
    return [
        {"title": f"YouTube - free {skill} courses",
         "url": f"https://www.youtube.com/results?search_query={quoted}"},
        {"title": f"Coursera - {skill} (audit for free)",
         "url": f"https://www.coursera.org/search?query={urllib.parse.quote_plus(skill)}"},
    ]


# ------------------------------------------------------------------ tokens
def tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    words = re.findall(r"[a-z][a-z+#.]{2,}", text.lower())
    return {w.strip(".") for w in words if w not in STOPWORDS}


def seniority_of(title: str) -> str | None:
    low = f" {title.lower()} "
    for level, words in SENIORITY_WORDS.items():
        if any(f" {w} " in low or low.strip().startswith(w) for w in words):
            return level
    return None


# ------------------------------------------------------------------ scoring
def score_job(job: Any, prefs: dict[str, Any], user_skills: set[str]) -> tuple[int, dict]:
    """Score a job 0-100 against the profile, with the reasoning attached."""
    title = _get(job, "title") or ""
    description = _get(job, "description") or ""
    location = _get(job, "location") or ""
    is_remote = bool(_get(job, "is_remote"))
    posted_at = _get(job, "posted_at")

    reasons: list[str] = []

    # --- title, 40 points
    wanted_titles = [t for t in prefs.get("titles", []) if t.strip()]
    wanted_tokens = set().union(*(tokens(t) for t in wanted_titles)) if wanted_titles else set()
    title_tokens = tokens(title)
    overlap = wanted_tokens & title_tokens
    title_score = 40 * (len(overlap) / len(wanted_tokens)) if wanted_tokens else 20
    if overlap:
        reasons.append(f"Title matches {', '.join(sorted(overlap))}")
    else:
        reasons.append("Title does not match your target roles")

    # Seniority mismatch is the most common false positive, so it bites.
    wanted_level = (prefs.get("seniority") or "").lower() or None
    job_level = seniority_of(title)
    if wanted_level and job_level and wanted_level != job_level:
        distance = abs(_level_rank(wanted_level) - _level_rank(job_level))
        if distance >= 2:
            title_score *= 0.4
            reasons.append(f"Seniority looks off: job reads {job_level}, you want {wanted_level}")
        elif distance == 1:
            title_score *= 0.75

    # --- skills, 35 points
    required = extract_skills(title, description)
    matched = required & user_skills
    missing = required - user_skills
    if required:
        skill_score = 35 * (len(matched) / len(required))
        reasons.append(f"{len(matched)} of {len(required)} listed skills are on your resume")
    else:
        skill_score = 17.5
        reasons.append("No recognisable skills listed in the posting")

    # --- location, 15 points
    wanted_locations = [loc.lower() for loc in prefs.get("locations", []) if loc.strip()]
    location_low = location.lower()
    if prefs.get("remote_only"):
        location_score = 15 if is_remote else 0
    elif not wanted_locations:
        location_score = 10
    elif is_remote or any(loc in location_low or loc == "remote" and is_remote
                          for loc in wanted_locations):
        location_score = 15
    elif any(loc.split(",")[0] in location_low for loc in wanted_locations):
        location_score = 15
    elif (_get(job, "country") or "").upper() == (prefs.get("country") or "").upper():
        location_score = 7
    else:
        location_score = 0
    if location_score < 7:
        reasons.append(f"Location '{location or 'unknown'}' is outside your preferences")

    # --- freshness, 10 points
    age_days = _age_days(posted_at)
    if age_days is None:
        fresh_score = 5.0
    else:
        fresh_score = max(0.0, 10 * math.exp(-age_days / 14))
        if age_days > 21:
            reasons.append(f"Posted {int(age_days)} days ago")

    total = int(round(title_score + skill_score + location_score + fresh_score))
    detail = {
        "title": round(title_score, 1),
        "skills": round(skill_score, 1),
        "location": round(location_score, 1),
        "freshness": round(fresh_score, 1),
        "matched_skills": sorted(matched),
        "missing_skills": sorted(missing),
        "reasons": reasons,
    }
    return max(0, min(100, total)), detail


def _level_rank(level: str) -> int:
    order = ["intern", "junior", "mid", "senior", "manager"]
    return order.index(level) if level in order else 2


def _age_days(posted_at: Any) -> float | None:
    if not posted_at:
        return None
    if isinstance(posted_at, str):
        try:
            posted_at = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(posted_at, datetime):
        return None
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - posted_at).total_seconds() / 86400


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


# ------------------------------------------------------- ATS keyword report
def keyword_report(resume_text: str, job_description: str, job_title: str = "") -> dict:
    """What an ATS keyword filter would see: coverage, hits and misses."""
    required = extract_skills(job_title, job_description)
    present = extract_skills(resume_text)
    matched = sorted(required & present)
    missing = sorted(required - present)

    # Plain keywords that are not in the skills dictionary but are repeated in
    # the posting still matter to a keyword filter.
    jd_tokens = tokens(job_description)
    resume_tokens = tokens(resume_text)
    repeated = [
        word for word in jd_tokens
        if len(word) > 4
        and job_description.lower().count(word) >= 3
        and word not in resume_tokens
    ]

    coverage = round(100 * len(matched) / len(required)) if required else 100
    return {
        "coverage": coverage,
        "matched": matched,
        "missing": missing,
        "other_terms": sorted(repeated)[:10],
        "required_count": len(required),
    }


def ats_checks(resume_md: str, contact: dict[str, str]) -> list[dict[str, str]]:
    """Structural checks an ATS parser cares about. Cheap, local, honest."""
    results: list[dict[str, str]] = []

    def add(ok: bool, label: str, hint: str) -> None:
        results.append({"ok": "yes" if ok else "no", "label": label, "hint": "" if ok else hint})

    words = len(resume_md.split())
    add(250 <= words <= 1000, f"Length: {words} words",
        "Aim for 400-800 words. Too short reads thin, too long gets skimmed.")
    add(bool(contact.get("email")) and bool(contact.get("phone")), "Contact details present",
        "Add an email and phone number on the Profile page - they are added at PDF time.")
    headings = re.findall(r"^##\s+(.+)$", resume_md, re.M)
    lowered = [h.lower() for h in headings]
    add(any("experience" in h for h in lowered), "Has an Experience section",
        "ATS parsers look for a heading containing 'Experience'.")
    add(any("skill" in h for h in lowered), "Has a Skills section",
        "A plain Skills list is the easiest thing for a keyword filter to read.")
    add(any("education" in h for h in lowered), "Has an Education section",
        "Add Education, even if it is one line.")
    bullets = re.findall(r"^\s*-\s+(.+)$", resume_md, re.M)
    add(bool(bullets), f"{len(bullets)} bullet points",
        "Use '- ' bullets under each role rather than paragraphs.")
    with_numbers = [b for b in bullets if re.search(r"\d", b)]
    add(len(with_numbers) >= max(2, len(bullets) // 4),
        f"{len(with_numbers)} bullets carry a number",
        "Quantify what you can: volumes, percentages, team sizes, timelines.")
    add("|" not in resume_md, "No tables",
        "Tables and columns confuse ATS parsers. Keep one column.")
    return results


# ---------------------------------------------------------------- skill gap
def skill_gap(jobs: Iterable[Any], user_skills: set[str], limit: int = 8) -> list[dict]:
    """'Learn X and N more of these jobs open up.'"""
    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    total = 0
    for job in jobs:
        total += 1
        required = extract_skills(_get(job, "title"), _get(job, "description"))
        for skill in required - user_skills:
            counts[skill] = counts.get(skill, 0) + 1
            if len(samples.setdefault(skill, [])) < 3:
                samples[skill].append(_get(job, "title") or "")
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [
        {
            "skill": skill,
            "jobs_unlocked": count,
            "share": round(100 * count / total) if total else 0,
            "sample_titles": samples.get(skill, []),
            "resources": learning_links(skill),
        }
        for skill, count in ranked
    ]


def strengths(jobs: Iterable[Any], user_skills: set[str], limit: int = 8) -> list[dict]:
    """Which of the user's skills the market is actually asking for."""
    counts: dict[str, int] = {}
    for job in jobs:
        required = extract_skills(_get(job, "title"), _get(job, "description"))
        for skill in required & user_skills:
            counts[skill] = counts.get(skill, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"skill": skill, "jobs": count} for skill, count in ranked]
