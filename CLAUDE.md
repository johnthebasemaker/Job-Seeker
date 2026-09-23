# Job Seeker - working rules

Read `README.md` first for the architecture. These are the rules that are
easy to break by accident.

## Non-negotiable

* **Never build bot-detection evasion.** No stealth fingerprinting, proxy
  rotation, CAPTCHA solving or headless logins to Indeed. The application
  step is always: the app prepares, the person clicks Submit in their own
  browser. If a feature needs evasion to work, the feature is wrong.
* **Nothing personal reaches an LLM.** Anything sent to a model goes through
  `core/privacy.Redactor` first, and comes back through `.restore()`.
  Contact details belong in `profile.contact`, never in the resume markdown.
* **Numbers are computed, not generated.** Match scores, ATS coverage and
  skill counts come from `core/match.py`. A model may write prose about them
  and nothing else.
* **The AI may not invent experience.** Every tailored draft is diffed
  against the base resume by `tailor.fabrication_warnings` and new claims are
  shown to the user before saving.

* **The helper never submits and never guesses.** `extension/content/fill.js`
  must not click submit/apply/continue, must skip demographic questions, and
  must list anything it has no saved answer for instead of filling it.
  `tests/test_core.py::ExtensionTests` enforces the first part.

## Conventions

* Canonical resume format is the markdown in `core/resume.py`'s docstring:
  `## Section`, `### Role - Employer`, a meta line, then `- ` bullets. Both
  renderers and the editor depend on it.
* All Supabase access goes through `core/db.py`, which scopes every query by
  `user_id`. Never call the client from a page.
* `core/` must import cleanly without Streamlit - GitHub Actions imports it.
* Free-tier discipline: every new API call needs a budget and a graceful
  path when the quota is gone.

## Commands

```bash
.venv/bin/python -m unittest discover -s tests -v   # 35 tests, no network
node extension/tests/rules.test.js                  # form-filling rules
.venv/bin/python scripts/check_keys.py              # one live call per key
.venv/bin/streamlit run app.py                      # needs .streamlit/secrets.toml
.venv/bin/python scripts/discover.py --user <uuid>  # one discovery run
```

Secrets live in `.streamlit/secrets.toml` (gitignored) and in the Streamlit
Cloud and GitHub Actions secret stores. Never commit a key.
