"""Turn an uploaded PDF into the canonical resume markdown.

The canonical format is deliberately boring, because both the PDF renderer
and the tailoring editor parse it:

    ## Summary
    One short paragraph.

    ## Skills
    - Python, SQL, FastAPI

    ## Experience

    ### Backend Developer - Acme Technologies
    Chennai, India | Jun 2022 - Present
    - Did a thing that moved a number.

    ## Education

    ### B.E. Computer Science - Anna University
    Chennai | 2018 - 2022

Contact details are never part of this markdown. They live in
``profile.contact`` and are stitched back on at render time, which is what
keeps names, emails and phone numbers away from the model.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from .llm import LLM, LLMError
from .privacy import Redactor, contact_terms, split_contact

SECTION_ORDER = ["Summary", "Skills", "Experience", "Projects", "Education", "Certifications"]

SYSTEM = """You reformat resumes. You never invent content.

Rules you must follow:
- Use ONLY facts present in the input. Never add employers, job titles, dates,
  degrees, certifications, tools or numbers that are not there.
- Placeholder tokens like [[NAME_1]] or [[EMAIL_2]] must be copied through
  exactly as they appear, never rewritten or removed.
- Output markdown only, no commentary, no code fences.

Use exactly this structure, skipping any section the input has nothing for:

## Summary
<one short paragraph, only if the resume already has a summary or objective>

## Skills
- <comma separated list, grouped on a few lines>

## Experience

### <Job title> - <Employer>
<Location> | <Start> - <End>
- <achievement bullet, kept close to the original wording>

## Projects

### <Project name>
- <bullet>

## Education

### <Qualification> - <Institution>
<Location> | <Years>

## Certifications
- <certification, year>
"""


@dataclass
class Entry:
    heading: str
    meta: str = ""
    bullets: list[str] = field(default_factory=list)
    body: str = ""


@dataclass
class Section:
    title: str
    entries: list[Entry] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    body: str = ""


class ResumeError(RuntimeError):
    pass


# ----------------------------------------------------------------- reading
def extract_text(data: bytes) -> str:
    """Pull text out of a PDF. Scanned pages come back empty on purpose."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise ResumeError("pypdf is not installed") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise ResumeError(f"Could not read that PDF: {exc}") from exc

    text = "\n".join(pages).strip()
    if len(text) < 200:
        raise ResumeError(
            "That PDF has almost no selectable text, so it is probably a scan "
            "or an image export. Re-export it from Word or Google Docs as a "
            "normal PDF and upload again."
        )
    return _tidy(text)


def _tidy(text: str) -> str:
    text = text.replace("•", "\n- ").replace("\r", "\n")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# -------------------------------------------------------------- conversion
def to_markdown(raw_text: str, llm: LLM | None = None) -> tuple[str, dict[str, str]]:
    """(markdown, contact). The markdown is contact-free and model-safe."""
    contact, body = split_contact(raw_text)
    if llm is None or not llm.available():
        return naive_markdown(body), contact

    redactor = Redactor(contact_terms(contact))
    safe = redactor.redact(body)
    try:
        reply = llm.ask(SYSTEM, safe[:18000], temperature=0.0, max_tokens=3000)
    except LLMError:
        return naive_markdown(body), contact

    markdown = _strip_fences(reply)
    # Any token the model echoed is mapped back, then dropped if unknown.
    markdown = redactor.result.restore(markdown)
    # Contact details must not sneak back into the body.
    for value in contact.values():
        markdown = markdown.replace(value, "")
    if "##" not in markdown:
        return naive_markdown(body), contact
    return markdown.strip(), contact


def naive_markdown(text: str) -> str:
    """Offline fallback: keep the text, guess the section headings."""
    known = {
        "summary": "Summary", "objective": "Summary", "profile": "Summary",
        "skills": "Skills", "technical skills": "Skills",
        "experience": "Experience", "work experience": "Experience",
        "employment": "Experience", "projects": "Projects",
        "education": "Education", "certifications": "Certifications",
        "certification": "Certifications", "achievements": "Certifications",
    }
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        key = stripped.lower().strip(":").strip()
        if key in known:
            out.append(f"\n## {known[key]}")
        elif stripped.startswith(("-", "*", "•")):
            out.append(f"- {stripped.lstrip('-*• ').strip()}")
        else:
            out.append(stripped)
    markdown = "\n".join(out).strip()
    if "## " not in markdown:
        markdown = "## Summary\n" + markdown
    return markdown


def _strip_fences(text: str) -> str:
    fenced = re.match(r"^\s*```(?:markdown)?\s*(.*?)```\s*$", text, re.S)
    return fenced.group(1) if fenced else text


# ------------------------------------------------------------------ parsing
def parse(markdown: str) -> list[Section]:
    """Canonical markdown -> sections. Used by the PDF and DOCX renderers."""
    sections: list[Section] = []
    current: Section | None = None
    entry: Entry | None = None

    for raw_line in (markdown or "").splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current = Section(title=line[3:].strip())
            sections.append(current)
            entry = None
        elif line.startswith("### "):
            if current is None:
                current = Section(title="Experience")
                sections.append(current)
            entry = Entry(heading=line[4:].strip())
            current.entries.append(entry)
        elif line.strip().startswith(("- ", "* ")):
            bullet = line.strip()[2:].strip()
            if entry is not None:
                entry.bullets.append(bullet)
            elif current is not None:
                current.bullets.append(bullet)
        elif line.strip():
            if entry is not None and not entry.meta and not entry.bullets:
                entry.meta = line.strip()
            elif entry is not None:
                entry.body = (entry.body + " " + line.strip()).strip()
            elif current is not None:
                current.body = (current.body + " " + line.strip()).strip()
    return sections


def skills_text(markdown: str) -> str:
    for section in parse(markdown):
        if "skill" in section.title.lower():
            return " ".join(section.bullets + [section.body])
    return ""


def word_count(markdown: str) -> int:
    return len(re.sub(r"[#*\-|]", " ", markdown or "").split())
