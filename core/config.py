"""Settings and the country registry.

Values come from environment variables first (that is how GitHub Actions runs
the discovery job) and from ``st.secrets`` second (that is how Streamlit Cloud
runs the app). Nothing is hard-coded and no key ever lands in the repo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any


def _from_streamlit(key: str) -> Any | None:
    try:
        import streamlit as st  # imported lazily: the cron job has no streamlit
    except Exception:
        return None
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        # No secrets.toml at all - fine, we fall through to the default.
        pass
    return None


def get(key: str, default: Any = None) -> Any:
    value = os.environ.get(key)
    if value not in (None, ""):
        return value
    value = _from_streamlit(key)
    if value not in (None, ""):
        return value
    return default


def get_bool(key: str, default: bool = False) -> bool:
    raw = get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def get_int(key: str, default: int) -> int:
    try:
        return int(get(key, default))
    except (TypeError, ValueError):
        return default


def get_list(key: str, default: list[str] | None = None) -> list[str]:
    raw = get(key)
    if raw is None:
        return list(default or [])
    if isinstance(raw, (list, tuple)):
        return [str(v).strip() for v in raw if str(v).strip()]
    return [part.strip() for part in str(raw).split(",") if part.strip()]


# --------------------------------------------------------------------- app
def supabase_url() -> str | None:
    return get("SUPABASE_URL")


def supabase_service_key() -> str | None:
    return get("SUPABASE_SERVICE_KEY")


def allowed_emails() -> list[str]:
    """Only these Google accounts may sign in."""
    return [e.lower() for e in get_list("ALLOWED_EMAILS")]


def dev_mode() -> bool:
    """Local development without Google sign-in configured."""
    return get_bool("APP_DEV_MODE", False)


def dev_user_email() -> str:
    return str(get("DEV_USER_EMAIL", "dev@localhost"))


# --------------------------------------------------------------------- llm
#: Free-tier defaults. Check the provider's model list if one is retired.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "cloudflare": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "ollama": "llama3.1:8b",
}


def llm_provider() -> str:
    """groq (default) | cloudflare | ollama."""
    return str(get("LLM_PROVIDER", "groq")).lower()


def llm_model() -> str:
    return str(get("LLM_MODEL", DEFAULT_MODELS.get(llm_provider(), "")))


def groq_api_key() -> str | None:
    return get("GROQ_API_KEY")


def cf_account_id() -> str | None:
    return get("CF_ACCOUNT_ID")


def cf_api_token() -> str | None:
    return get("CF_API_TOKEN")


def ollama_host() -> str:
    return str(get("OLLAMA_HOST", "http://localhost:11434"))


def llm_daily_call_limit() -> int:
    """Per-user ceiling, so one person cannot drain the shared free key."""
    return get_int("LLM_DAILY_CALL_LIMIT", 120)


# ------------------------------------------------------------- job sources
def jsearch_api_key() -> str | None:
    return get("JSEARCH_API_KEY")


def adzuna_credentials() -> tuple[str | None, str | None]:
    return get("ADZUNA_APP_ID"), get("ADZUNA_APP_KEY")


def jooble_api_key() -> str | None:
    return get("JOOBLE_API_KEY")


# --------------------------------------------------------------- countries
@dataclass(frozen=True)
class Country:
    code: str
    name: str
    currency: str
    #: Adzuna's country slug, or None when Adzuna has no board there.
    adzuna: str | None = None
    #: Jooble's country subdomain, or None.
    jooble: str | None = None
    #: Common locations, used to seed the location picker.
    cities: tuple[str, ...] = field(default_factory=tuple)

    @property
    def sources(self) -> list[str]:
        names = ["jsearch"]
        if self.adzuna:
            names.append("adzuna")
        if self.jooble:
            names.append("jooble")
        return names


COUNTRIES: dict[str, Country] = {
    c.code: c
    for c in [
        Country("IN", "India", "INR", adzuna="in", jooble="in",
                cities=("Bengaluru", "Chennai", "Hyderabad", "Pune", "Mumbai",
                        "Delhi NCR", "Kolkata", "Coimbatore", "Ahmedabad", "Remote")),
        Country("AE", "United Arab Emirates", "AED", jooble="ae",
                cities=("Dubai", "Abu Dhabi", "Sharjah", "Remote")),
        Country("SA", "Saudi Arabia", "SAR", jooble="sa",
                cities=("Riyadh", "Jeddah", "Dammam", "Remote")),
        Country("QA", "Qatar", "QAR", jooble="qa", cities=("Doha", "Remote")),
        Country("KW", "Kuwait", "KWD", cities=("Kuwait City", "Remote")),
        Country("OM", "Oman", "OMR", cities=("Muscat", "Remote")),
        Country("BH", "Bahrain", "BHD", cities=("Manama", "Remote")),
        Country("SG", "Singapore", "SGD", adzuna="sg", jooble="sg",
                cities=("Singapore", "Remote")),
        Country("GB", "United Kingdom", "GBP", adzuna="gb", jooble="uk",
                cities=("London", "Manchester", "Birmingham", "Remote")),
        Country("US", "United States", "USD", adzuna="us", jooble="us",
                cities=("New York", "San Francisco", "Austin", "Remote")),
        Country("CA", "Canada", "CAD", adzuna="ca", jooble="ca",
                cities=("Toronto", "Vancouver", "Remote")),
        Country("AU", "Australia", "AUD", adzuna="au", jooble="au",
                cities=("Sydney", "Melbourne", "Remote")),
        Country("DE", "Germany", "EUR", adzuna="de", jooble="de",
                cities=("Berlin", "Munich", "Remote")),
    ]
}

DEFAULT_COUNTRY = "IN"


@lru_cache(maxsize=1)
def country_options() -> list[tuple[str, str]]:
    """(code, label) pairs for a select box, India first."""
    ordered = [DEFAULT_COUNTRY] + [c for c in COUNTRIES if c != DEFAULT_COUNTRY]
    return [(code, f"{COUNTRIES[code].name} ({code})") for code in ordered]


# ------------------------------------------------------------------ limits
MAX_RESUME_BYTES = 5 * 1024 * 1024


def daily_job_target() -> int:
    """How many jobs a discovery run keeps per user."""
    return get_int("DAILY_JOB_TARGET", 20)
