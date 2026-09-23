"""Apply: build the pack for the browser helper, then track what was sent."""

from __future__ import annotations

import streamlit as st

from core import auth, db, pack
from views import _shared

user = auth.require_login()
profile = _shared.profile_for(user)
contact = profile.get("contact") or {}

st.title("Apply")
st.caption(
    "The helper fills the application form in your own browser. You read it "
    "and press Submit. It never submits anything by itself."
)

if _shared.needs_resume(profile):
    st.stop()

# ------------------------------------------------------- step 1: the helper
with st.expander("Step 1 - Install the helper in Chrome (once)"):
    try:
        st.download_button(
            "Download the helper (.zip)",
            pack.extension_zip(),
            file_name="job-seeker-helper.zip",
            mime="application/zip",
            use_container_width=True,
        )
    except FileNotFoundError:
        st.warning("The extension folder is missing from this deployment.")
    st.markdown(
        """
1. Unzip the file. You get a folder called **extension**.
2. Open Chrome and go to `chrome://extensions`.
3. Turn on **Developer mode** (top right).
4. Click **Load unpacked** and pick the **extension** folder.
5. Pin **Job Seeker Helper** to the toolbar with the puzzle-piece icon.

It works on Chrome, Edge and Brave on a laptop. Chrome on Android cannot run
extensions, so on a phone use the downloads below and fill the form yourself.
        """
    )

# --------------------------------------------------------- step 2: the pack
st.subheader("Step 2 - Build your apply pack")

candidates = db.list_jobs(user["id"], ["ready", "saved"], limit=60)
if not candidates:
    st.info("Mark a job as ready on the Tailor page and it will show up here.")
    if st.button("Go to Tailor"):
        _shared.goto("tailor")
    st.stop()

labels = {
    row["id"]: f"{row['title']} - {row.get('company') or 'Unknown'}"
               f"{' (ready)' if row['status'] == 'ready' else ''}"
    for row in candidates
}
ready_ids = [row["id"] for row in candidates if row["status"] == "ready"]
chosen_ids = st.multiselect(
    "Jobs to include",
    list(labels),
    default=ready_ids[: pack.MAX_JOBS] or [candidates[0]["id"]],
    format_func=lambda i: labels[i],
    max_selections=pack.MAX_JOBS,
)

if st.button("Build apply pack", type="primary", disabled=not chosen_ids):
    with st.spinner("Building resumes and packing them up..."):
        selected = [row for row in candidates if row["id"] in chosen_ids]
        drafts, notes = {}, {}
        for row in selected:
            saved = db.get_tailoring(user["id"], row["id"]) or {}
            if saved.get("resume_md"):
                drafts[row["id"]] = saved["resume_md"]
            if saved.get("cover_note"):
                notes[row["id"]] = saved["cover_note"]
        built = pack.build(profile, selected, drafts, notes)
        st.session_state["apply_pack"] = pack.to_bytes(built)
        st.session_state["apply_pack_count"] = len(built["jobs"])
        st.session_state["apply_pack_tailored"] = len(drafts)

if st.session_state.get("apply_pack"):
    data = st.session_state["apply_pack"]
    count = st.session_state.get("apply_pack_count", 0)
    tailored = st.session_state.get("apply_pack_tailored", 0)
    st.success(f"{count} job(s) packed, {tailored} with a tailored resume, "
               f"{len(data) / 1000:.0f} KB.")
    warning = pack.size_warning(data)
    if warning:
        st.warning(warning)
    st.download_button(
        "Download apply pack (.json)",
        data,
        file_name="job-seeker-pack.json",
        mime="application/json",
        use_container_width=True,
    )
    st.caption(
        "This file holds your name, contact details, saved answers and your "
        "resumes, because that is what fills the form. Keep it on your own "
        "laptop and delete it when you are done - the helper has a button for "
        "that too."
    )
    st.markdown(
        "**Then:** click the helper icon in Chrome, choose **Import apply "
        "pack**, pick this file, and press **Open and use** next to a job. "
        "On the application page, press **Fill this form**, check everything, "
        "and submit it yourself."
    )

# -------------------------------------------------------- step 3: tracking
st.subheader("Step 3 - Keep track")
for row in candidates:
    if row["id"] not in chosen_ids:
        continue
    with st.container(border=True):
        columns = st.columns([4, 2, 2])
        with columns[0]:
            st.markdown(f"**{row['title']}**")
            st.caption(f"{row.get('company') or ''} · {_shared.apply_hint(row)}")
        with columns[1]:
            if row.get("apply_url"):
                st.link_button("Open", row["apply_url"], use_container_width=True)
        with columns[2]:
            if st.button("I applied", key=f"applied_{row['id']}", use_container_width=True):
                db.record_application(user["id"], row["id"])
                st.rerun()

applications = db.list_applications(user["id"])
if applications:
    st.subheader("Applied")
    by_id = {row["id"]: row for row in db.list_jobs(user["id"], None, limit=200)}
    for application in applications:
        job = by_id.get(application["job_id"])
        if not job:
            continue
        when = (application.get("submitted_at") or application["prepared_at"])[:10]
        st.markdown(f"- {when} · **{job['title']}** at {job.get('company') or 'unknown'} "
                    f"({application['status']})")
