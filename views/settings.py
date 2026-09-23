"""Settings: what is connected, what is stored, and how to erase it."""

from __future__ import annotations

import streamlit as st

from core import auth, config, db
from core.llm import LLM
from views import _shared

user = auth.require_login()
profile = _shared.profile_for(user)

st.title("Settings")

# ------------------------------------------------------------- services
st.subheader("Connected services")
st.caption("Keys are held by the app owner. You never have to get your own.")

llm = LLM()
adzuna_id, adzuna_key = config.adzuna_credentials()
rows = [
    (f"AI ({llm.provider}, {llm.model})", llm.available()),
    ("JSearch - Indeed and Google for Jobs listings", bool(config.jsearch_api_key())),
    ("Adzuna", bool(adzuna_id and adzuna_key)),
    ("Jooble", bool(config.jooble_api_key())),
    ("Company boards (Greenhouse, Lever, Ashby)", True),
]
for label, ready in rows:
    st.markdown(("✅ " if ready else "➖ ") + label + ("" if ready else " - no key set"))

used = db.usage_today(user["id"])
limit = config.llm_daily_call_limit()
st.progress(min(1.0, used / limit) if limit else 0.0,
            text=f"AI requests today: {used} of {limit}")

# -------------------------------------------------------------- privacy
st.subheader("Your data")
st.markdown(
    """
**Stored for you:** your resume file and its text, your preferences, your
application answers, and the jobs found for you. They sit in this app's own
database, under your account.

**Sent to the AI:** the resume text and the job description, with your name,
email, phone number, links and postcode replaced by placeholders first. The
real values are put back on your device side of the app. The AI provider we
use does not train on API data.

**Never sent anywhere:** your contact details, which are only merged back in
when a PDF or Word file is generated.
"""
)

with st.expander("What the AI actually receives"):
    from core.privacy import Redactor, contact_terms

    sample = (profile.get("base_resume_md") or "Upload a resume to see this.")[:900]
    redactor = Redactor(contact_terms(profile.get("contact") or {}))
    st.code(redactor.redact(sample) or "(nothing yet)", language="markdown")

# --------------------------------------------------------------- delete
st.subheader("Delete everything")
st.caption(
    "This removes your resume file, your profile, every job we found for you "
    "and every tailored draft. It cannot be undone."
)
confirm = st.text_input(f"Type your email ({user['email']}) to confirm")
if st.button("Delete my data", type="primary", disabled=confirm.strip().lower() != user["email"]):
    result = db.delete_everything(user["id"], user["email"])
    st.session_state.clear()
    st.success(f"Deleted. {result['files']} stored files removed.")
    st.caption("Sign out to finish.")
    st.button("Sign out", on_click=auth.sign_out)
