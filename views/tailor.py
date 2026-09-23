"""Tailor: ATS report, AI suggestions, a chat editor and the downloads."""

from __future__ import annotations

import datetime as dt

import streamlit as st

from core import auth, db, match, render, tailor
from views import _shared

user = auth.require_login()
profile = _shared.profile_for(user)
prefs = _shared.prefs_of(profile)
contact = profile.get("contact") or {}

st.title("Tailor")

if _shared.needs_resume(profile):
    st.stop()

# ------------------------------------------------------------ pick a job
candidates = db.list_jobs(user["id"], ["new", "saved", "ready", "applied"], limit=100)
if not candidates:
    st.info("Find some jobs first.")
    if st.button("Go to Jobs"):
        _shared.goto("jobs")
    st.stop()

ids = [row["id"] for row in candidates]
preselected = st.session_state.get("tailor_job_id")
index = ids.index(preselected) if preselected in ids else 0
by_id = {row["id"]: row for row in candidates}

job_id = st.selectbox(
    "Job",
    ids,
    index=index,
    format_func=lambda i: f"{by_id[i]['title']} - {by_id[i].get('company') or 'Unknown'} "
                          f"({by_id[i].get('score', 0)})",
)
st.session_state["tailor_job_id"] = job_id
job = by_id[job_id]

# --------------------------------------------------------------- state
state_key = f"draft_{job_id}"
chat_key = f"chat_{job_id}"

if state_key not in st.session_state:
    saved = db.get_tailoring(user["id"], job_id)
    st.session_state[state_key] = (saved or {}).get("resume_md") or profile["base_resume_md"]
    st.session_state[chat_key] = (saved or {}).get("chat") or []

st.session_state.setdefault(chat_key, [])
draft = st.session_state[state_key]
report = tailor.build_report(draft, contact, job, prefs)


def persist(**extra) -> None:
    db.save_tailoring(
        user["id"], job_id,
        resume_md=st.session_state[state_key],
        chat=st.session_state[chat_key],
        ats={"coverage": report["coverage"], "score": report["match_score"]},
        **extra,
    )


metrics = st.columns(3)
metrics[0].metric("Match score", report["match_score"])
metrics[1].metric("Keyword coverage", f"{report['coverage']}%")
metrics[2].metric("Missing keywords", len(report["missing"]))
st.caption(f"{_shared.source_badge(job)} · {_shared.apply_hint(job)}")

review_tab, edit_tab, chat_tab = st.tabs(["Review", "Edit and download", "Ask the AI"])

# -------------------------------------------------------------- review
with review_tab:
    if report["matched"]:
        st.markdown("**Already covered:** " + ", ".join(report["matched"]))
    if report["missing"]:
        st.markdown("**The posting asks for, your resume does not show:** "
                    + ", ".join(report["missing"]))
        st.caption(
            "Only add these if you have really done them. Anything you have "
            "not done belongs on the learning list, not the resume."
        )
        for skill in report["missing"][:4]:
            links = " · ".join(f"[{r['title']}]({r['url']})"
                               for r in match.learning_links(skill))
            st.markdown(f"- **{skill}** - {links}")
    if report["other_terms"]:
        st.caption("Words the posting repeats: " + ", ".join(report["other_terms"]))

    st.subheader("ATS checks")
    for check in report["checks"]:
        if check["ok"] == "yes":
            st.markdown(f"✅ {check['label']}")
        else:
            st.markdown(f"⚠️ {check['label']} - {check['hint']}")

    st.subheader("AI suggestions")
    if st.button("Suggest edits for this job", type="primary"):
        try:
            with st.spinner("Comparing your resume with the posting..."):
                st.session_state[f"suggestions_{job_id}"] = tailor.suggest_edits(
                    draft, job, _shared.llm_for(user), report, contact
                )
        except Exception as exc:
            _shared.show_llm_error(exc)

    for number, suggestion in enumerate(st.session_state.get(f"suggestions_{job_id}", [])):
        with st.container(border=True):
            st.caption(suggestion.get("section") or "Resume")
            if suggestion.get("original"):
                st.markdown(f"~~{suggestion['original']}~~")
            st.markdown(f"**{suggestion.get('proposed', '')}**")
            if suggestion.get("why"):
                st.caption(suggestion["why"])
            if st.button("Apply this", key=f"apply_{job_id}_{number}"):
                updated, applied = tailor.apply_suggestion(
                    st.session_state[state_key], suggestion)
                if applied:
                    st.session_state[state_key] = updated
                    persist(warnings=tailor.fabrication_warnings(
                        profile["base_resume_md"], updated, job.get("description") or ""))
                    st.rerun()
                else:
                    st.warning(
                        "Could not find that exact line any more. Copy the "
                        "wording into the editor tab instead."
                    )

# ------------------------------------------------------- edit + download
with edit_tab:
    edited = st.text_area("Tailored resume (markdown)", st.session_state[state_key],
                          height=430)
    warnings = tailor.fabrication_warnings(
        profile["base_resume_md"], edited, job.get("description") or "")
    if warnings:
        st.warning("Check these before you send it:")
        for item in warnings:
            st.markdown(f"- **{item['value']}** - {item['note']}")

    buttons = st.columns(3)
    with buttons[0]:
        if st.button("Save draft", type="primary", use_container_width=True):
            st.session_state[state_key] = edited
            persist(warnings=warnings)
            st.success("Saved.")
    with buttons[1]:
        if st.button("Reset to base resume", use_container_width=True):
            st.session_state[state_key] = profile["base_resume_md"]
            persist()
            st.rerun()
    with buttons[2]:
        if st.button("Mark as ready", use_container_width=True):
            db.set_job_status(user["id"], job_id, "ready")
            st.success("Marked ready to apply.")

    st.subheader("Download")
    st.caption("Your contact details are added here, not before.")
    try:
        pdf = render.resume_pdf(edited, contact)
        docx = render.resume_docx(edited, contact)
        downloads = st.columns(2)
        downloads[0].download_button(
            "PDF", pdf, file_name=render.safe_filename(contact, job, "pdf"),
            mime="application/pdf", use_container_width=True)
        downloads[1].download_button(
            "Word", docx, file_name=render.safe_filename(contact, job, "docx"),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True)
    except render.RenderError as exc:
        st.error(str(exc))

    with st.expander("Short cover note"):
        if st.button("Write one"):
            try:
                with st.spinner("Writing..."):
                    st.session_state[f"cover_{job_id}"] = tailor.cover_note(
                        edited, job, _shared.llm_for(user), contact)
            except Exception as exc:
                _shared.show_llm_error(exc)
        if st.session_state.get(f"cover_{job_id}"):
            st.text_area("Cover note", st.session_state[f"cover_{job_id}"], height=200)

# ----------------------------------------------------------------- chat
with chat_tab:
    st.caption(
        "Ask for a rewrite, a shorter summary, or why a bullet is weak. The "
        "AI can change the draft; you approve every change."
    )
    for message in st.session_state[chat_key]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("Rewrite my second bullet to match this job")
    if question:
        st.session_state[chat_key].append(
            {"role": "user", "content": question,
             "ts": dt.datetime.now(dt.timezone.utc).isoformat()})
        try:
            with st.spinner("Thinking..."):
                result = tailor.chat(
                    st.session_state[chat_key], st.session_state[state_key], job,
                    _shared.llm_for(user), contact)
            st.session_state[chat_key].append(
                {"role": "assistant", "content": result["reply"],
                 "ts": dt.datetime.now(dt.timezone.utc).isoformat()})
            if result.get("resume_md"):
                st.session_state[f"proposed_{job_id}"] = result["resume_md"]
            persist()
            st.rerun()
        except Exception as exc:
            st.session_state[chat_key].pop()
            _shared.show_llm_error(exc)

    proposed = st.session_state.get(f"proposed_{job_id}")
    if proposed:
        st.divider()
        st.markdown("**The AI rewrote the resume. Review before it replaces your draft.**")
        flags = tailor.fabrication_warnings(
            profile["base_resume_md"], proposed, job.get("description") or "")
        for item in flags:
            st.markdown(f"- ⚠️ **{item['value']}** - {item['note']}")
        st.text_area("Proposed version", proposed, height=300, key=f"preview_{job_id}")
        choice = st.columns(2)
        if choice[0].button("Use this version", type="primary", use_container_width=True):
            st.session_state[state_key] = proposed
            st.session_state.pop(f"proposed_{job_id}")
            persist(warnings=flags)
            st.rerun()
        if choice[1].button("Discard", use_container_width=True):
            st.session_state.pop(f"proposed_{job_id}")
            st.rerun()
