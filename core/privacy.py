"""Strip personal data before anything is sent to an LLM.

The rule for this project: the model never sees who the candidate is. It sees
the shape of their experience. Names, emails, phone numbers, postal addresses
and profile links are replaced with stable tokens before the request and put
back afterwards, so the user still reads a normal resume in the UI.

This is belt and braces on top of the provider choice (Groq does not train on
API data and offers zero data retention), not a replacement for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# +91 98765 43210, (044) 2345 6789, 98765-43210, +971 50 123 4567 ...
PHONE_RE = re.compile(
    r"(?<![\w/])(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3,5}[\s.-]?\d{3,5}(?:[\s.-]?\d{2,4})?(?![\w/])"
)
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>,;)\]]+", re.I)
HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,}")
# "Flat 3B, 12 Anna Salai, Chennai - 600002" style lines.
POSTCODE_RE = re.compile(r"\b\d{6}\b")

#: Tokens look like this so a model is unlikely to rewrite them.
TOKEN_RE = re.compile(r"\[\[([A-Z]+)_(\d+)\]\]")


@dataclass
class Redaction:
    """The redacted text plus the map needed to undo it."""

    text: str
    mapping: dict[str, str] = field(default_factory=dict)

    def restore(self, text: str) -> str:
        """Put the real values back into anything the model returned."""
        out = text
        for token, original in self.mapping.items():
            out = out.replace(token, original)
        # Any token the model invented on its own gets cleaned away rather
        # than shown to the user.
        return TOKEN_RE.sub("", out).replace("  ", " ")


class Redactor:
    """Builds a redaction with stable tokens across several strings."""

    def __init__(self, extra_terms: list[str] | None = None):
        self._mapping: dict[str, str] = {}
        self._seen: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        # Longest first so "Andrew Johnson" wins over "Andrew".
        self._extra = sorted(
            {t.strip() for t in (extra_terms or []) if t and len(t.strip()) > 2},
            key=len,
            reverse=True,
        )

    # ------------------------------------------------------------------
    def _token(self, kind: str, value: str) -> str:
        key = f"{kind}:{value.lower()}"
        if key in self._seen:
            return self._seen[key]
        self._counts[kind] = self._counts.get(kind, 0) + 1
        token = f"[[{kind}_{self._counts[kind]}]]"
        self._seen[key] = token
        self._mapping[token] = value
        return token

    def redact(self, text: str | None) -> str:
        if not text:
            return ""
        out = text
        for term in self._extra:
            out = re.sub(rf"\b{re.escape(term)}\b", self._token("NAME", term), out, flags=re.I)
        out = EMAIL_RE.sub(lambda m: self._token("EMAIL", m.group(0)), out)
        out = URL_RE.sub(lambda m: self._token("LINK", m.group(0)), out)
        out = HANDLE_RE.sub(lambda m: self._token("HANDLE", m.group(0)), out)
        out = PHONE_RE.sub(lambda m: self._phone(m.group(0)), out)
        out = POSTCODE_RE.sub(lambda m: self._token("POSTCODE", m.group(0)), out)
        return out

    def _phone(self, raw: str) -> str:
        """Only treat it as a phone number if it has enough digits.

        Resume bullets are full of numbers ("reduced latency by 40%", "2019 -
        2022") and those must survive, or the model loses the achievements it
        is supposed to keep.
        """
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 8 or len(digits) > 15:
            return raw
        return self._token("PHONE", raw)

    @property
    def result(self) -> Redaction:
        return Redaction(text="", mapping=dict(self._mapping))


def redact(text: str, extra_terms: list[str] | None = None) -> Redaction:
    """One-shot helper: redact a single string."""
    r = Redactor(extra_terms)
    clean = r.redact(text)
    return Redaction(text=clean, mapping=dict(r._mapping))


def split_contact(text: str) -> tuple[dict[str, str], str]:
    """Pull the contact block out of raw resume text, locally.

    Returns (contact, remaining_text). The contact half is stored in Postgres
    and re-attached at PDF render time; the remaining half is what gets
    structured by the model.
    """
    contact: dict[str, str] = {}

    emails = EMAIL_RE.findall(text)
    if emails:
        contact["email"] = emails[0]

    phones = [p for p in PHONE_RE.findall(text) if 8 <= len(re.sub(r"\D", "", p)) <= 15]
    if phones:
        contact["phone"] = phones[0].strip()

    for url in URL_RE.findall(text):
        low = url.lower()
        if "linkedin" in low and "linkedin" not in contact:
            contact["linkedin"] = url.rstrip(".,")
        elif "github" in low and "github" not in contact:
            contact["github"] = url.rstrip(".,")
        elif "website" not in contact and "linkedin" not in low and "github" not in low:
            contact["website"] = url.rstrip(".,")

    # The name is almost always the first non-empty line of a resume, and it
    # is short and has no digits.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) <= 60 and not any(ch.isdigit() for ch in line) and "@" not in line:
            words = line.split()
            if 1 < len(words) <= 5:
                contact["full_name"] = line
        break

    remaining = text
    for value in contact.values():
        remaining = remaining.replace(value, " ")
    return contact, remaining


def contact_terms(contact: dict[str, str]) -> list[str]:
    """Terms from a stored contact block that must also be redacted."""
    terms: list[str] = []
    name = contact.get("full_name", "")
    if name:
        terms.append(name)
        terms.extend([w for w in name.split() if len(w) > 2])
    for key in ("email", "phone", "linkedin", "github", "website", "address"):
        if contact.get(key):
            terms.append(str(contact[key]))
    return terms
