# Scholarly Insight implementation and handoff checklist

This checklist records the product requirements, technologies, setup decisions,
and deployment work discussed for Scholarly Insight. Status describes evidence
in the current source, tests, or configuration—not an assumption that an
external Firebase or Google Cloud service is working.

## Status key

- [x] Implemented in source and/or covered by a focused test.
- [~] Partially implemented, requires external setup, or not integration-tested.
- [ ] Not implemented, not configured, or not verified.

## 1. Product features from the presentation

The presentation's six planned features are Search & Browse, Article Details,
User Accounts, Reading History, Trackers & Notifications, and Discussion Forum.

| Feature | Status | What is present | Remaining work / caveat |
|---|---|---|---|
| Search & Browse | [~] | Flask search page and JSON API support keyword, author, category, submitted-date range, sort, and pagination. The server queries the arXiv Atom API and validates filters. | No category catalog/directory or autocomplete; categories are entered as text. |
| Article Details | [x] | `/article/<id>` displays title, abstract, authors, categories, dates, source/PDF links, related cached papers, and discussion. | No standalone `GET /api/articles/<id>` JSON route. Text normalization does not remove all LaTeX markup. |
| User Accounts | [~] | Firebase Google sign-in is implemented in the browser; protected Flask routes verify ID tokens and use the verified UID. | Real Firebase configuration, provider setup, authorized domains, and server credentials must be configured. Automated tests use a fake token verifier. |
| Reading History | [x] | Signed-in article visits can be recorded and retrieved with the library. Repeated views update activity time. | The API returns at most the latest 100 items; no export/clear-history flow. |
| Trackers & Notifications | [~] | Users can create/list/delete trackers. Refresh searches arXiv and stores deduplicated in-app alerts. A CLI refreshes all trackers. | Email alerts send via optional SMTP config on new notifications only. No preconfigured scheduler. Trackers cannot currently be edited; refresh is user-triggered or external. |
| Discussion Forum | [~] | Signed-in users can post article comments and replies. Replies must target a comment on the same article; the UI renders threads. | No edit/delete, moderation/reporting, pagination, or forum-wide discovery. |

## 2. Data and modeling requirements

| Item | Status | Evidence / remaining work |
|---|---|---|
| Fetch papers from arXiv | [x] | `app/arxiv.py` builds queries, calls the Atom API over verified TLS, parses entries, and stores normalized records. |
| Merge arXiv versions | [x] | Version suffixes are removed when parsing IDs so versions map to a base paper ID. |
| Normalize title and abstract whitespace | [x] | Parser collapses whitespace in titles and abstracts. |
| Remove LaTeX and normalize author/date fields | [~] | Whitespace is normalized, but comprehensive LaTeX cleanup and systematic author/date normalization are absent. |
| Profile the full arXiv corpus | [ ] | Insights summarize only articles collected into this application's cache, not all arXiv records. |
| Category, author, and monthly summaries | [x] | `app/insights.py` summarizes cached papers; this is descriptive metadata, not global analytics. |
| TF-IDF-style related-paper ranking | [~] | Cosine-style text similarity plus a category-overlap bonus ranks up to 300 recently cached papers. No user relevance evaluation is implemented. |
| LDA topic modeling | [ ] | No LDA/topic model is present. Category counts are not learned topics. |
| Next-read recommendations | [ ] | No separate recommendation model or save-rate evaluation is present. |
| Logistic-regression classification | [ ] | No classifier is trained to predict paper fields/categories. |
| Model evaluation from the presentation | [ ] | No documented relevance study, topic review, recommendation save-rate, or classifier accuracy evaluation. |
| Citation/download/readership metrics | [ ] | These are not available through the selected arXiv API integration and must not be presented as measured app metrics. |

## 3. Data structures / algorithm concepts

| Presentation concept | Status | What is actually used |
|---|---|---|
| Query cache keyed lookup / hash map | [~] | Normalized query parameters are SHA-256 hashed and used as a primary key in the SQL query cache. This is persistent database lookup, not an in-memory hash map. |
| arXiv request queue/rate limit | [~] | Requests are serialized in-process with a thread lock. When PostgreSQL is configured, a PostgreSQL advisory lock and stored timestamp coordinate across instances. The shared PostgreSQL path has no live database integration test. |
| Date sort plus binary search | [ ] | Date bounds are encoded in the arXiv query; no local binary search is used. |
| Stack-based nested query parser | [~] | The query builder groups author/category OR terms and combines filters with AND. It does not parse arbitrary nested expressions with a stack. |
| Trie/autocomplete | [ ] | There is no autocomplete index or trie. |
| Heap for cross-tracker top-k | [ ] | Trackers are refreshed separately; no heap-based merged feed is implemented. |
| Tree/recursive threaded replies | [x] | Comments use `parent_id`; the browser constructs and renders reply trees. |
| Graph/BFS related co-authors | [ ] | Related-paper ranking uses text similarity and category overlap, not a co-author graph or BFS. |

## 4. Technologies and architecture actually used

| Area | Used / selected | Status |
|---|---|---|
| Language and server | Python 3.11+, Flask | [x] Implemented. |
| HTML rendering | Flask/Jinja templates, browser JavaScript, responsive CSS | [x] Implemented. The presentation's React/Tailwind option was replaced to keep the project Python-first. |
| External scholarly data | arXiv Atom API, parsed with `feedparser` | [x] Implemented; live availability depends on arXiv and network access. |
| HTTPS trust | `certifi` CA bundle with normal TLS verification | [x] Implemented; addresses the earlier local Python CA-bundle problem. |
| Local database | SQLite | [x] Implemented and initialized automatically. |
| Production database | PostgreSQL via `psycopg`, planned Cloud SQL | [~] Adapter and schema are present; no live PostgreSQL integration/deployment verified. |
| Authentication | Firebase Authentication Google provider in browser; Firebase Admin verification in Flask | [~] Code exists; real credentials and project settings are external prerequisites. |
| Production compute | Docker image / Gunicorn on Cloud Run | [~] Configuration prepared; image build and Cloud Run deployment not verified. |
| Public routing | Firebase Hosting rewrite to Cloud Run | [~] `firebase.json` is configured; Hosting deployment is not confirmed. |
| Secrets | `.env` locally; Secret Manager planned for production | [~] Secret paths are documented and ignored locally; production Secret Manager values/resources not verified. |
| Background refresh | `python -m app.refresh_trackers` | [~] Command exists; no scheduler is configured. |
| API documentation / CI | None evidenced | [ ] No OpenAPI document or GitHub Actions workflow was present in the reviewed project. |

## 5. Database schema

SQLite and PostgreSQL DDL are defined in `app/db.py`. The application creates
tables at startup with `CREATE TABLE IF NOT EXISTS`; it does not have a
versioned migration framework.

| Table | Status | Purpose |
|---|---|---|
| `articles` | [x] | Normalized article metadata keyed by arXiv ID. |
| `query_cache` | [x] | Search query hash, ordered article IDs, result total, and fetch time. |
| `users` | [x] | Firebase UID and basic profile metadata; no password is stored. |
| `favorites` | [x] | User-to-article favorites with saved timestamp. |
| `reading_history` | [x] | User-to-article history with last viewed timestamp. |
| `trackers` | [x] | User-defined keywords, authors, and categories. |
| `comments` | [x] | Article discussions and reply parent IDs. |
| `notifications` | [x] | Additional table for deduplicated in-app tracker alerts and read state. |
| `arxiv_rate_limit` | [~] | Timestamp used with PostgreSQL advisory locking; SQLite has local/process throttling behavior. |

The schema broadly follows the presentation's planned tables and adds
`notifications` to support in-app alerts. Validate both DDL variants when
changing schema or database behavior.

## 6. Firebase configuration checklist

### Local development

- [ ] Firebase project exists and correct `FIREBASE_PROJECT_ID` is set.
- [ ] Firebase Web app has been registered; its API key, auth domain, and app
  ID are set in `.env`.
- [ ] Google sign-in provider is enabled.
- [ ] The actual local browser hostname (`localhost` and/or `127.0.0.1`) is in
  Firebase Authentication's authorized domains.
- [ ] Firebase Admin uses suitable Application Default Credentials or a
  service-account file stored outside the repository.
- [ ] A real browser sign-in and protected account action have been tested.

Public search does not require Firebase configuration. Firebase web config is
client configuration; service-account JSON is secret and must never be
committed, uploaded into an image, or pasted into chat.

## 7. Local development and validation

- [x] Python virtual environment setup is documented in `run.md`.
- [x] `.env.example` contains placeholders and local defaults.
- [x] SQLite is the local default; database initializes on app startup.
- [x] Run command is documented: `flask --app wsgi run --debug --host 127.0.0.1`.
- [x] Local URL is `http://127.0.0.1:5000`; use `127.0.0.1` if macOS `localhost`
  reaches an unrelated service.
- [x] Unit tests use `python -m unittest discover -s tests -v`.
- [x] Tests cover arXiv query construction, parsing/cache behavior, app routes,
  auth guards, library, trackers, comments, and PostgreSQL adapter behavior.
- [~] The suite passed 23 tests on 2026-11-20; rerun it after future changes
  and do not infer external integration success from unit tests.
- [~] A live local arXiv search returned HTTP 200 in the earlier debugging
  session; rerun if network, code, or runtime changes.
- [ ] Live Firebase Google sign-in has not been proven by the unit suite.
- [ ] PostgreSQL, Docker image build, Cloud Run, and Firebase Hosting have not
  been integration-verified by the unit suite.

## 8. Hosting and publication checklist

Selected target architecture:

```text
Browser -> Firebase Hosting -> Cloud Run (Flask/Gunicorn) -> Cloud SQL PostgreSQL
                           -> Firebase Authentication for identity
```

| Hosting step | Status |
|---|---|
| Cloud Run Dockerfile and Gunicorn entry point | [x] Configuration exists; build/runtime not verified here. |
| Cloud SQL PostgreSQL adapter and schema | [~] Code exists; live database path not tested. |
| Firebase Hosting rewrite to service `scholarly-insight`, region `us-central1` | [x] `firebase.json` contains this configuration. |
| Firebase project alias `scholarly-insights-77069` | [x] Present in `.firebaserc`; verify the intended account/project before deploy. |
| Billing account linked / Firebase upgraded to Blaze | [ ] Not verified. |
| Cloud APIs enabled and Cloud SQL created | [ ] Not verified. |
| Runtime service account/IAM permissions created | [ ] Not verified. |
| Production secrets stored in Secret Manager | [ ] Not verified. |
| Cloud Run service deployed and `/health` tested | [ ] Not verified. |
| Firebase Hosting deployed and public URL tested | [ ] Not verified. |
| Production Firebase authorized domain configured | [ ] Not verified. |
| Ongoing cost/budget monitoring set up | [ ] Not verified. |

The intended Firebase default domains are
`scholarly-insights-77069.web.app` and
`scholarly-insights-77069.firebaseapp.com`, not `*.firebase.com`. A custom
domain must be owned by the user. Firebase Hosting does not execute Flask;
Cloud Run is required for the Python backend.

Cloud Run, Cloud SQL, Secret Manager, and related services can incur charges.
Do not enable billing, create billable resources, or deploy without the user's
explicit approval in the active conversation. See `run.md` for the step-by-step
deployment procedure.

## 9. GitHub repository and credential handling

- [x] Public repository was requested in the previous GitHub setup discussion.
- [x] The local repository was initialized on branch `main` and an initial
  commit was created in that session.
- [x] `.gitignore` excludes `.env`, `.venv/`, `instance/`,
  `firebase-admin.json`, and `firebase-service-account.json`.
- [x] `.dockerignore` excludes local secrets, data, tests, and `.git/` from
  Docker build context.
- [x] Before the initial commit, `.env`, `firebase-admin.json`, SQLite data,
  and `.venv` were verified absent from the Git index; staged text files were
  scanned for common key/token patterns.
- [~] The user later may have published/pushed the repository; verify the
  current GitHub URL, visibility, default branch, and remote before claiming
  publication is complete.
- [ ] Confirm no credential was ever committed in prior history. Ignore rules
  do not remove files from old commits. If a key was exposed, revoke/rotate it
  and follow the provider's history-cleanup guidance.
- [ ] Verify the actual public repository through GitHub before sharing its
  URL.

The Git commit author email is part of public commit metadata. Use a GitHub
`noreply` address if the user wants to keep a personal email private.

## 10. Monitoring, maintenance, and known gaps

- [x] arXiv errors are logged; exact-query cached results may be served stale
  when the upstream request fails.
- [~] Cache TTL defaults to 24 hours, but expired query rows are not globally
  evicted by a background cleanup job.
- [~] PostgreSQL advisory lock is intended to serialize arXiv calls across
  Cloud Run instances; needs a live PostgreSQL test.
- [ ] No nightly tracker scheduler is installed.
- [~] Email alerts are implemented via optional SMTP configuration
  (`SMTP_HOST`/`SMTP_USERNAME`/`SMTP_PASSWORD`/`EMAIL_FROM`); they are sent
  only for newly created notifications and are skipped when unconfigured or
  when the user has no email on file. Delivery is untested against a real
  SMTP server.
- [ ] No structured production monitoring/alerting or error-reporting service
  is configured.
- [ ] No GitHub Actions CI workflow was evidenced.
- [ ] No user-acceptance test with five or more people was documented.
- [ ] No independent parity test compares app search results with arXiv's own
  results.
- [ ] No API OpenAPI/Swagger specification exists.

## 11. Before claiming the project is ready

- [ ] Run the test suite on the current commit.
- [ ] Verify the current GitHub repository and ensure no secrets exist in its
  history.
- [ ] Configure and test Firebase sign-in using the actual project.
- [ ] Provision Cloud SQL and verify PostgreSQL schema/CRUD behavior.
- [ ] Build and run the Docker image locally, if Docker is available.
- [ ] Deploy Cloud Run only after billing/cost approval; verify `/health`.
- [ ] Deploy Firebase Hosting and verify the actual public URL.
- [ ] Test search, article detail, Firebase sign-in, favorite/library, tracker,
  alerts, and threaded comments against the hosted deployment.
- [ ] Add the deployed Hosting domain to Firebase Auth authorized domains.
- [ ] Review logs, IAM, secrets, and billing after deployment.
