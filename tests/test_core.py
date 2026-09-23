"""Smoke tests for the pieces that must not silently rot.

Run them with the project venv and no extra dependencies:

    .venv/bin/python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
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
