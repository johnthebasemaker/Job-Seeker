"""Daily job discovery, run by GitHub Actions.

Keeps the Streamlit app fast (it only reads rows) and keeps the Supabase free
tier awake. Prints counts only - never an email address or a resume line,
because workflow logs are not a private place.

    python scripts/discover.py            # every user
    python scripts/discover.py --user <uuid>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config, db, jobs as jobs_api, match  # noqa: E402


def run_for_user(user_id: str) -> int:
    profile = db.get_profile(user_id)
    prefs = profile.get("prefs") or {}
    if not prefs.get("titles"):
        print(f"  {user_id[:8]}: no job titles set, skipping")
        return 0

    found = jobs_api.discover(prefs, log=lambda line: print(f"    {line}"))
    if not found:
        print(f"  {user_id[:8]}: nothing found")
        return 0

    user_skills = match.extract_skills(profile.get("base_resume_md") or "",
                                       " ".join(prefs.get("keywords", [])))
    for job in found:
        job.score, job.score_detail = match.score_job(job, prefs, user_skills)
    found.sort(key=lambda j: j.score, reverse=True)
    keep = found[: max(config.daily_job_target() * 2, 20)]

    added = db.upsert_jobs(user_id, [job.to_row() for job in keep])
    print(f"  {user_id[:8]}: {len(found)} found, {added} new")
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch jobs for every user")
    parser.add_argument("--user", help="Only run for this user id")
    args = parser.parse_args()

    users = ([{"id": args.user}] if args.user else db.list_users())
    if not users:
        print("No users yet.")
        return 0

    print(f"Running discovery for {len(users)} user(s)")
    total = 0
    for user in users:
        try:
            total += run_for_user(user["id"])
        except Exception as exc:  # one broken profile must not stop the rest
            print(f"  {user['id'][:8]}: failed - {type(exc).__name__}: {exc}")
    print(f"Done. {total} new jobs stored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
