"""Copy the keys the daily cron needs from secrets.toml into GitHub Actions.

    .venv/bin/python scripts/sync_actions_secrets.py

Uses the `gh` CLI you are already signed in to. Values go from the file to
GitHub over stdin and are never printed. Keys that are empty locally are
skipped, so running it again after adding Adzuna or Jooble is safe.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

REPO = "johnthebasemaker/Job-Seeker"
SECRETS = Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"

#: Exactly what .github/workflows/discover.yml reads.
NEEDED = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "JSEARCH_API_KEY",
    "ADZUNA_APP_ID",
    "ADZUNA_APP_KEY",
    "JOOBLE_API_KEY",
]


def main() -> int:
    if not SECRETS.exists():
        sys.exit(f"No {SECRETS}")
    values = tomllib.loads(SECRETS.read_text(encoding="utf-8"))
    done, skipped = [], []
    for name in NEEDED:
        value = str(values.get(name) or "").strip()
        if not value or "YOUR-PROJECT" in value:
            skipped.append(name)
            continue
        result = subprocess.run(
            ["gh", "secret", "set", name, "-R", REPO],
            input=value, text=True, capture_output=True,
        )
        if result.returncode != 0:
            print(f"  failed  {name}: {result.stderr.strip()[:200]}")
            continue
        done.append(name)
    for name in done:
        print(f"  set     {name}")
    for name in skipped:
        print(f"  skipped {name} (empty in secrets.toml)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
