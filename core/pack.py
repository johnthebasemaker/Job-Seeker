"""The apply pack: one JSON file that hands the browser helper everything.

Why a file and not an API: the extension then needs no keys, no login and no
network access of its own. The person downloads the pack from the app and
imports it once; the helper works offline from there.

The pack contains personal data by design - it is the thing that fills the
form - so it never leaves the user's own machine and the app tells them that
plainly.
"""

from __future__ import annotations

import base64
import datetime as dt
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from . import render

PACK_VERSION = 1
MAX_JOBS = 12
#: Chrome's storage.local cap is generous, but keep the file mailable.
SOFT_LIMIT_BYTES = 8 * 1024 * 1024

CONTACT_FIELDS = ("full_name", "email", "phone", "location", "linkedin",
                  "github", "website")


def build(profile: dict[str, Any], jobs: list[dict[str, Any]],
          drafts: dict[str, str] | None = None,
          cover_notes: dict[str, str] | None = None) -> dict[str, Any]:
    """Assemble the pack. ``drafts`` maps job id -> tailored markdown."""
    contact = profile.get("contact") or {}
    answers = dict(profile.get("answer_bank") or {})
    drafts = drafts or {}
    cover_notes = cover_notes or {}
    base_resume = profile.get("base_resume_md") or ""

    entries = []
    for job in jobs[:MAX_JOBS]:
        markdown = drafts.get(job["id"]) or base_resume
        if not markdown:
            continue
        filename = render.safe_filename(contact, job, "pdf")
        try:
            pdf = render.resume_pdf(markdown, contact)
        except render.RenderError:
            continue
        entries.append({
            "id": job["id"],
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "apply_url": job.get("apply_url"),
            "apply_kind": job.get("apply_kind") or "external",
            "source_label": job.get("source_label"),
            "resume_filename": filename,
            "resume_pdf_b64": base64.b64encode(pdf).decode("ascii"),
            "cover_note": cover_notes.get(job["id"], ""),
        })

    return {
        "version": PACK_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "profile": {key: str(contact.get(key) or "") for key in CONTACT_FIELDS},
        "answers": answers,
        "jobs": entries,
    }


def to_bytes(pack: dict[str, Any]) -> bytes:
    return json.dumps(pack, ensure_ascii=False, indent=1).encode("utf-8")


def size_warning(data: bytes) -> str | None:
    if len(data) <= SOFT_LIMIT_BYTES:
        return None
    return (f"This pack is {len(data) / 1_000_000:.1f} MB. Mark fewer jobs as "
            "ready, or build one pack per batch.")


def extension_zip(root: Path | None = None) -> bytes:
    """Zip the helper extension so the app can hand it over as a download."""
    source = root or Path(__file__).resolve().parents[1] / "extension"
    if not source.is_dir():
        raise FileNotFoundError(f"No extension directory at {source}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(source.parent))
    return buffer.getvalue()
