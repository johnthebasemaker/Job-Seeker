"""Sign-in gate.

Streamlit's own OIDC login (``st.login``) handles Google. We only keep the
email, and only accounts on ALLOWED_EMAILS get in - that is what stops a
stranger draining the shared free-tier API key.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from . import config, db


def _allowed(email: str) -> bool:
    allow = config.allowed_emails()
    if not allow:
        return False
    if email.lower() in allow:
        return True
    # "@example.com" in the list allows a whole domain.
    domain = "@" + email.split("@")[-1].lower()
    return domain in allow


def _auth_configured() -> bool:
    try:
        return "auth" in st.secrets and bool(st.secrets["auth"].get("cookie_secret"))
    except Exception:
        return False


def current_user() -> dict[str, Any] | None:
    """The signed-in user row, or None."""
    return st.session_state.get("user")


def require_login() -> dict[str, Any]:
    """Return the user row, or render the sign-in screen and stop."""
    user = current_user()
    if user:
        return user

    if config.dev_mode():
        row = db.get_or_create_user(config.dev_user_email(), "Local dev")
        st.session_state["user"] = row
        return row

    st.title("Job Seeker")
    st.caption("Find the job, tailor the resume, apply with one click.")

    if not _auth_configured():
        st.error(
            "Google sign-in is not configured yet. Add an `[auth]` section to "
            "`.streamlit/secrets.toml`, or set `APP_DEV_MODE = true` to work "
            "locally. The README has both snippets."
        )
        st.stop()

    if not getattr(st.user, "is_logged_in", False):
        st.write("This app is invite-only while we are testing.")
        st.button("Sign in with Google", type="primary", on_click=st.login)
        st.stop()

    email = (getattr(st.user, "email", "") or "").lower()
    if not _allowed(email):
        st.error(f"{email} is not on the invite list.")
        st.caption("Ask the owner to add your address to ALLOWED_EMAILS.")
        st.button("Sign out", on_click=st.logout)
        st.stop()

    row = db.get_or_create_user(email, getattr(st.user, "name", None))
    st.session_state["user"] = row
    return row


def sign_out() -> None:
    st.session_state.pop("user", None)
    if not config.dev_mode():
        st.logout()
    else:
        st.rerun()
