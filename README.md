# JobPilot AI

A personal, privacy-first job-search agent: it discovers real openings from official job-board APIs, scores them transparently against your verified profile, tailors your resume and cover letter without inventing anything, walks you through an approval-gated application, tracks every application, and drafts networking outreach for you to send.

**Milestone 1 — runnable MVP.** One FastAPI service serves both the API and the web app. SQLite by default, PostgreSQL via `DATABASE_URL`.

---

## Run it

**Option A — script (macOS / Linux, Python 3.11+)**

```bash
./run.sh
```

Then open http://127.0.0.1:8000, create an account, and follow the setup checklist on the dashboard.

**Option B — manual**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
python -m app.migrations          # creates/updates the schema (idempotent)
uvicorn app.main:app --reload     # http://127.0.0.1:8000
```

**Option C — Docker with PostgreSQL**

```bash
cp .env.example .env              # optional: add OPENAI_API_KEY
docker compose up --build         # http://127.0.0.1:8000
```

**Run the tests**

```bash
cd backend && python -m pytest -q
```

API reference (OpenAPI): http://127.0.0.1:8000/api/docs

---

## First 5 minutes

1. **Register** (the account lives in your own database).
2. **Resume library →** upload your PDF/DOCX, review what was extracted, click **Fill empty profile fields**.
3. **Profile →** correct anything, add target titles/locations/salary, sponsorship need, tick **I confirm**, save.
4. **Discover →** add a source, e.g. Greenhouse board `anthropic` / `airbnb` or Lever site `palantir` (the slug in `job-boards.greenhouse.io/<slug>` or `jobs.lever.co/<slug>`). It runs immediately and scores every job.
   *No network or just exploring?* Add the **Simulated demo source** — every listing it creates is badged **SIMULATED**, uses example.com links, and is excluded from analytics by default.
5. Open a job → **Tailor resume** / **Draft cover letter** → review side-by-side → **Approve** → download PDF/DOCX.
6. **Application →** paste screening questions → fill what JobPilot can't know → **Validate & request approval** → **Approve package** → open the official form, submit it yourself → **Record submission** (paste the confirmation).
7. **Networking →** run the suggested searches, add people you verified (with source URL), draft → approve → copy → mark as sent.

---

## What's new in milestone 2

- **Format-preserving tailoring.** JobPilot now edits *your uploaded file* (PDF or DOCX) instead of generating a new resume: it re-words relevant lines in the job's language and adds matching skills to your existing skills lines. Your name, contact details, layout, fonts, bold keywords and every other section stay exactly as they are. Each change is shown side by side with your original, with a live preview, and nothing is applied until you approve it.
- **Honest skills.** Skills the posting asks for that already appear elsewhere in your resume are pre-ticked; skills that don't are listed unticked ("tick only if you really have it").
- **ATS match score.** Jobs are scored like an applicant tracking system would: keywords (required items count double), job title, years of experience, education and soft skills, computed against your actual resume text, with a before → after score for every tailored version.
- **Find jobs for me.** One button searches the free sources — Remotive, Himalayas, Jobicy (remote), The Muse, Arbeitnow (Europe) — plus JSearch (Google Jobs: LinkedIn/Indeed/Glassdoor, free RapidAPI key, ~200 searches/month) and USAJOBS (free key) if connected; Adzuna is optional and paid (£8/month after 25 test calls). Runs daily on your schedule.
- **Companies I follow.** Paste careers-page links or company names; JobPilot detects the company's Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee or Workday site — or its own careers site (Amazon, Microsoft, Google, Apple, Netflix, Oracle, JPMorgan) — and checks it daily, keeping only roles that match your target titles. robots.txt is checked before every careers-site search. Companies with no usable feed (e.g. Meta, Tesla — Tesla's robots.txt disallows automated search) are followed through Google Jobs (JSearch key needed), each checked weekly so ~30 such companies fit JSearch's free plan.
- **Top 100 tech companies.** Discover → *Top 100 tech companies*: one click follows all of them (the Google Jobs ones need a JSearch key). 66 have direct feeds verified live from GitHub Actions in Oct 2026 (big tech, NVIDIA/Intel/Broadcom and other chip makers on Workday, Salesforce, Adobe, OpenAI, Anthropic, xAI, Stripe, SpaceX…); the other 34 use Google Jobs. Following more than 8 companies at once searches them in the background.
- **Connections.** Save an AI key (Google Gemini free plan or OpenAI), JSearch, USAJOBS or Adzuna keys in Settings → Connections; they're stored encrypted.

## One-click apply (browser extension)

JobPilot → Settings → **Browser extension**: download, load it in Chrome/Edge (Developer mode → Load unpacked), click **Connect**.
Then **⚡ Apply with JobPilot** on a job or application: you approve the package once, the company's application form opens,
and the extension fills it — name, contact details, links, location, work authorization and sponsorship (from your profile),
your approved screening answers, and attaches your resume (the approved tailored version, or your uploaded resume) and cover letter.
You check the highlighted fields and press the site's Submit button; the extension sees the site's confirmation page and records
the submission in JobPilot with that text as evidence.

It never accepts terms or consent boxes, never answers demographic (EEO) questions, never solves CAPTCHAs, and only runs in tabs
opened from JobPilot (or when you click *Fill this page* in its popup). Workday and some company sites need you to sign in to their
portal first; the extension fills each step's fields after that.

## What works now (verified)

| Area | Status | Notes |
|---|---|---|
| Accounts, sessions, per-user data isolation | ✅ tested | scrypt passwords, httpOnly SameSite=Strict cookie, 404 on other users' rows |
| Profile + preferences + work authorization + match weights | ✅ tested | every save snapshots a revision; restore supported |
| Resume upload (PDF/DOCX) + parsing | ✅ tested | magic-byte + size + zip-bomb checks, random storage names, files chmod 600 |
| Greenhouse Job Board adapter | ✅ tested against documented response shape | **real, no credentials**; couldn't be called live from the build sandbox (network allow-list) |
| Lever Postings adapter (global + EU) | ✅ tested against documented response shape | **real, no credentials**; same caveat |
| Simulated demo source | ✅ tested | clearly labelled everywhere; disable with `JOBPILOT_ALLOW_MOCK_SOURCES=0` |
| Retries, 429 back-off, non-JSON handling, clear 404 errors | ✅ tested | source errors are stored and shown, never crash a run |
| Cross-source duplicate detection, closed-listing detection, listing history | ✅ tested | |
| Transparent match score (5 weighted components) + flags | ✅ tested | sponsorship conflicts, experience gaps, excluded keywords |
| Resume tailoring with fact guard | ✅ tested | employers/titles/dates/education locked; new numbers or skills rejected |
| Cover letters with required personal motivation placeholder | ✅ tested | can't approve until `[[ADD: …]]` is filled |
| Screening answers (never guesses personal facts) + reusable answer library | ✅ tested | |
| Approval gate (hash-bound) + manual submission record + duplicate prevention | ✅ tested | edits after approval revoke it |
| DOCX / PDF export, CSV tracker export (formula-injection safe) | ✅ tested | |
| Tracker (board + table), status state machine, interviews, notes, history | ✅ tested | |
| Networking research plans, contacts, approval-gated outreach, duplicate-outreach rules | ✅ tested | |
| Follow-up tasks (auto + manual), calendar, snooze | ✅ tested | |
| Analytics (verified vs self-reported, simulated excluded) | ✅ tested | |
| Background scheduler + global pause + per-workflow toggles | ✅ tested | |
| Data export (JSON) and full account deletion | ✅ tested | |
| Full UI walkthrough in headless Chromium | ✅ run | register → upload → profile → discover → tailor → approve → submit → tracker/analytics/settings, no console errors |

## Requires credentials or external access

| Integration | Needed | How |
|---|---|---|
| OpenAI (optional polishing of bullets/letters) | `OPENAI_API_KEY` (paid, usage-based) | add to `.env`; set `OPENAI_MODEL` to a model your account has. Uses Chat Completions with strict JSON schema. **The client is unit-tested with mocks only — it has not been called against the live API.** |
| PostgreSQL | a database | `DATABASE_URL=postgresql+psycopg://…` or `docker compose up`. The full test suite passes on PostgreSQL 16 and SQLite; CI runs both. |
| Greenhouse / Lever live data | outbound internet | nothing to configure |

## Deliberately not automated (and why)

- **Submitting applications.** Greenhouse's and Lever's *apply* APIs require an **employer-issued** key, so a candidate can't use them. Browser-automating other ATS forms routinely violates their terms and trips bot protection. JobPilot prepares and validates everything, then you submit and record it. The `Application` service is designed so a permitted submission adapter can be added later without touching the rest (see below).
- **LinkedIn / people search.** No scraping. JobPilot generates targeted queries you run yourself; contacts are only "verified" when you attach the source URL.
- **Sending messages.** Drafts are approved, copied and sent by you, then marked sent (feeding follow-ups and duplicate-outreach checks).

---

## Architecture

```
frontend/                 Vanilla ES-module SPA (no build step), served by FastAPI
  js/app.js               router + shell;  js/pages/*.js one module per page
  js/ui.js                DOM helper — all untrusted text set via textContent
backend/app/
  main.py                 app, security headers/CSP, error handling, scheduler startup
  config.py               env-based settings (secrets never in DB or frontend)
  models.py               SQLAlchemy schema (users, profiles, resumes, sources, jobs,
                          snapshots, assessments, applications, documents, answers,
                          contacts, outreach, tasks, interviews, events, audit log)
  migrations.py           versioned, idempotent migration runner
  security.py             auth, ownership checks, rate limiting, audit logging
  scheduler.py            Orchestrator loop (per-user lock, pause-aware)
  api/                    HTTP routes (thin)
  services/
    resume_parser.py      Profile Agent — extraction + validation
    sources/              Job Discovery adapters (greenhouse, lever, mock)
    discovery.py          upsert, dedupe, closed detection, history
    matching.py           Job Matching Agent — deterministic weighted score
    tailoring.py          Resume + Cover Letter Agents, fact guard
    llm.py                optional OpenAI client (structured output, fenced untrusted input)
    applications.py       Application + Tracker Agents — state machine, approval gate
    networking.py         Networking Agent — research plans, drafts, duplicate rules
    insights.py           Follow-up Agent + analytics
    export.py             ATS-friendly DOCX/PDF, safe CSV
```

**Deterministic where it matters:** permissions, validation, scores, status transitions and approvals are plain code. LLMs (when enabled) only rewrite wording, and every rewrite passes the fact guard.

**Stack choice vs. the brief.** The brief preferred Next.js + Celery/Redis. For a one-developer MVP I chose a single FastAPI process serving a no-build ES-module frontend and an in-process scheduler: one command to run, nothing else to operate. The API is fully separate (`/api/*`, OpenAPI documented), so a Next.js frontend can replace `frontend/` later, and `scheduler.tick()` can move into a Celery beat task unchanged.

### Adding a job source

1. Create `backend/app/services/sources/<name>.py` with a `JobSourceAdapter` subclass implementing `fetch() -> list[NormalizedJob]` (use `self._get_json` for retries/back-off).
2. Register it in `sources/__init__.py` `ADAPTERS`, and add its kind to `SourceIn.kind` in `schemas.py`.
3. Add a fixture-based test like `test_greenhouse_adapter_normalizes`. Only use sources whose terms permit this access.

Good next candidates (check each one's current docs and terms first): Ashby (`api.ashbyhq.com/posting-api/job-board/<org>`), Workable, SmartRecruiters public postings, and paid aggregators with APIs.

### Adding a submission integration

Implement a function that takes an approved `Application` and returns evidence (confirmation id / receipt), then call it from a new endpoint after `approval_is_current()` and before `record_submission(..., method="<adapter>")`. Keep the explicit-confirm step.

---

## Deploy to Render (free)

The repo includes `render.yaml`, so Render creates the web service and a Postgres database for you.

1. Sign in at https://dashboard.render.com with GitHub.
2. **New → Blueprint**, pick this repository, click **Apply**. Leave `OPENAI_API_KEY` blank unless you have one.
3. Wait for the first build (~3–5 min), then open `https://<service-name>.onrender.com` and create your account.
4. Sign-up closes automatically after the first account (`JOBPILOT_ALLOW_REGISTRATION=first`), so create yours right away.

Free-plan limits (Render docs): the service sleeps after 15 min without traffic and takes ~1 min to wake, so scheduled searches only run while it's awake; the free database **expires 30 days after creation** (14-day grace to upgrade, ~$7/mo for the smallest paid plan at time of writing). Resumes are stored in Postgres, so nothing is lost when the container restarts.

Every push to `main` redeploys automatically; GitHub Actions runs the tests on SQLite and Postgres.

## Deploying elsewhere

Any container host works (Fly.io, Render, Railway, a VPS). Checklist:

- Use the `Dockerfile`, a managed PostgreSQL (`DATABASE_URL`), and a persistent volume for `JOBPILOT_DATA_DIR` (uploaded resumes). For multiple instances, move uploads to private object storage (S3/GCS) and the scheduler to a single worker.
- Serve only over HTTPS (session cookies become `Secure` automatically behind HTTPS; keep `--proxy-headers`).
- Use `JOBPILOT_ALLOW_REGISTRATION=first` (or `0` after signing up) and `JOBPILOT_ALLOW_MOCK_SOURCES=0`.
- Keep `OPENAI_API_KEY` in the host's secret manager, never in the image.
- Enable encrypted-at-rest storage for the database and volume (the app stores resumes and personal data); take regular backups.
- Rate limiting is in-memory per process — put a reverse proxy rate limit in front for public exposure.

## Security & privacy controls

- Approval required (and enforced server-side) before any document is final, any package is approved, any submission is recorded or any message is marked sent.
- Untrusted text (job posts, resumes) is rendered as text only, fenced as data in LLM prompts, and LLM output is schema-validated and fact-checked.
- Strict CSP (no inline scripts), `X-Frame-Options: DENY`, `nosniff`, `no-store` on API responses.
- Audit log of important actions (visible in Settings); secrets redacted.
- Kill switch pauses all automation instantly; per-workflow toggles.
- Full JSON export and account deletion (removes stored files too).

## Roadmap (next milestones)

1. Ashby + one aggregator adapter; saved-search alerts for high-match jobs (email/push).
2. Live-tested OpenAI path with prompt evaluation set; resume diff for summary/skills.
3. Alembic migrations + Postgres CI; encrypted columns for contact details.
4. Next.js frontend (if you want SSR/marketing pages) reusing the same API.
5. Permitted submission adapters (e.g. employer-provided integrations) behind the existing approval gate.
