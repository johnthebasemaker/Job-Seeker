"""Job Seeker - Streamlit entry point.

Run locally:   .venv/bin/streamlit run app.py
Deployed on:   Streamlit Community Cloud, free tier.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Job Seeker",
    page_icon="🎯",
    layout="centered",          # centred reads better than wide on a phone
    initial_sidebar_state="collapsed",
)

from core import auth, config, db  # noqa: E402
from views import _shared  # noqa: E402

user = auth.require_login()

profile_page = st.Page("views/onboarding.py", title="Profile", icon=":material/person:")
jobs_page = st.Page("views/jobs.py", title="Jobs", icon=":material/work:", default=True)
tailor_page = st.Page("views/tailor.py", title="Tailor", icon=":material/edit_note:")
settings_page = st.Page("views/settings.py", title="Settings", icon=":material/settings:")

_shared.PAGES.update({
    "profile": profile_page,
    "jobs": jobs_page,
    "tailor": tailor_page,
    "settings": settings_page,
})

with st.sidebar:
    st.markdown(f"**{user.get('display_name') or user['email']}**")
    st.caption(user["email"])
    try:
        used = db.usage_today(user["id"])
        st.caption(f"AI requests today: {used} / {config.llm_daily_call_limit()}")
    except Exception:
        pass
    st.divider()
    if st.button("Sign out", use_container_width=True):
        auth.sign_out()

st.navigation([jobs_page, profile_page, tailor_page, settings_page]).run()
