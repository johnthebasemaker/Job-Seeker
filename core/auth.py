"""Sign-in gate.

Two ways in, checked in this order:

1. **Personal invite link** - ``https://<app>/?invite=<token>``. Each person
   gets their own long random token in the ``[invites]`` secrets table, and
   the token decides whose data they see. This is the "click a link and it
   opens" path, and it needs no Google Cloud setup at all.

   A link on its own is a bearer secret, so it is meant to sit behind
   Streamlit Community Cloud's private-app gate: only people on the app's
   viewer list can load the page in the first place, so a forwarded link is
   useless to anyone else. Revoke a link by changing its token.

2. **Google sign-in** via ``st.login``, once an OAuth client is configured in
   ``[auth]``. Only accounts on ALLOWED_EMAILS get in.

Either way, that gate is what stops a stranger draining the shared free-tier
API key.
"""

from __future__ import annotations

import hmac
from typing import Any

import streamlit as st

from . import config, db

INVITE_PARAM = "invite"
MIN_TOKEN_LENGTH = 24


# ------------------------------------------------------------------ invites
def invites() -> dict[str, str]:
    """``{label: token}`` from the ``[invites]`` secrets table."""
    try:
        table = st.secrets.get("invites", {})
        return {str(label): str(token) for label, token in dict(table).items() if token}
    except Exception:
        return {}


def match_invite(token: str | None, table: dict[str, str]) -> str | None:
    """The label whose token matches, compared in constant time."""
    if not token or len(token) < MIN_TOKEN_LENGTH:
        return None
    found = None
    for label, expected in table.items():
        if len(expected) < MIN_TOKEN_LENGTH:
            continue  # a short token is a mistake, never a way in
        if hmac.compare_digest(token.encode(), expected.encode()):
            found = label
    return found


def identity_for(label: str) -> str:
    """Invite labels become the account key. Real emails are kept as-is."""
    clean = label.strip().lower()
    return clean if "@" in clean else f"{clean}@invite.local"


# --------------------------------------------------------------- google
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
    """True only for a real OAuth client, not the example placeholders."""
    try:
        auth = st.secrets["auth"] if "auth" in st.secrets else {}
    except Exception:
        return False
    client_id = str(auth.get("client_id", ""))
    cookie = str(auth.get("cookie_secret", ""))
    return (
        client_id.endswith(".apps.googleusercontent.com")
        and not client_id.startswith(".")
        and bool(cookie)
        and "a-long-random-string" not in cookie
    )


# ------------------------------------------------------------------ gate
def current_user() -> dict[str, Any] | None:
    """The signed-in user row, or None."""
    return st.session_state.get("user")


def _sign_in(email: str, display_name: str | None, method: str) -> dict[str, Any]:
    row = db.get_or_create_user(email, display_name)
    st.session_state["user"] = row
    st.session_state["auth_method"] = method
    return row


def _stop_with(message: str, detail: str | None = None) -> None:
    st.title("Job Seeker")
    st.write(message)
    if detail:
        st.caption(detail)
    st.stop()


def require_login() -> dict[str, Any]:
    """Return the user row, or render the sign-in screen and stop."""
    user = current_user()
    if user:
        return user

    if config.dev_mode():
        return _sign_in(config.dev_user_email(), "Local dev", "dev")

    token = st.query_params.get(INVITE_PARAM)
    if token is not None:
        label = match_invite(token, invites())
        if label:
            return _sign_in(identity_for(label), label, "invite")
        _stop_with(
            "This link is not valid any more.",
            "Ask the person who shared Job Seeker with you for a fresh link.",
        )

    if not _auth_configured():
        _stop_with(
            "Job Seeker is invite-only.",
            "Open the personal link you were sent. If you just signed in to "
            "Streamlit and landed here, tap your link once more.",
        )

    if not getattr(st.user, "is_logged_in", False):
        st.title("Job Seeker")
        st.write("This app is invite-only while we are testing.")
        st.button("Sign in with Google", type="primary", on_click=st.login)
        st.stop()

    email = (getattr(st.user, "email", "") or "").lower()
    if not _allowed(email):
        st.title("Job Seeker")
        st.error(f"{email} is not on the invite list.")
        st.caption("Ask the owner to add your address to ALLOWED_EMAILS.")
        st.button("Sign out", on_click=st.logout)
        st.stop()

    return _sign_in(email, getattr(st.user, "name", None), "google")


def sign_out() -> None:
    method = st.session_state.get("auth_method")
    st.session_state.pop("user", None)
    st.session_state.pop("auth_method", None)
    if method == "google":
        st.logout()
    else:
        # Drop the token from the address bar so a shared screen does not
        # show it; reopening the personal link signs back in.
        st.query_params.clear()
        st.rerun()
