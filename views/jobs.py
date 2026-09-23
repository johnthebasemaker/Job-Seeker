"""Jobs: run discovery, browse what came back, see the skill gaps."""

from __future__ import annotations

import streamlit as st

from core import auth, config, db, jobs as jobs_api, match
from views import _shared

user = auth.require_login()
profile = _shared.profile_for(user)
prefs = _shared.prefs_of(profile)

st.title("Jobs")

if not prefs.get("titles"):
    st.info("Tell us which roles you want on the Profile page, then come back.")
    if st.button("Go to Profile"):
        _shared.goto("profile")
    st.stop()

user_skills = match.extract_skills(profile.get("base_resume_md") or "",
                                   " ".join(prefs.get("keywords", [])))


def run_discovery() -> None:
    with st.status("Searching...", expanded=True) as status:
        lines: list[str] = []

        def log(message: str) -> None:
            lines.append(message)
            status.write(message)

        try:
            found = jobs_api.discover(prefs, log=log)
        except Exception as exc:
            status.update(label="Search failed", state="error")
            st.error(str(exc))
            return

        if not found:
            status.update(label="Nothing came back", state="error")
            st.warning(
                "No jobs matched. Check that at least one job source key is "
                "set in Settings, then try broader job titles."
            )
            return

        status.write(f"Scoring {len(found)} listings")
        rows = []
        for job in found:
            score, detail = match.score_job(job, prefs, user_skills)
            job.score, job.score_detail = score, detail
            rows.append(job)
        rows.sort(key=lambda j: j.score, reverse=True)
        keep = rows[: max(config.daily_job_target() * 2, 20)]

        added = db.upsert_jobs(user["id"], [job.to_row() for job in keep])
        status.update(label=f"{added} new jobs added", state="complete")


top = st.columns([3, 2])
with top[0]:
    if st.button("Find jobs now", type="primary", use_container_width=True):
        run_discovery()
        st.rerun()
with top[1]:
    view = st.selectbox("Show", ["New", "Saved", "All", "Hidden"], label_visibility="collapsed")

status_filter = {
    "New": ["new"],
    "Saved": ["saved", "ready"],
    "All": ["new", "saved", "ready", "applied"],
    "Hidden": ["hidden"],
}[view]

rows = db.list_jobs(user["id"], status_filter, limit=200)

if not rows:
    st.caption("Nothing here yet. Press **Find jobs now** to search.")
    st.stop()

filters = st.columns([2, 3])
with filters[0]:
    min_score = st.slider("Minimum match", 0, 100, 0, step=5)
with filters[1]:
    sources = sorted({row.get("source_label") or row["source"] for row in rows})
    chosen_sources = st.multiselect("Sources", sources, default=sources,
                                    label_visibility="collapsed",
                                    placeholder="All sources")

visible = [
    row for row in rows
    if row.get("score", 0) >= min_score
    and (not chosen_sources or (row.get("source_label") or row["source"]) in chosen_sources)
]

st.caption(f"{len(visible)} of {len(rows)} jobs")

for row in visible:
    with st.container(border=True):
        head = st.columns([5, 1])
        with head[0]:
            st.markdown(f"**{row['title']}**")
            st.caption(f"{row.get('company') or 'Unknown company'} - "
                       f"{row.get('location') or 'Location not stated'}")
        with head[1]:
            colour = _shared.score_colour(row.get("score", 0))
            st.markdown(f":{colour}[**{row.get('score', 0)}**]")
            st.caption("match")

        meta = [_shared.source_badge(row), _shared.apply_hint(row)]
        if row.get("salary_text"):
            meta.append(row["salary_text"])
        if row.get("is_remote"):
            meta.append("Remote")
        st.caption(" · ".join(meta))

        detail = row.get("score_detail") or {}
        matched = detail.get("matched_skills") or []
        missing = detail.get("missing_skills") or []
        if matched:
            st.markdown(f"Matches: {', '.join(matched[:8])}")
        if missing:
            st.markdown(f"Gaps: {', '.join(missing[:6])}")

        with st.expander("Why this score, and the description"):
            for reason in detail.get("reasons", []):
                st.write("- " + reason)
            st.caption(
                f"title {detail.get('title', 0)} · skills {detail.get('skills', 0)} · "
                f"location {detail.get('location', 0)} · freshness {detail.get('freshness', 0)}"
            )
            st.divider()
            st.write((row.get("description") or "")[:2500] or "No description supplied.")

        buttons = st.columns(4)
        with buttons[0]:
            if st.button("Tailor", key=f"tailor_{row['id']}", type="primary",
                         use_container_width=True):
                st.session_state["tailor_job_id"] = row["id"]
                _shared.goto("tailor")
        with buttons[1]:
            if row["status"] != "saved" and st.button("Save", key=f"save_{row['id']}",
                                                      use_container_width=True):
                db.set_job_status(user["id"], row["id"], "saved")
                st.rerun()
        with buttons[2]:
            label = "Unhide" if row["status"] == "hidden" else "Hide"
            if st.button(label, key=f"hide_{row['id']}", use_container_width=True):
                db.set_job_status(user["id"], row["id"],
                                  "new" if row["status"] == "hidden" else "hidden")
                st.rerun()
        with buttons[3]:
            if row.get("apply_url"):
                st.link_button("Open", row["apply_url"], use_container_width=True)

# ------------------------------------------------------------ skill advice
st.divider()
st.subheader("What to learn next")
st.caption("Counted across the jobs above, not guessed by an AI.")

gaps = match.skill_gap(rows, user_skills)
if not gaps:
    st.write("Your resume already covers the skills these postings ask for.")
for gap in gaps:
    with st.container(border=True):
        st.markdown(f"**{gap['skill'].title()}** - would open up "
                    f"{gap['jobs_unlocked']} of these {len(rows)} jobs ({gap['share']}%)")
        if gap["sample_titles"]:
            st.caption("For example: " + "; ".join(t for t in gap["sample_titles"] if t))
        links = " · ".join(f"[{r['title']}]({r['url']})" for r in gap["resources"])
        st.markdown(links)

strong = match.strengths(rows, user_skills)
if strong:
    st.subheader("What is already working for you")
    st.write(", ".join(f"{s['skill']} ({s['jobs']} jobs)" for s in strong))
