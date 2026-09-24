"""Manage personal invite links in .streamlit/secrets.toml.

    .venv/bin/python scripts/invites.py add friend
    .venv/bin/python scripts/invites.py links https://your-app.streamlit.app
    .venv/bin/python scripts/invites.py revoke friend
    .venv/bin/python scripts/invites.py list

Tokens are written straight into the gitignored secrets file. Only `links`
prints them, in your own terminal, because a link is as good as a password.
After any change, paste the updated secrets into Streamlit Cloud
(App settings -> Secrets) so the live app sees it.
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
import tomllib
from pathlib import Path

SECRETS = Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._@+-]{0,60}$")


def _read() -> str:
    if not SECRETS.exists():
        sys.exit(f"No {SECRETS}. Copy secrets.toml.example to it first.")
    return SECRETS.read_text(encoding="utf-8")


def _table(text: str) -> dict[str, str]:
    return {str(k): str(v) for k, v in tomllib.loads(text).get("invites", {}).items()}


def _write_table(text: str, table: dict[str, str]) -> str:
    """Replace the [invites] section, or append one at the end."""
    lines = text.splitlines()
    body = [f'"{label}" = "{token}"' for label, token in sorted(table.items())]

    start = next((i for i, line in enumerate(lines) if line.strip() == "[invites]"), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["# Personal links - managed by scripts/invites.py", "[invites]", *body]
    else:
        end = start + 1
        while end < len(lines) and not lines[end].lstrip().startswith("["):
            end += 1
        # Keep trailing comments/blank lines that belong to the next section.
        lines[start + 1:end] = body + [""]
    result = "\n".join(lines).rstrip() + "\n"
    tomllib.loads(result)  # refuse to save a file Streamlit could not read
    return result


def _label(raw: str) -> str:
    label = raw.strip().lower()
    if not LABEL_RE.match(label):
        sys.exit("Use a short name like 'friend' or an email address.")
    return label


def cmd_add(args: argparse.Namespace) -> None:
    text = _read()
    table = _table(text)
    label = _label(args.label)
    if label in table:
        sys.exit(f"'{label}' already has a link. Use 'revoke' to replace it.")
    table[label] = secrets.token_urlsafe(32)
    SECRETS.write_text(_write_table(text, table), encoding="utf-8")
    print(f"Added a link for '{label}'. Print it with: invites.py links <app url>")


def cmd_revoke(args: argparse.Namespace) -> None:
    text = _read()
    table = _table(text)
    label = _label(args.label)
    if label not in table:
        sys.exit(f"No link for '{label}'.")
    table[label] = secrets.token_urlsafe(32)
    SECRETS.write_text(_write_table(text, table), encoding="utf-8")
    print(f"Replaced the link for '{label}'. The old one stops working once "
          "you paste the new secrets into Streamlit Cloud.")


def cmd_list(_: argparse.Namespace) -> None:
    table = _table(_read())
    if not table:
        print("No invites yet. Add one with: invites.py add friend")
    for label in sorted(table):
        print(f"- {label}")


def cmd_links(args: argparse.Namespace) -> None:
    table = _table(_read())
    base = args.app_url.rstrip("/")
    if not base.startswith("https://"):
        sys.exit("Give the full app address, e.g. https://job-seeker.streamlit.app")
    for label, token in sorted(table.items()):
        print(f"{label}: {base}/?invite={token}")
    print("\nSend each person only their own line. Treat it like a password.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="create a link for someone")
    add.add_argument("label")
    add.set_defaults(func=cmd_add)
    revoke = sub.add_parser("revoke", help="replace someone's link")
    revoke.add_argument("label")
    revoke.set_defaults(func=cmd_revoke)
    sub.add_parser("list", help="who has a link").set_defaults(func=cmd_list)
    links = sub.add_parser("links", help="print the links for your app")
    links.add_argument("app_url")
    links.set_defaults(func=cmd_links)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
