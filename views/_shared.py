"""Small helpers shared by the Streamlit pages."""

from __future__ import annotations

from typing import Any

import streamlit as st

from core import config, db
from core.llm import LLM, LLMError, QuotaExceeded

#: Filled in by app.py so pages can send the user somewhere else.
PAGES: dict[str, Any] = {}


class DailyLimitReached(LLMError):
    pass


def llm_for(user: dict[str, Any]) -> LLM:
    """An LLM that records usage and refuses to blow the daily budget."""
    used = db.usage_today(user["id"])
    limit = config.llm_daily_call_limit()
    if used >= limit:
        raise DailyLimitReached(
            f"You have used today's {limit} AI requests. The counter resets at "
            "midnight UTC - the resume editor and downloads still work."
        )
    return LLM(on_usage=lambda kind, tokens: db.log_usage(user["id"], kind, tokens))


def profile_for(user: dict[str, Any], refresh: bool = False) -> dict[str, Any]:
    if refresh or "profile" not in st.session_state:
        st.session_state["profile"] = db.get_profile(user["id"])
    return st.session_state["profile"]


def prefs_of(profile: dict[str, Any]) -> dict[str, Any]:
    return profile.get("prefs") or {}


def goto(name: str) -> None:
    page = PAGES.get(name)
    if page is not None:
        st.switch_page(page)


def needs_resume(profile: dict[str, Any]) -> bool:
    if profile.get("base_resume_md"):
        return False
    st.info("Upload your resume on the Profile page first.")
    if st.button("Go to Profile"):
        goto("profile")
    return True


def source_badge(job: dict[str, Any]) -> str:
    label = job.get("source_label") or job.get("source") or "unknown"
    if job.get("is_indeed"):
        return f"**Indeed** - {label}"
    return label


def apply_hint(job: dict[str, Any]) -> str:
    return {
        "indeed_easy_apply": "Indeed apply form",
        "greenhouse": "Greenhouse form",
        "lever": "Lever form",
        "ashby": "Ashby form",
    }.get(job.get("apply_kind") or "", "Company site")


def score_colour(score: int) -> str:
    if score >= 70:
        return "green"
    if score >= 45:
        return "orange"
    return "gray"


def show_llm_error(exc: Exception) -> None:
    if isinstance(exc, DailyLimitReached):
        st.warning(str(exc))
    elif isinstance(exc, QuotaExceeded):
        st.warning(str(exc))
    else:
        st.error(f"The AI request failed: {exc}")
