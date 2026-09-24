"""Smoke tests for the pieces that must not silently rot.

Run them with the project venv and no extra dependencies:

    .venv/bin/python -m unittest discover -s tests -v
"""

from __future__ import annotations

import base64
import io
import json
import sys
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import match, privacy, render, resume, tailor  # noqa: E402
from core.jobs import base, dedupe  # noqa: E402

SAMPLE_MD = """## Summary
Backend developer with three years building APIs.

## Skills
- Python, FastAPI, PostgreSQL, Docker

## Experience

### Backend Developer - Acme Technologies
Chennai, India | Jun 2022 - Present
- Built 14 REST endpoints used by 30,000 users a month.
- Cut p95 latency by 40% by adding Redis caching.

### Intern - Beta Labs
Chennai | Jan 2022 - May 2022
- Wrote pytest suites for the billing module.

## Education

### B.E. Computer Science - Anna University
Chennai | 2018 - 2022
"""

CONTACT = {
    "full_name": "Priya Raman",
    "email": "priya.raman@example.com",
    "phone": "+91 98765 43210",
    "linkedin": "https://linkedin.com/in/priyaraman",
}

JOB = {
    "title": "Python Backend Developer",
    "company": "Nimbus Systems",
    "location": "Chennai, Tamil Nadu",
    "country": "IN",
    "is_remote": False,
    "posted_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
    "description": (
        "We need a Python developer with FastAPI and PostgreSQL experience. "
        "Kubernetes and Kafka are a plus. You will own REST API design. "
        "Kubernetes clusters run our services; Kubernetes knowledge helps."
    ),
}


class PrivacyTests(unittest.TestCase):
    def test_round_trip(self):
        text = "Priya Raman, priya.raman@example.com, +91 98765 43210"
        redaction = privacy.redact(text, ["Priya Raman"])
        self.assertNotIn("Priya", redaction.text)
        self.assertNotIn("example.com", redaction.text)
        self.assertNotIn("98765", redaction.text)
        self.assertEqual(redaction.restore(redaction.text), text)

    def test_metrics_survive_redaction(self):
        redaction = privacy.redact("Cut p95 latency by 40% and served 30,000 users in 2022")
        self.assertIn("40%", redaction.text)
        self.assertIn("2022", redaction.text)

    def test_split_contact(self):
        raw = ("Priya Raman\npriya.raman@example.com | +91 98765 43210\n"
               "https://linkedin.com/in/priyaraman\n\nSummary\nBackend developer.")
        contact, remaining = privacy.split_contact(raw)
        self.assertEqual(contact["full_name"], "Priya Raman")
        self.assertEqual(contact["email"], "priya.raman@example.com")
        self.assertIn("linkedin", contact)
        self.assertNotIn("priya.raman@example.com", remaining)


class ResumeTests(unittest.TestCase):
    def test_parse_structure(self):
        sections = resume.parse(SAMPLE_MD)
        titles = [s.title for s in sections]
        self.assertEqual(titles, ["Summary", "Skills", "Experience", "Education"])
        experience = sections[2]
        self.assertEqual(len(experience.entries), 2)
        self.assertEqual(experience.entries[0].meta, "Chennai, India | Jun 2022 - Present")
        self.assertEqual(len(experience.entries[0].bullets), 2)

    def test_naive_markdown_has_sections(self):
        markdown = resume.naive_markdown("Summary\nDid things\nSkills\nPython")
        self.assertIn("## Summary", markdown)
        self.assertIn("## Skills", markdown)


class RenderTests(unittest.TestCase):
    def test_typst_escapes_markup(self):
        source = render.typst_source('## Skills\n- C# and "quotes" #hash $dollar\n', CONTACT)
        self.assertIn('\\"quotes\\"', source)
        self.assertIn("Priya Raman", source)

    def test_pdf_bytes(self):
        pdf = render.resume_pdf(SAMPLE_MD, CONTACT)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 3000)

    def test_docx_bytes(self):
        docx = render.resume_docx(SAMPLE_MD, CONTACT)
        self.assertTrue(docx.startswith(b"PK"))

    def test_filename(self):
        name = render.safe_filename(CONTACT, {"company": "Nimbus Systems", "title": "Dev"}, "pdf")
        self.assertEqual(name, "Priya_Raman_Nimbus_Systems_Dev.pdf")


class MatchTests(unittest.TestCase):
    def test_extract_skills(self):
        skills = match.extract_skills(SAMPLE_MD)
        self.assertIn("python", skills)
        self.assertIn("fastapi", skills)
        self.assertIn("postgresql", skills)

    def test_score_prefers_matching_title(self):
        prefs = {"titles": ["Python Backend Developer"], "locations": ["Chennai"],
                 "country": "IN", "seniority": "mid"}
        user_skills = match.extract_skills(SAMPLE_MD)
        good, detail = match.score_job(JOB, prefs, user_skills)
        off_topic = dict(JOB, title="Senior Sales Manager",
                         description="Cold calling and CRM targets in Dubai.")
        bad, _ = match.score_job(off_topic, prefs, user_skills)
        self.assertGreater(good, bad)
        self.assertIn("fastapi", detail["matched_skills"])
        self.assertIn("kubernetes", detail["missing_skills"])

    def test_keyword_report(self):
        report = match.keyword_report(SAMPLE_MD, JOB["description"], JOB["title"])
        self.assertIn("fastapi", report["matched"])
        self.assertIn("kubernetes", report["missing"])
        self.assertLessEqual(report["coverage"], 100)

    def test_skill_gap_counts_jobs(self):
        gaps = match.skill_gap([JOB, JOB], match.extract_skills(SAMPLE_MD))
        by_skill = {g["skill"]: g for g in gaps}
        self.assertEqual(by_skill["kubernetes"]["jobs_unlocked"], 2)
        self.assertTrue(by_skill["kubernetes"]["resources"])

    def test_ats_checks_flags_tables(self):
        checks = match.ats_checks(SAMPLE_MD + "\n| a | b |\n", CONTACT)
        tables = [c for c in checks if c["label"] == "No tables"][0]
        self.assertEqual(tables["ok"], "no")


class JobTests(unittest.TestCase):
    def test_fingerprint_collapses_duplicates(self):
        one = base.Job(source="jsearch", source_label="Indeed (via JSearch)",
                       title="Python Developer", company="Acme Technologies Pvt Ltd",
                       location="Chennai, Tamil Nadu", description="a" * 50,
                       is_indeed=True)
        two = base.Job(source="adzuna", source_label="Adzuna",
                       title="Python Developer (Job ID 4821)", company="Acme Technologies",
                       location="Chennai", description="b" * 500)
        self.assertEqual(one.fingerprint, two.fingerprint)
        merged = dedupe([two, one])
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0].is_indeed, "Indeed listing should win a tie")

    def test_classify_apply(self):
        kind, is_indeed = base.classify_apply("https://in.indeed.com/viewjob?jk=123")
        self.assertEqual(kind, "indeed_easy_apply")
        self.assertTrue(is_indeed)
        self.assertEqual(base.classify_apply("https://jobs.lever.co/acme/1")[0], "lever")
        self.assertEqual(base.classify_apply("https://careers.example.com/1")[0], "external")

    def test_html_to_text(self):
        self.assertEqual(base.html_to_text("<p>Hello &amp; welcome</p>"), "Hello & welcome")


class TailorTests(unittest.TestCase):
    def test_fabrication_warnings_flag_new_claims(self):
        rewritten = SAMPLE_MD.replace(
            "- Wrote pytest suites for the billing module.",
            "- Ran Kubernetes clusters serving 99.99% uptime.",
        )
        warnings = tailor.fabrication_warnings(SAMPLE_MD, rewritten, JOB["description"])
        kinds = {w["kind"] for w in warnings}
        values = {w["value"] for w in warnings}
        self.assertIn("skill", kinds)
        self.assertIn("kubernetes", values)
        self.assertIn("99.99%", values)

    def test_no_warnings_for_pure_rewording(self):
        rewritten = SAMPLE_MD.replace(
            "- Built 14 REST endpoints used by 30,000 users a month.",
            "- Designed and shipped 14 REST endpoints serving 30,000 users a month.",
        )
        self.assertEqual(tailor.fabrication_warnings(SAMPLE_MD, rewritten), [])

    def test_apply_suggestion_replaces_line(self):
        suggestion = {
            "original": "- Cut p95 latency by 40% by adding Redis caching.",
            "proposed": "- Cut p95 API latency by 40% with Redis caching.",
        }
        updated, applied = tailor.apply_suggestion(SAMPLE_MD, suggestion)
        self.assertTrue(applied)
        self.assertIn("Cut p95 API latency", updated)

    def test_apply_suggestion_without_bullet_prefix(self):
        suggestion = {
            "original": "Wrote pytest suites for the billing module.",
            "proposed": "Wrote pytest suites covering the billing module.",
        }
        updated, applied = tailor.apply_suggestion(SAMPLE_MD, suggestion)
        self.assertTrue(applied)
        self.assertIn("covering the billing module", updated)


if __name__ == "__main__":
    unittest.main()


class PackTests(unittest.TestCase):
    """The apply pack is what the browser helper reads."""

    PROFILE = {"contact": CONTACT, "base_resume_md": SAMPLE_MD,
               "answer_bank": {"notice_period": "30 days",
                               "custom": [{"q": "How did you hear about us?",
                                           "a": "Through a friend"}]}}
    JOB_ROW = dict(JOB, id="job-1", apply_url="https://in.indeed.com/viewjob?jk=1",
                   apply_kind="indeed_easy_apply", source_label="Indeed (via JSearch)")

    def test_build_embeds_a_real_pdf(self):
        from core import pack

        built = pack.build(self.PROFILE, [self.JOB_ROW])
        self.assertEqual(built["version"], 1)
        self.assertEqual(len(built["jobs"]), 1)
        entry = built["jobs"][0]
        self.assertEqual(entry["apply_kind"], "indeed_easy_apply")
        self.assertTrue(base64.b64decode(entry["resume_pdf_b64"]).startswith(b"%PDF"))
        self.assertTrue(entry["resume_filename"].endswith(".pdf"))

    def test_contact_travels_but_nothing_else_does(self):
        from core import pack

        built = pack.build(self.PROFILE, [self.JOB_ROW])
        self.assertEqual(built["profile"]["email"], CONTACT["email"])
        self.assertEqual(built["answers"]["notice_period"], "30 days")
        # The pack is for form filling, so it must not carry the job description
        # or the chat history around.
        self.assertNotIn("description", built["jobs"][0])

    def test_tailored_draft_wins_over_the_base_resume(self):
        from core import pack

        tailored = SAMPLE_MD.replace("Backend developer", "Senior backend developer")
        built = pack.build(self.PROFILE, [self.JOB_ROW], {"job-1": tailored})
        self.assertGreater(len(built["jobs"][0]["resume_pdf_b64"]), 100)

    def test_round_trips_as_json(self):
        from core import pack

        data = pack.to_bytes(pack.build(self.PROFILE, [self.JOB_ROW]))
        self.assertEqual(json.loads(data)["jobs"][0]["id"], "job-1")
        self.assertIsNone(pack.size_warning(data))


class ExtensionTests(unittest.TestCase):
    """Catch a manifest that points at a file nobody shipped."""

    ROOT = Path(__file__).resolve().parents[1] / "extension"

    def setUp(self):
        self.manifest = json.loads((self.ROOT / "manifest.json").read_text())

    def test_every_referenced_file_exists(self):
        referenced = [self.manifest["action"]["default_popup"]]
        referenced += list(self.manifest["icons"].values())
        for block in self.manifest["content_scripts"]:
            referenced += block.get("js", []) + block.get("css", [])
        for relative in referenced:
            self.assertTrue((self.ROOT / relative).is_file(), f"missing {relative}")

    def test_popup_loads_its_script(self):
        html = (self.ROOT / "popup.html").read_text()
        self.assertIn('src="popup.js"', html)
        self.assertNotIn("onclick=", html, "inline handlers break the extension CSP")

    def test_content_script_covers_the_same_sites(self):
        matches = set(self.manifest["content_scripts"][0]["matches"])
        self.assertEqual(matches, set(self.manifest["host_permissions"]))

    def test_it_never_presses_submit(self):
        source = (self.ROOT / "content" / "fill.js").read_text()
        for forbidden in ("form.submit(", ".requestSubmit(", 'type="submit"]'):
            self.assertNotIn(forbidden, source)
        self.assertIn("never clicks Submit", source)

    def test_zip_contains_the_manifest(self):
        from core import pack

        data = pack.extension_zip()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
        self.assertIn("extension/manifest.json", names)
        self.assertIn("extension/content/fill.js", names)


class AuthTests(unittest.TestCase):
    """Personal invite links: the right person in, everyone else out."""

    TABLE = {"friend": "f" * 43, "owner": "o" * 43, "broken": "short"}

    def test_matching_token_signs_in_that_person(self):
        from core import auth

        self.assertEqual(auth.match_invite("f" * 43, self.TABLE), "friend")
        self.assertEqual(auth.match_invite("o" * 43, self.TABLE), "owner")

    def test_wrong_or_missing_token_is_refused(self):
        from core import auth

        self.assertIsNone(auth.match_invite("x" * 43, self.TABLE))
        self.assertIsNone(auth.match_invite("", self.TABLE))
        self.assertIsNone(auth.match_invite(None, self.TABLE))

    def test_short_tokens_never_work(self):
        from core import auth

        # A too-short token in secrets must not become a guessable way in.
        self.assertIsNone(auth.match_invite("short", self.TABLE))
        self.assertIsNone(auth.match_invite("f" * 10, {"friend": "f" * 10}))

    def test_labels_become_stable_account_keys(self):
        from core import auth

        self.assertEqual(auth.identity_for("Friend"), "friend@invite.local")
        self.assertEqual(auth.identity_for("Priya@Gmail.com"), "priya@gmail.com")


class JSearchTests(unittest.TestCase):
    """JSearch v5: /search-v2, results under data.jobs, cursor paging."""

    ITEM = {
        "job_title": "Python Developer", "employer_name": "Acme", "job_city": "Chennai",
        "job_state": "Tamil Nadu", "job_country": "IN", "job_description": "Python, FastAPI",
        "job_publisher": "LinkedIn", "job_apply_link": "https://linkedin.com/jobs/1",
        "job_salary_string": "INR 6-9 LPA",
        "apply_options": [
            {"publisher": "LinkedIn", "apply_link": "https://linkedin.com/jobs/1"},
            {"publisher": "Indeed", "apply_link": "https://in.indeed.com/viewjob?jk=1"},
        ],
    }

    def _response(self, body, status=200):
        from unittest import mock

        response = mock.Mock(status_code=status, ok=status < 400)
        response.json.return_value = body
        response.raise_for_status = mock.Mock()
        return response

    def test_reads_v2_shape_and_prefers_indeed(self):
        import os
        from unittest import mock

        from core.jobs import jsearch

        body = {"status": "OK", "data": {"jobs": [self.ITEM], "cursor": None}}
        with mock.patch.dict(os.environ, {"JSEARCH_API_KEY": "k"}), \
                mock.patch.object(jsearch.requests, "get", return_value=self._response(body)) as get:
            jobs = jsearch.search("python developer in Chennai", "IN")
        self.assertTrue(get.call_args.args[0].endswith("/search-v2"))
        self.assertNotIn("page", get.call_args.kwargs["params"])
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0].is_indeed, "the Indeed apply option should win")
        self.assertEqual(jobs[0].apply_kind, "indeed_easy_apply")
        self.assertEqual(jobs[0].salary_text, "INR 6-9 LPA")

    def test_follows_the_cursor_for_extra_pages(self):
        import os
        from unittest import mock

        from core.jobs import jsearch

        pages = [
            self._response({"data": {"jobs": [self.ITEM], "cursor": "next-1"}}),
            self._response({"data": {"jobs": [self.ITEM], "cursor": None}}),
        ]
        with mock.patch.dict(os.environ, {"JSEARCH_API_KEY": "k"}), \
                mock.patch.object(jsearch.requests, "get", side_effect=pages) as get:
            jobs = jsearch.search("q", "IN", pages=3)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(get.call_count, 2, "stops when the cursor runs out")
        self.assertEqual(get.call_args_list[1].kwargs["params"]["cursor"], "next-1")

    def test_quota_exhausted_returns_nothing_quietly(self):
        import os
        from unittest import mock

        from core.jobs import jsearch

        with mock.patch.dict(os.environ, {"JSEARCH_API_KEY": "k"}), \
                mock.patch.object(jsearch.requests, "get", return_value=self._response({}, 429)):
            self.assertEqual(jsearch.search("q", "IN"), [])
