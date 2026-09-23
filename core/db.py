"""Supabase access, scoped to one user at a time.

Every read and write goes through here so that the ``user_id`` filter can
never be forgotten in a page. The service role key is used, which bypasses
RLS, so this module is the security boundary.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from . import config

RESUME_BUCKET = "resumes"
GENERATED_BUCKET = "generated"


class NotConfigured(RuntimeError):
    pass


@lru_cache(maxsize=1)
def client() -> Client:
    url, key = config.supabase_url(), config.supabase_service_key()
    if not url or not key:
        raise NotConfigured(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY are missing. "
            "Add them to .streamlit/secrets.toml (see README)."
        )
    return create_client(url, key)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ------------------------------------------------------------------- users
def get_or_create_user(email: str, display_name: str | None = None) -> dict[str, Any]:
    email = email.strip().lower()
    found = client().table("app_user").select("*").eq("email", email).execute().data
    if found:
        user = found[0]
        client().table("app_user").update({"last_seen_at": _now()}).eq("id", user["id"]).execute()
        return user
    created = client().table("app_user").insert(
        {"email": email, "display_name": display_name}
    ).execute().data[0]
    client().table("profile").insert({"user_id": created["id"]}).execute()
    return created


def list_users() -> list[dict[str, Any]]:
    """Used by the nightly discovery run."""
    return client().table("app_user").select("id, email").execute().data or []


# ----------------------------------------------------------------- profile
def get_profile(user_id: str) -> dict[str, Any]:
    rows = client().table("profile").select("*").eq("user_id", user_id).execute().data
    if rows:
        return rows[0]
    return client().table("profile").insert({"user_id": user_id}).execute().data[0]


def save_profile(user_id: str, **fields: Any) -> dict[str, Any]:
    fields["updated_at"] = _now()
    return client().table("profile").update(fields).eq("user_id", user_id).execute().data[0]


def upload_resume(user_id: str, filename: str, data: bytes,
                  content_type: str = "application/pdf") -> str:
    path = f"{user_id}/{filename}"
    client().storage.from_(RESUME_BUCKET).upload(
        path, data, {"content-type": content_type, "upsert": "true"}
    )
    return path


def store_generated(user_id: str, filename: str, data: bytes, content_type: str) -> str:
    path = f"{user_id}/{filename}"
    client().storage.from_(GENERATED_BUCKET).upload(
        path, data, {"content-type": content_type, "upsert": "true"}
    )
    return path


# -------------------------------------------------------------------- jobs
def upsert_jobs(user_id: str, jobs: list[dict[str, Any]]) -> int:
    """Insert new jobs, skipping fingerprints this user has already seen."""
    if not jobs:
        return 0
    existing = {
        row["fingerprint"]
        for row in client().table("job").select("fingerprint")
        .eq("user_id", user_id).execute().data or []
    }
    fresh, seen = [], set()
    for job in jobs:
        fp = job["fingerprint"]
        if fp in existing or fp in seen:
            continue
        seen.add(fp)
        fresh.append({**job, "user_id": user_id})
    if not fresh:
        return 0
    client().table("job").insert(fresh).execute()
    return len(fresh)


def list_jobs(user_id: str, statuses: list[str] | None = None,
              limit: int = 100) -> list[dict[str, Any]]:
    query = client().table("job").select("*").eq("user_id", user_id)
    if statuses:
        query = query.in_("status", statuses)
    return query.order("score", desc=True).limit(limit).execute().data or []


def get_job(user_id: str, job_id: str) -> dict[str, Any] | None:
    rows = (client().table("job").select("*")
            .eq("user_id", user_id).eq("id", job_id).execute().data)
    return rows[0] if rows else None


def set_job_status(user_id: str, job_id: str, status: str) -> None:
    (client().table("job").update({"status": status})
     .eq("user_id", user_id).eq("id", job_id).execute())


def delete_jobs(user_id: str, statuses: list[str]) -> None:
    (client().table("job").delete()
     .eq("user_id", user_id).in_("status", statuses).execute())


# --------------------------------------------------------------- tailoring
def get_tailoring(user_id: str, job_id: str) -> dict[str, Any] | None:
    rows = (client().table("tailoring").select("*")
            .eq("user_id", user_id).eq("job_id", job_id).execute().data)
    return rows[0] if rows else None


def save_tailoring(user_id: str, job_id: str, **fields: Any) -> dict[str, Any]:
    payload = {"user_id": user_id, "job_id": job_id, "updated_at": _now(), **fields}
    return (client().table("tailoring")
            .upsert(payload, on_conflict="user_id,job_id").execute().data[0])


# ------------------------------------------------------------------ quota
def log_usage(user_id: str | None, kind: str, tokens: int = 0) -> None:
    try:
        client().table("usage_log").insert(
            {"user_id": user_id, "kind": kind, "calls": 1, "tokens": tokens}
        ).execute()
    except Exception:
        # Usage accounting must never break the feature it is measuring.
        pass


def usage_today(user_id: str, kind: str = "llm") -> int:
    today = dt.date.today().isoformat()
    rows = (client().table("usage_log").select("calls")
            .eq("user_id", user_id).eq("kind", kind).eq("day", today)
            .execute().data or [])
    return sum(int(row.get("calls") or 0) for row in rows)


# ------------------------------------------------------------ hard delete
def delete_everything(user_id: str, email: str) -> dict[str, int]:
    """Wipe this user's rows and stored files. Irreversible, by design."""
    removed_files = 0
    for bucket in (RESUME_BUCKET, GENERATED_BUCKET):
        try:
            objects = client().storage.from_(bucket).list(user_id) or []
            paths = [f"{user_id}/{obj['name']}" for obj in objects]
            if paths:
                client().storage.from_(bucket).remove(paths)
                removed_files += len(paths)
        except Exception:
            pass
    # ON DELETE CASCADE clears profile, job, tailoring, application, usage_log.
    client().table("app_user").delete().eq("email", email.lower()).execute()
    return {"files": removed_files}
