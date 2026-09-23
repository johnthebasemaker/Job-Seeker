-- Job Seeker schema.
--
-- Security model: the Streamlit app is the only client. It talks to Postgres
-- with the service role key held in st.secrets, and every query is scoped to a
-- user_id by core/db.py. RLS is enabled with NO policies so that the anon /
-- publishable key can read nothing at all if it ever leaks. The service role
-- bypasses RLS by design.
--
-- PII rule: profile.contact holds name/email/phone/links and is NEVER sent to
-- an LLM. The resume markdown stored here is already contact-free.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------- users
create table if not exists app_user (
    id            uuid primary key default gen_random_uuid(),
    email         text unique not null,
    display_name  text,
    created_at    timestamptz not null default now(),
    last_seen_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------- profile
create table if not exists profile (
    user_id           uuid primary key references app_user(id) on delete cascade,
    contact           jsonb not null default '{}'::jsonb,  -- PII, never leaves this app
    headline          text,
    base_resume_md    text,                                -- contact-free markdown
    resume_file_path  text,                                -- storage object path
    prefs             jsonb not null default '{}'::jsonb,  -- country, titles, locations, ...
    answer_bank       jsonb not null default '{}'::jsonb,  -- one-time screening answers
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

-- ---------------------------------------------------------------- jobs
create table if not exists job (
    id             uuid primary key default gen_random_uuid(),
    user_id        uuid not null references app_user(id) on delete cascade,
    fingerprint    text not null,
    source         text not null,          -- jsearch | adzuna | jooble | greenhouse | lever | ashby
    source_label   text not null,          -- shown in the UI, e.g. "Indeed (via JSearch)"
    publisher      text,                   -- board the listing came from, when known
    is_indeed      boolean not null default false,
    title          text not null,
    company        text,
    location       text,
    country        text,
    is_remote      boolean default false,
    employment_type text,
    salary_text    text,
    description    text,
    apply_url      text,
    apply_kind     text,                   -- indeed_easy_apply | greenhouse | lever | ashby | external
    posted_at      timestamptz,
    discovered_at  timestamptz not null default now(),
    score          integer default 0,
    score_detail   jsonb not null default '{}'::jsonb,
    status         text not null default 'new',  -- new | saved | hidden | ready | applied
    unique (user_id, fingerprint)
);

create index if not exists job_user_status_score_idx on job (user_id, status, score desc);
create index if not exists job_user_discovered_idx  on job (user_id, discovered_at desc);

-- ---------------------------------------------------------------- tailoring
create table if not exists tailoring (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references app_user(id) on delete cascade,
    job_id      uuid not null references job(id) on delete cascade,
    resume_md   text,                                 -- tailored, contact-free
    ats         jsonb not null default '{}'::jsonb,   -- deterministic ATS report
    chat        jsonb not null default '[]'::jsonb,   -- [{role, content, ts}]
    warnings    jsonb not null default '[]'::jsonb,   -- fabrication checks
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    unique (user_id, job_id)
);

-- ---------------------------------------------------------------- applications
create table if not exists application (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references app_user(id) on delete cascade,
    job_id      uuid not null references job(id) on delete cascade,
    status      text not null default 'prepared',  -- prepared | submitted | interview | rejected
    answers     jsonb not null default '{}'::jsonb,
    pdf_path    text,
    docx_path   text,
    notes       text,
    prepared_at timestamptz not null default now(),
    submitted_at timestamptz,
    unique (user_id, job_id)
);

-- ---------------------------------------------------------------- quota
create table if not exists usage_log (
    id         bigserial primary key,
    user_id    uuid references app_user(id) on delete cascade,
    day        date not null default current_date,
    kind       text not null,        -- llm | jsearch | adzuna | jooble | ats
    calls      integer not null default 1,
    tokens     integer not null default 0,
    created_at timestamptz not null default now()
);

create index if not exists usage_log_day_kind_idx on usage_log (day, kind);

-- ---------------------------------------------------------------- lockdown
alter table app_user   enable row level security;
alter table profile    enable row level security;
alter table job        enable row level security;
alter table tailoring  enable row level security;
alter table application enable row level security;
alter table usage_log  enable row level security;

-- ---------------------------------------------------------------- storage
insert into storage.buckets (id, name, public)
values ('resumes', 'resumes', false)
on conflict (id) do nothing;

insert into storage.buckets (id, name, public)
values ('generated', 'generated', false)
on conflict (id) do nothing;

-- ---------------------------------------------------------------- hard delete
-- Used by the "Delete my data" button. Storage objects are removed by the app
-- first; this wipes every row, including the account itself.
create or replace function delete_user_data(p_email text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
    delete from app_user where email = p_email;
end;
$$;
