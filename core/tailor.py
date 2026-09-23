"""AI tailoring: analysis, suggestions, chat editing and a fabrication check.

Two rules shape this module:

1. Numbers are computed, never generated. The match score and the ATS
   coverage come from core.match, so they are stable and explainable.
2. The model may rephrase, reorder and re-emphasise what is already true. It
   may not add an employer, a date, a degree, a certification, a tool or a
   metric. Every edit is diffed against the original and anything new is put
   in front of the user before it can be saved.
"""

from __future__ import annotations

import re
from typing import Any

from . import match
from .llm import LLM, LLMError
from .privacy import Redactor, contact_terms
from .resume import parse

GUARDRAIL = """You help a job seeker tailor their existing resume to one job.

Hard rules:
- Never invent facts. Do not add employers, job titles, dates, degrees,
  certifications, tools, languages or metrics that are not already in the
  resume. If the job needs something the resume does not show, say so plainly
  and suggest they learn it - do not write it in.
- You may rephrase bullets, reorder them, merge them, use the job's wording
  for skills the person already has, and sharpen weak verbs.
- Keep every number exactly as it appears in the original.
- Placeholder tokens like [[NAME_1]] are private data. Copy them through
  unchanged; never guess what they stand for.
- Keep the markdown structure: '## Section', '### Role - Employer', a meta
  line, then '- ' bullets.
"""

SUGGEST_SYSTEM = GUARDRAIL + """
Return JSON only, shaped like:
{"suggestions": [
  {"section": "Experience",
   "original": "<the exact line from the resume you would change, or ''>",
   "proposed": "<your rewrite>",
   "why": "<one sentence, mention the job requirement it serves>",
   "keywords": ["keyword you worked in"]}
]}
Give between 3 and 6 suggestions, most valuable first.
"""

CHAT_SYSTEM = GUARDRAIL + """
You are in a chat editor. Reply in JSON only:
{"reply": "<what you are telling the user, plain text, 1-4 sentences>",
 "resume_md": "<the complete updated resume markdown, or null if you are only answering a question>"}
Only fill resume_md when the user asked for a change. Return the whole
document when you do, not a fragment.
"""


# ------------------------------------------------------------------ report
def build_report(resume_md: str, contact: dict[str, str], job: dict[str, Any],
                 prefs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything deterministic we can say about this resume for this job."""
    description = job.get("description") or ""
    title = job.get("title") or ""
    keywords = match.keyword_report(resume_md, description, title)
    checks = match.ats_checks(resume_md, contact)
    user_skills = match.extract_skills(resume_md)
    score, detail = match.score_job(job, prefs or {}, user_skills)
    return {
        "coverage": keywords["coverage"],
        "matched": keywords["matched"],
        "missing": keywords["missing"],
        "other_terms": keywords["other_terms"],
        "checks": checks,
        "match_score": score,
        "match_detail": detail,
    }


def _job_brief(job: dict[str, Any], limit: int = 6000) -> str:
    bits = [
        f"Title: {job.get('title')}",
        f"Company: {job.get('company')}",
        f"Location: {job.get('location')}",
        f"Employment type: {job.get('employment_type') or 'not stated'}",
        "",
        (job.get("description") or "")[:limit],
    ]
    return "\n".join(bits)


def _redactor(contact: dict[str, str]) -> Redactor:
    return Redactor(contact_terms(contact))


# -------------------------------------------------------------- suggestions
def suggest_edits(resume_md: str, job: dict[str, Any], llm: LLM,
                  report: dict[str, Any] | None = None,
                  contact: dict[str, str] | None = None) -> list[dict[str, Any]]:
    redactor = _redactor(contact or {})
    safe_resume = redactor.redact(resume_md)
    safe_job = redactor.redact(_job_brief(job))
    missing = ", ".join((report or {}).get("missing", [])[:12]) or "none detected"

    user = (
        f"JOB\n{safe_job}\n\n"
        f"RESUME\n{safe_resume}\n\n"
        f"Keywords the job asks for that the resume does not show: {missing}.\n"
        "Only use those keywords where the resume already shows the underlying "
        "work. Otherwise leave them out and say which ones are genuinely missing."
    )
    payload = llm.ask_json(SUGGEST_SYSTEM, user, temperature=0.3, max_tokens=2000)
    suggestions = payload.get("suggestions") if isinstance(payload, dict) else payload
    if not isinstance(suggestions, list):
        raise LLMError("The model did not return a suggestion list")

    restored = []
    for item in suggestions[:8]:
        if not isinstance(item, dict):
            continue
        restored.append({
            "section": str(item.get("section") or ""),
            "original": redactor.result.restore(str(item.get("original") or "")),
            "proposed": redactor.result.restore(str(item.get("proposed") or "")),
            "why": redactor.result.restore(str(item.get("why") or "")),
            "keywords": [str(k) for k in (item.get("keywords") or [])][:6],
        })
    return restored


def apply_suggestion(resume_md: str, suggestion: dict[str, Any]) -> tuple[str, bool]:
    """Swap one line in place. Returns (markdown, applied)."""
    original = (suggestion.get("original") or "").strip()
    proposed = (suggestion.get("proposed") or "").strip()
    if not proposed:
        return resume_md, False
    if original and original in resume_md:
        return resume_md.replace(original, proposed, 1), True
    if original:
        # The model often quotes a bullet without its leading "- ".
        loose = re.escape(original.lstrip("- ").strip())
        pattern = re.compile(rf"^(\s*-\s*){loose}\s*$", re.M)
        if pattern.search(resume_md):
            return pattern.sub(lambda m: f"{m.group(1)}{proposed.lstrip('- ')}", resume_md, count=1), True
    return resume_md, False


# --------------------------------------------------------------------- chat
def chat(messages: list[dict[str, str]], resume_md: str, job: dict[str, Any],
         llm: LLM, contact: dict[str, str] | None = None) -> dict[str, Any]:
    """One chat turn. ``messages`` is the visible history, oldest first."""
    redactor = _redactor(contact or {})
    safe_job = redactor.redact(_job_brief(job, limit=4000))
    safe_resume = redactor.redact(resume_md)

    conversation = [{"role": "system", "content": CHAT_SYSTEM},
                    {"role": "user",
                     "content": f"JOB\n{safe_job}\n\nCURRENT RESUME\n{safe_resume}"}]
    for message in messages[-10:]:
        role = "assistant" if message.get("role") == "assistant" else "user"
        conversation.append({"role": role,
                             "content": redactor.redact(str(message.get("content", "")))})

    response = llm.chat(conversation, temperature=0.3, max_tokens=3000, json_mode=True)
    from .llm import parse_json
    payload = parse_json(response.text)
    if not isinstance(payload, dict):
        return {"reply": redactor.result.restore(response.text), "resume_md": None}

    reply = redactor.result.restore(str(payload.get("reply") or ""))
    updated = payload.get("resume_md")
    if isinstance(updated, str) and "##" in updated:
        updated = redactor.result.restore(updated)
    else:
        updated = None
    return {"reply": reply, "resume_md": updated}


# ------------------------------------------------------------- fabrication
_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?(?!\w)")
_PROPER_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9.+#]{1,}\s?){1,3}\b")


def fabrication_warnings(original_md: str, new_md: str,
                         job_description: str = "") -> list[dict[str, str]]:
    """Flag anything in the rewrite that was not in the original."""
    warnings: list[dict[str, str]] = []

    old_numbers = set(_NUMBER_RE.findall(original_md))
    for number in sorted(set(_NUMBER_RE.findall(new_md)) - old_numbers):
        if len(number.strip(".,")) < 2:
            continue
        warnings.append({
            "kind": "number",
            "value": number,
            "note": "This figure is not in your original resume. Keep it only if it is true.",
        })

    old_skills = match.extract_skills(original_md)
    for skill in sorted(match.extract_skills(new_md) - old_skills):
        in_jd = skill in match.extract_skills(job_description)
        warnings.append({
            "kind": "skill",
            "value": skill,
            "note": ("This skill is in the job description but was not on your resume. "
                     "Only keep it if you have really used it."
                     if in_jd else
                     "This skill was added and was not on your original resume."),
        })

    old_headings = {e.heading.lower() for s in parse(original_md) for e in s.entries}
    for section in parse(new_md):
        for entry in section.entries:
            if entry.heading.lower() not in old_headings:
                warnings.append({
                    "kind": "entry",
                    "value": entry.heading,
                    "note": "A new role or entry appeared. Check it against your real history.",
                })

    return warnings[:20]


# ------------------------------------------------------------ cover letter
COVER_SYSTEM = GUARDRAIL + """
Write a short cover note, 120-160 words, in plain language and first person.
No greeting line placeholders like [Hiring Manager], no invented details, no
flattery about the company you cannot back up. Return plain text only.
"""


def cover_note(resume_md: str, job: dict[str, Any], llm: LLM,
               contact: dict[str, str] | None = None) -> str:
    redactor = _redactor(contact or {})
    user = (f"JOB\n{redactor.redact(_job_brief(job, limit=3000))}\n\n"
            f"RESUME\n{redactor.redact(resume_md)}")
    text = llm.ask(COVER_SYSTEM, user, temperature=0.4, max_tokens=1200)
    return redactor.result.restore(text).strip()
