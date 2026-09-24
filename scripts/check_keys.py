"""Check every configured key with one real call each. Prints no secrets.

    .venv/bin/python scripts/check_keys.py

Reads .streamlit/secrets.toml when it exists, otherwise the environment, so
it works locally and inside GitHub Actions.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from core import config  # noqa: E402

OK, BAD, SKIP = "  ok  ", " FAIL ", " skip "


def _load_local_secrets() -> None:
    """Make st.secrets values visible without a Streamlit session."""
    import os
    import tomllib

    path = Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"
    if not path.exists():
        return
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        sys.exit(f"secrets.toml has a typo: {exc}. Most often a curly quote "
                 "from a Mac editor, or a value missing its closing quote.")
    for key, value in data.items():
        if isinstance(value, (str, int, float)) and key not in os.environ:
            os.environ[key] = str(value)


def line(status: str, label: str, detail: str = "") -> None:
    print(f"[{status}] {label}" + (f" - {detail}" if detail else ""))


def check_supabase() -> None:
    url, key = config.supabase_url(), config.supabase_service_key()
    if not url or not key:
        return line(SKIP, "Supabase", "SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
    if "YOUR-PROJECT" in url:
        return line(BAD, "Supabase", "SUPABASE_URL is still the example value")
    try:
        response = requests.get(
            f"{url}/rest/v1/app_user?select=id&limit=1",
            headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30)
    except requests.RequestException as exc:
        return line(BAD, "Supabase", str(exc))
    if response.ok:
        return line(OK, "Supabase", f"{len(response.json())} user row(s) visible")
    line(BAD, "Supabase", f"{response.status_code} {response.text[:120]}")


def check_llm() -> None:
    provider, model = config.llm_provider(), config.llm_model()
    if provider != "groq":
        return line(SKIP, f"LLM ({provider})", "no automated check for this provider yet")
    key = config.groq_api_key()
    if not key:
        return line(SKIP, "Groq", "GROQ_API_KEY not set")
    try:
        models = requests.get("https://api.groq.com/openai/v1/models",
                              headers={"Authorization": f"Bearer {key}"}, timeout=30)
        if not models.ok:
            return line(BAD, "Groq", f"{models.status_code} {models.text[:120]}")
        available = {m["id"] for m in models.json().get("data", [])}
        if model not in available:
            chat_models = sorted(m for m in available
                                 if not any(x in m for x in ("whisper", "tts", "guard")))
            return line(BAD, "Groq", f"model '{model}' not on this key. Available: "
                                     + ", ".join(chat_models))
        payload = {"model": model, "max_tokens": 200,
                   "messages": [{"role": "user", "content": "Reply with the word ready."}]}
        if "gpt-oss" in model:
            payload["reasoning_effort"] = "low"
        chat = requests.post("https://api.groq.com/openai/v1/chat/completions",
                             headers={"Authorization": f"Bearer {key}"},
                             json=payload, timeout=60)
    except requests.RequestException as exc:
        return line(BAD, "Groq", str(exc))
    if not chat.ok:
        return line(BAD, "Groq", f"{chat.status_code} {chat.text[:120]}")
    reply = (chat.json()["choices"][0]["message"].get("content") or "").strip()
    if not reply:
        return line(BAD, "Groq", "empty reply - raise max_tokens or lower reasoning_effort")
    line(OK, f"Groq ({model})", f"replied {reply[:30]!r}")


def check_jsearch() -> None:
    key = config.jsearch_api_key()
    if not key:
        return line(SKIP, "JSearch", "JSEARCH_API_KEY not set")
    from core.jobs import jsearch

    try:
        response = requests.get(
            jsearch.ENDPOINT,
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": jsearch.HOST},
            params={"query": "python developer in Chennai", "country": "in"}, timeout=90)
    except requests.RequestException as exc:
        return line(BAD, "JSearch", f"{exc} - try again, the first call is sometimes slow")
    if response.status_code == 403:
        return line(BAD, "JSearch",
                    "the key is not subscribed to this API. Open the JSearch page on "
                    "RapidAPI and subscribe to the free Basic plan.")
    if response.status_code == 404:
        return line(BAD, "JSearch",
                    f"JSearch no longer has {jsearch.ENDPOINT} - the API changed again. "
                    "Update ENDPOINT in core/jobs/jsearch.py.")
    if response.status_code == 429:
        return line(BAD, "JSearch", "monthly quota used up")
    if not response.ok:
        return line(BAD, "JSearch", f"{response.status_code} {response.text[:120]}")
    data, _ = jsearch._page(response.json())
    publishers = {}
    for item in data:
        name = item.get("job_publisher") or "unknown"
        publishers[name] = publishers.get(name, 0) + 1
    top = ", ".join(f"{k} x{v}" for k, v in sorted(publishers.items(), key=lambda kv: -kv[1])[:4])
    line(OK, "JSearch", f"{len(data)} results ({top})")


def check_adzuna() -> None:
    app_id, app_key = config.adzuna_credentials()
    if not (app_id and app_key):
        return line(SKIP, "Adzuna", "ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
    try:
        response = requests.get(
            "https://api.adzuna.com/v1/api/jobs/in/search/1",
            params={"app_id": app_id, "app_key": app_key, "results_per_page": 5,
                    "what": "python developer", "content-type": "application/json"},
            timeout=40)
    except requests.RequestException as exc:
        return line(BAD, "Adzuna", str(exc))
    if not response.ok:
        return line(BAD, "Adzuna", f"{response.status_code} {response.text[:120]}")
    line(OK, "Adzuna", f"{len(response.json().get('results', []))} results for India")


def check_jooble() -> None:
    key = config.jooble_api_key()
    if not key:
        return line(SKIP, "Jooble", "JOOBLE_API_KEY not set")
    try:
        response = requests.post(f"https://in.jooble.org/api/{key}",
                                 json={"keywords": "python developer", "location": "Chennai"},
                                 timeout=40)
    except requests.RequestException as exc:
        return line(BAD, "Jooble", str(exc))
    if not response.ok:
        return line(BAD, "Jooble", f"{response.status_code} {response.text[:120]}")
    line(OK, "Jooble", f"{len(response.json().get('jobs', []))} results for India")


def check_sign_in() -> None:
    import tomllib

    path = Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    invites = {k: v for k, v in (data.get("invites") or {}).items() if v}
    short = [k for k, v in invites.items() if len(str(v)) < 24]
    if short:
        line(BAD, "Invite links", "token too short for: " + ", ".join(short)
             + " - recreate with scripts/invites.py revoke <name>")
    elif invites:
        line(OK, "Invite links", f"{len(invites)} person(s): " + ", ".join(sorted(invites)))
    else:
        line(SKIP, "Invite links", "none yet - scripts/invites.py add friend")

    auth = data.get("auth") or {}
    if not auth:
        return line(SKIP, "Google sign-in", "not set up (optional - invite links work without it)")
    client_id = str(auth.get("client_id", ""))
    if not client_id.endswith(".apps.googleusercontent.com") or client_id.startswith("."):
        return line(BAD, "Google sign-in",
                    "client_id is not a real OAuth client ID. Either finish the OAuth "
                    "client or comment out the [auth] block.")
    if "a-long-random-string" in str(auth.get("cookie_secret", "")):
        return line(BAD, "Google sign-in", "cookie_secret is still the example value")
    line(OK, "Google sign-in", "client id and secret look right")


def main() -> int:
    _load_local_secrets()
    print("Checking keys. No secret values are printed.\n")
    for check in (check_supabase, check_llm, check_jsearch, check_adzuna,
                  check_jooble, check_sign_in):
        check()
    print("\nAnything marked FAIL stops that feature only - the rest still runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
