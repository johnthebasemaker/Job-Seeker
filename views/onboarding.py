"""Profile: resume upload, contact details, search preferences, answer bank."""

from __future__ import annotations

import streamlit as st

from core import auth, config, db, match, render, resume
from core.jobs import ats
from core.resume import ResumeError
from views import _shared

user = auth.require_login()
profile = _shared.profile_for(user)
prefs = dict(_shared.prefs_of(profile))
contact = dict(profile.get("contact") or {})
answers = dict(profile.get("answer_bank") or {})

st.title("Profile")
st.caption(
    "Your resume is stored under your account only. Personal details are "
    "stripped out before anything is sent to the AI - see Settings."
)

resume_tab, prefs_tab, answers_tab = st.tabs(["Resume", "What you want", "Application answers"])

# --------------------------------------------------------------- resume tab
with resume_tab:
    if profile.get("base_resume_md"):
        st.success("Base resume saved.")
    else:
        st.info("Upload your current resume as a PDF to get started.")

    uploaded = st.file_uploader("Resume (PDF)", type=["pdf"], key="resume_upload")
    if uploaded is not None and st.button("Read this resume", type="primary"):
        data = uploaded.getvalue()
        if len(data) > config.MAX_RESUME_BYTES:
            st.error("That file is over 5 MB. Export a smaller PDF and try again.")
        else:
            with st.status("Reading your resume...", expanded=True) as status:
                try:
                    st.write("Extracting text")
                    raw = resume.extract_text(data)

                    st.write("Separating your contact details (these never reach the AI)")
                    try:
                        llm = _shared.llm_for(user)
                    except Exception:
                        llm = None
                    markdown, found_contact = resume.to_markdown(raw, llm)

                    st.write("Saving")
                    path = db.upload_resume(user["id"], uploaded.name, data)
                    merged = {**found_contact, **{k: v for k, v in contact.items() if v}}
                    db.save_profile(
                        user["id"],
                        base_resume_md=markdown,
                        contact=merged,
                        resume_file_path=path,
                    )
                    status.update(label="Resume imported", state="complete")
                    _shared.profile_for(user, refresh=True)
                    st.rerun()
                except ResumeError as exc:
                    status.update(label="Could not read that file", state="error")
                    st.error(str(exc))

    if profile.get("base_resume_md"):
        st.subheader("Contact details")
        st.caption("Added to the PDF at download time. Never sent to the AI.")
        cols = st.columns(2)
        with cols[0]:
            contact["full_name"] = st.text_input("Full name", contact.get("full_name", ""))
            contact["email"] = st.text_input("Email", contact.get("email", ""))
            contact["phone"] = st.text_input("Phone", contact.get("phone", ""))
        with cols[1]:
            contact["location"] = st.text_input("City", contact.get("location", ""))
            contact["linkedin"] = st.text_input("LinkedIn", contact.get("linkedin", ""))
            contact["github"] = st.text_input("GitHub or portfolio",
                                              contact.get("github", "") or contact.get("website", ""))

        st.subheader("Base resume")
        st.caption(
            "This is the master copy. Tailoring never changes it - each job "
            "gets its own version."
        )
        edited = st.text_area("Markdown", profile["base_resume_md"], height=380,
                              label_visibility="collapsed")

        left, right = st.columns(2)
        with left:
            if st.button("Save resume and details", type="primary", use_container_width=True):
                db.save_profile(user["id"], base_resume_md=edited, contact=contact)
                _shared.profile_for(user, refresh=True)
                st.success("Saved.")
        with right:
            if st.button("Preview PDF", use_container_width=True):
                try:
                    st.session_state["preview_pdf"] = render.resume_pdf(edited, contact)
                except render.RenderError as exc:
                    st.error(str(exc))

        if st.session_state.get("preview_pdf"):
            st.download_button(
                "Download PDF",
                st.session_state["preview_pdf"],
                file_name=render.safe_filename(contact, None, "pdf"),
                mime="application/pdf",
                use_container_width=True,
            )

        found = sorted(match.extract_skills(edited))
        if found:
            st.caption(f"Skills detected: {', '.join(found)}")

# ------------------------------------------------------------ preferences
with prefs_tab:
    with st.form("prefs"):
        codes = [code for code, _ in config.country_options()]
        labels = dict(config.country_options())
        country = st.selectbox(
            "Country",
            codes,
            index=codes.index(prefs.get("country", config.DEFAULT_COUNTRY))
            if prefs.get("country", config.DEFAULT_COUNTRY) in codes else 0,
            format_func=lambda c: labels[c],
        )

        titles = st.text_area(
            "Job titles you want (one per line, best three)",
            "\n".join(prefs.get("titles", [])),
            height=90,
            placeholder="Python Backend Developer\nSoftware Engineer",
        )
        city_options = list(config.COUNTRIES[country].cities)
        saved_locations = [loc for loc in prefs.get("locations", []) if loc]
        locations = st.multiselect(
            "Locations",
            sorted(set(city_options) | set(saved_locations)),
            default=saved_locations or city_options[:1],
        )
        other_location = st.text_input("Another location (optional)",
                                       placeholder="Madurai")

        cols = st.columns(2)
        with cols[0]:
            levels = ["", "intern", "junior", "mid", "senior", "manager"]
            saved_level = prefs.get("seniority", "")
            seniority = st.selectbox(
                "Level",
                levels,
                index=levels.index(saved_level) if saved_level in levels else 0,
                format_func=lambda s: s.title() if s else "Any",
            )
            remote_only = st.checkbox("Remote roles only", value=bool(prefs.get("remote_only")))
        with cols[1]:
            indeed_only = st.checkbox("Indeed listings only", value=bool(prefs.get("indeed_only")))
            st.caption("Leave off to see Greenhouse, Lever and Ashby roles too.")

        keywords = st.text_input("Must-have keywords (comma separated)",
                                 ", ".join(prefs.get("keywords", [])))
        exclude = st.text_input("Words that rule a job out (comma separated)",
                                ", ".join(prefs.get("exclude", [])),
                                placeholder="night shift, commission only")

        st.markdown("**Sources**")
        source_cols = st.columns(4)
        sources = prefs.get("sources") or {}
        with source_cols[0]:
            use_jsearch = st.checkbox("JSearch", value=sources.get("jsearch", True))
        with source_cols[1]:
            use_adzuna = st.checkbox("Adzuna", value=sources.get("adzuna", True))
        with source_cols[2]:
            use_jooble = st.checkbox("Jooble", value=sources.get("jooble", True))
        with source_cols[3]:
            use_ats = st.checkbox("Company boards", value=sources.get("ats", True))

        if st.form_submit_button("Save preferences", type="primary"):
            chosen = [loc.strip() for loc in locations if loc.strip()]
            if other_location.strip():
                chosen.append(other_location.strip())
            prefs.update({
                "country": country,
                "titles": [t.strip() for t in titles.splitlines() if t.strip()],
                "locations": chosen,
                "seniority": seniority,
                "remote_only": remote_only,
                "indeed_only": indeed_only,
                "keywords": [k.strip() for k in keywords.split(",") if k.strip()],
                "exclude": [x.strip() for x in exclude.split(",") if x.strip()],
                "sources": {"jsearch": use_jsearch, "adzuna": use_adzuna,
                            "jooble": use_jooble, "ats": use_ats},
            })
            db.save_profile(user["id"], prefs=prefs)
            _shared.profile_for(user, refresh=True)
            st.success("Preferences saved.")

    country_code = prefs.get("country", config.DEFAULT_COUNTRY)
    available = config.COUNTRIES[country_code].sources
    st.caption(f"Sources that cover {config.COUNTRIES[country_code].name}: "
               f"{', '.join(available)} plus any company boards you add below.")

    st.subheader("Company job boards")
    st.caption(
        "Greenhouse, Lever and Ashby boards have the simplest application "
        "forms. Add the company's board name from its careers URL."
    )
    companies = list(prefs.get("ats_companies", []))
    for index, entry in enumerate(companies):
        row = st.columns([3, 5, 2])
        row[0].write(entry.get("board", ""))
        row[1].write(entry.get("slug", ""))
        if row[2].button("Remove", key=f"rm_ats_{index}"):
            companies.pop(index)
            prefs["ats_companies"] = companies
            db.save_profile(user["id"], prefs=prefs)
            _shared.profile_for(user, refresh=True)
            st.rerun()

    add = st.columns([3, 5, 2])
    board = add[0].selectbox("Board", list(ats.BOARDS), label_visibility="collapsed")
    slug = add[1].text_input("Board name", placeholder="acme-corp", label_visibility="collapsed")
    if add[2].button("Check", use_container_width=True) and slug.strip():
        ok, message = ats.check_slug(board, slug.strip())
        if ok:
            companies.append({"board": board, "slug": slug.strip()})
            prefs["ats_companies"] = companies
            db.save_profile(user["id"], prefs=prefs)
            _shared.profile_for(user, refresh=True)
            st.success(f"Added. {message}")
            st.rerun()
        else:
            st.error(message)

# ----------------------------------------------------------- answer bank
with answers_tab:
    st.caption(
        "These are the questions application forms ask over and over. Fill "
        "them once and the browser helper can answer them for you. If a form "
        "asks something that is not here, it stops and asks you rather than "
        "guessing."
    )
    with st.form("answers"):
        answers["work_authorisation"] = st.text_input(
            "Are you authorised to work in this country?",
            answers.get("work_authorisation", ""), placeholder="Yes, Indian citizen")
        answers["visa_sponsorship"] = st.text_input(
            "Do you need visa sponsorship?", answers.get("visa_sponsorship", ""),
            placeholder="No")
        cols = st.columns(2)
        with cols[0]:
            answers["total_experience"] = st.text_input(
                "Total years of experience", answers.get("total_experience", ""))
            answers["current_salary"] = st.text_input(
                "Current salary / CTC", answers.get("current_salary", ""))
            answers["notice_period"] = st.text_input(
                "Notice period", answers.get("notice_period", ""), placeholder="30 days")
        with cols[1]:
            answers["relevant_experience"] = st.text_input(
                "Relevant years of experience", answers.get("relevant_experience", ""))
            answers["expected_salary"] = st.text_input(
                "Expected salary / CTC", answers.get("expected_salary", ""))
            answers["availability"] = st.text_input(
                "When can you start?", answers.get("availability", ""), placeholder="Immediately")
        answers["relocation"] = st.text_input(
            "Willing to relocate?", answers.get("relocation", ""), placeholder="Yes, within India")
        answers["highest_qualification"] = st.text_input(
            "Highest qualification", answers.get("highest_qualification", ""))
        answers["languages"] = st.text_input(
            "Languages you speak", answers.get("languages", ""), placeholder="English, Tamil")
        answers["why_this_role"] = st.text_area(
            "A line about why you are looking", answers.get("why_this_role", ""), height=80)

        if st.form_submit_button("Save answers", type="primary"):
            db.save_profile(user["id"], answer_bank=answers)
            _shared.profile_for(user, refresh=True)
            st.success("Saved.")

    st.subheader("Your own questions and answers")
    custom = list(answers.get("custom", []))
    for index, pair in enumerate(custom):
        row = st.columns([4, 5, 1])
        row[0].write(pair.get("q", ""))
        row[1].write(pair.get("a", ""))
        if row[2].button("x", key=f"rm_q_{index}"):
            custom.pop(index)
            answers["custom"] = custom
            db.save_profile(user["id"], answer_bank=answers)
            _shared.profile_for(user, refresh=True)
            st.rerun()

    new = st.columns([4, 5, 1])
    question = new[0].text_input("Question", key="new_q", label_visibility="collapsed",
                                 placeholder="Question the form asks")
    answer = new[1].text_input("Answer", key="new_a", label_visibility="collapsed",
                               placeholder="Your answer")
    if new[2].button("+") and question.strip() and answer.strip():
        custom.append({"q": question.strip(), "a": answer.strip()})
        answers["custom"] = custom
        db.save_profile(user["id"], answer_bank=answers)
        _shared.profile_for(user, refresh=True)
        st.rerun()
