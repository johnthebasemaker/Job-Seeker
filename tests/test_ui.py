"""Run every Streamlit page headlessly with a fake database.

This catches the things unit tests miss: a renamed Streamlit argument, a bad
session-state key, a page that blows up before it draws anything. No network
and no Supabase project are needed.

    .venv/bin/python -m unittest tests.test_ui -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_DEV_MODE", "true")
os.environ.setdefault("DEV_USER_EMAIL", "dev@localhost")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "not-a-real-key")

from streamlit.testing.v1 import AppTest  # noqa: E402

from core import db  # noqa: E402
from tests.test_core import CONTACT, JOB, SAMPLE_MD  # noqa: E402

USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "dev@localhost",
        "display_name": "Dev"}

PROFILE = {
    "user_id": USER["id"],
    "contact": CONTACT,
    "base_resume_md": SAMPLE_MD,
    "prefs": {
        "country": "IN",
        "titles": ["Python Backend Developer"],
        "locations": ["Chennai"],
        "seniority": "mid",
        "keywords": ["fastapi"],
        "exclude": [],
        "sources": {"jsearch": True, "adzuna": True, "jooble": True, "ats": True},
        "ats_companies": [],
    },
    "answer_bank": {"notice_period": "30 days"},
}

JOB_ROW = dict(
    JOB,
    id="22222222-2222-2222-2222-222222222222",
    user_id=USER["id"],
    fingerprint="abc",
    source="jsearch",
    source_label="Indeed (via JSearch)",
    is_indeed=True,
    apply_url="https://in.indeed.com/viewjob?jk=1",
    apply_kind="indeed_easy_apply",
    status="new",
    score=72,
    score_detail={"title": 40, "skills": 20, "location": 15, "freshness": 9,
                  "matched_skills": ["python", "fastapi"],
                  "missing_skills": ["kubernetes"],
                  "reasons": ["Title matches python, developer"]},
)


SIGNED_IN: list[str] = []


class FakeDB:
    """Just enough of core.db for the pages to render."""

    @staticmethod
    def get_or_create_user(email, display_name=None):
        SIGNED_IN.append(email)
        return USER

    @staticmethod
    def get_profile(user_id):
        return PROFILE

    @staticmethod
    def save_profile(user_id, **fields):
        PROFILE.update(fields)
        return PROFILE

    @staticmethod
    def list_jobs(user_id, statuses=None, limit=100):
        return [JOB_ROW] if not statuses or JOB_ROW["status"] in statuses else []

    @staticmethod
    def get_job(user_id, job_id):
        return JOB_ROW

    @staticmethod
    def set_job_status(user_id, job_id, status):
        JOB_ROW["status"] = status

    @staticmethod
    def get_tailoring(user_id, job_id):
        return None

    @staticmethod
    def save_tailoring(user_id, job_id, **fields):
        return fields

    @staticmethod
    def usage_today(user_id, kind="llm"):
        return 3

    @staticmethod
    def log_usage(user_id, kind, tokens=0):
        return None

    @staticmethod
    def upsert_jobs(user_id, rows):
        return len(rows)

    @staticmethod
    def list_users():
        return [USER]

    @staticmethod
    def upload_resume(user_id, filename, data, content_type="application/pdf"):
        return f"{user_id}/{filename}"

    @staticmethod
    def delete_everything(user_id, email):
        return {"files": 0}

    @staticmethod
    def list_applications(user_id):
        return []

    @staticmethod
    def record_application(user_id, job_id, **kwargs):
        return {"job_id": job_id}


def _install_fake_db() -> dict:
    originals = {}
    for name in dir(FakeDB):
        if name.startswith("_"):
            continue
        originals[name] = getattr(db, name, None)
        setattr(db, name, getattr(FakeDB, name))
    return originals


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = _install_fake_db()

    @classmethod
    def tearDownClass(cls):
        for name, value in cls.originals.items():
            if value is not None:
                setattr(db, name, value)

    def _run(self, path: str) -> AppTest:
        app = AppTest.from_file(str(ROOT / path), default_timeout=30)
        app.run()
        if app.exception:
            self.fail(f"{path} raised: {[e.message for e in app.exception]}")
        return app

    def test_entrypoint_renders(self):
        app = self._run("app.py")
        self.assertTrue(app.title, "the app should render a title")

    def test_profile_page(self):
        app = self._run("views/onboarding.py")
        self.assertIn("Profile", [t.value for t in app.title])

    def test_jobs_page_lists_a_job(self):
        app = self._run("views/jobs.py")
        text = " ".join([m.value for m in app.markdown] + [c.value for c in app.caption])
        self.assertIn("Python Backend Developer", text)
        self.assertIn("Indeed", text, "the source label should be visible")
        self.assertIn("kubernetes", text.lower())

    def test_tailor_page_builds_report(self):
        app = self._run("views/tailor.py")
        labels = [m.label for m in app.metric]
        self.assertIn("Match score", labels)
        self.assertIn("Keyword coverage", labels)

    def test_apply_page_offers_the_helper(self):
        JOB_ROW["status"] = "ready"
        app = self._run("views/apply.py")
        text = " ".join([m.value for m in app.markdown] + [c.value for c in app.caption])
        self.assertIn("Submit", text, "the page must say who presses Submit")
        labels = [b.label for b in app.button]
        self.assertIn("Build apply pack", labels)
        JOB_ROW["status"] = "new"

    def test_settings_page(self):
        app = self._run("views/settings.py")
        text = " ".join(m.value for m in app.markdown)
        self.assertIn("Delete everything", " ".join(h.value for h in app.subheader) + text)


class InviteLinkTests(unittest.TestCase):
    """The shared-link sign-in, with dev mode off."""

    TOKEN = "t" * 43

    @classmethod
    def setUpClass(cls):
        cls.originals = _install_fake_db()

    @classmethod
    def tearDownClass(cls):
        for name, value in cls.originals.items():
            if value is not None:
                setattr(db, name, value)

    def setUp(self):
        self._dev = os.environ.get("APP_DEV_MODE")
        os.environ["APP_DEV_MODE"] = "false"
        SIGNED_IN.clear()

    def tearDown(self):
        os.environ["APP_DEV_MODE"] = self._dev or "true"

    def _app(self, invite: str | None) -> AppTest:
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
        app.secrets["invites"] = {"friend": self.TOKEN}
        if invite is not None:
            app.query_params["invite"] = invite
        app.run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        return app

    def _text(self, app: AppTest) -> str:
        return " ".join([m.value for m in app.markdown] + [c.value for c in app.caption])

    def test_valid_link_opens_the_app_as_that_person(self):
        app = self._app(self.TOKEN)
        self.assertEqual(SIGNED_IN, ["friend@invite.local"])
        self.assertIn("Jobs", [t.value for t in app.title])

    def test_wrong_link_is_refused(self):
        app = self._app("x" * 43)
        self.assertEqual(SIGNED_IN, [])
        self.assertIn("not valid", self._text(app))

    def test_no_link_and_no_google_shows_invite_only(self):
        app = self._app(None)
        self.assertEqual(SIGNED_IN, [])
        self.assertIn("invite-only", self._text(app))


if __name__ == "__main__":
    unittest.main()
