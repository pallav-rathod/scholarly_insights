# Agent guide

This file is the handoff for an AI agent or developer who needs to understand,
run, test, modify, or deploy Scholarly Insight. Read this together with
[`README.md`](./README.md), [`run.md`](./run.md), and, when checking product
requirements, [`checklist.md`](./checklist.md) and the supplied midterm
presentation.

## Project summary

Scholarly Insight is a Python 3.11+ Flask application for discovering arXiv
papers. Flask queries the arXiv Atom API, renders the web UI, caches normalized
papers and searches, and provides authenticated user features. Firebase
Authentication is used for Google sign-in; user data is stored in the
application database, not Firestore.

The web UI is Flask/Jinja with browser JavaScript and responsive CSS. Do not
replace it with React or another frontend framework unless the user changes the
Python-first requirement.

## Start here

1. Read `README.md` for current setup and configuration.
2. Read `run.md` for exact local, test, Docker, and cloud-hosting procedures.
3. Read `description.md` for the original project objective.
4. Read `checklist.md`, review the supplied midterm presentation, and verify
   every feature/model claim against the current source and tests.
5. Inspect the specific source and tests before changing behavior. Treat the
   source and tests as authoritative if a document and the implementation
   differ, then update the related documentation.

## Important files

| Path | Responsibility |
|---|---|
| `wsgi.py` | Gunicorn entry point; exports `app`. |
| `app/__init__.py` | Flask app factory and environment configuration. |
| `app/routes.py` | HTML pages, JSON APIs, user actions, health check. |
| `app/arxiv.py` | arXiv query construction, TLS requests, Atom parsing, caching, throttling. |
| `app/db.py` | SQLite and PostgreSQL schemas, connections, persistence helpers. |
| `app/auth.py` | Firebase Admin ID-token verification for protected routes. |
| `app/insights.py` | Cached metadata summaries and related-paper ranking. |
| `app/refresh_trackers.py` | CLI to refresh all trackers and create in-app alerts. |
| `app/templates/` | Jinja pages. |
| `app/static/` | Browser JavaScript and CSS. |
| `tests/` | `unittest` coverage for routes, arXiv behavior, and database adapter. |
| `.env.example` | Local environment variable template; contains placeholders only. |
| `Dockerfile` | Non-root Gunicorn container listening on port 8080. |
| `docker-compose.yml` | Local SQLite-backed container and persistent local volume. |
| `firebase.json` | Firebase Hosting rewrite to Cloud Run service `scholarly-insight` in `us-central1`. |
| `.firebaserc` | Firebase project alias, currently `scholarly-insights-77069`. |
| `Scholarly Insight — Midterm Presentation.pdf` | Original product and architecture requirements. |
| `checklist.md` | Feature, technology, database, deployment, and credential-safety checklist. |

## Local development

Use Python 3.11 or newer. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create `.env` from `.env.example` only if `.env` does not already exist. Do not
overwrite a developer's existing configuration. Public search works without
Firebase configuration. Start the server with:

```bash
flask --app wsgi run --debug --host 127.0.0.1
```

Open `http://127.0.0.1:5000`. Prefer `127.0.0.1` over `localhost` on this
developer's Mac because `localhost:5000` previously reached another local
service. SQLite is initialized automatically at
`instance/scholarly_insight.sqlite3`. Stop the server with Ctrl+C.

Run tests with:

```bash
python -m unittest discover -s tests -v
```

Do not treat a successful unit test as proof that Firebase OAuth, PostgreSQL,
Cloud Run, Docker, or Firebase Hosting has been integration-tested.

## Configuration and data

- Local development defaults to SQLite. Set `DATABASE_PATH` only when a
  different local file location is needed.
- When `DATABASE_URL` is configured, the app uses PostgreSQL. In production,
  `APP_ENV=production`, `SECRET_KEY`, and `DATABASE_URL` are required.
- Application tables are created idempotently at startup. There is no
  versioned migration framework; review schema changes for both SQLite and
  PostgreSQL.
- Do not use Cloud Run's writable container filesystem as durable storage.
  Production is designed for Cloud SQL PostgreSQL.
- Search results are fetched on demand from
  `https://export.arxiv.org/api/query`. The app uses `feedparser` for Atom,
  `certifi` for verified TLS, a 24-hour default SQLite/PostgreSQL result cache,
  and a three-second default request interval.
- Cached results can be served stale for an exact query/page if arXiv is
  unavailable. Do not claim that cache coverage includes all arXiv papers.
- arXiv does not provide citation, download, or readership counts. Insights
  are based only on locally cached records.

## Authentication and secrets

- Firebase client configuration (`FIREBASE_PROJECT_ID`,
  `FIREBASE_WEB_API_KEY`, `FIREBASE_AUTH_DOMAIN`, and `FIREBASE_APP_ID`) is
  used by the browser to initialize Firebase Auth.
- Firebase Admin credentials are server-side secrets. Never print, inspect,
  commit, upload, or copy a service-account JSON key into an image or chat.
- Local Firebase authentication can use an external service-account file via
  `GOOGLE_APPLICATION_CREDENTIALS`, or suitable Application Default
  Credentials.
- Cloud Run should use its attached runtime service account and Application
  Default Credentials, not a downloaded service-account key.
- Protected routes verify Firebase ID tokens and use the verified UID for data
  ownership. Do not trust a UID supplied by the browser.
- `.gitignore` and `.dockerignore` exclude common local credential filenames,
  `.env`, the virtual environment, and SQLite instance data. Before a GitHub
  push, confirm no secret or local database is already tracked; ignore rules do
  not untrack previously committed files.

## Deployment guardrails

The prepared production architecture is:

```text
Browser -> Firebase Hosting -> Cloud Run (Flask/Gunicorn) -> Cloud SQL (PostgreSQL)
                      Firebase Authentication -> ID token verified by Flask
```

- Firebase Hosting is a proxy/static hosting layer; it does not run Flask.
- `firebase.json` rewrites all Hosting paths to Cloud Run service
  `scholarly-insight` in `us-central1`.
- The intended default public domain is
  `scholarly-insights-77069.web.app` (also `scholarly-insights-77069.firebaseapp.com`),
  not `*.firebase.com`. A custom domain must be owned by the user.
- Cloud Run is intentionally configured as publicly invokable so Firebase
  Hosting can reach it. Account-specific endpoints still require a verified
  Firebase ID token.
- Cloud Run, Cloud SQL, Secret Manager, and related services can incur charges.
  Do not enable billing, create billable resources, or deploy unless the user
  has explicitly authorized those actions in the active conversation. Check
  the current billing state and explain expected costs before provisioning.
- Never infer that deployment is live from configuration files alone. Check
  Cloud Run health, Firebase Hosting deployment, and the public URL.
- Follow `run.md` for IAM roles, Secret Manager values, database setup, deploy
  commands, and post-deployment checks. Do not put secret values in Git or
  command history.

## Product audit: accurate completion claims

The detailed evidence and status are tracked in `checklist.md`. Re-check the
current source and tests before making completion claims. Key caveats include:

- Search, article pages, reading history, and threaded comments are present.
- User accounts require working Firebase client configuration and server-side
  Admin credentials; tests use a fake Firebase verifier.
- Trackers and alerts exist, but refresh is manual or externally scheduled.
  Optional Resend email alerts (`RESEND_API_KEY`) are sent for newly created
  notifications only; an installed nightly scheduler is absent.
- Search/browse has text category filters, not a category catalog or trie-based
  autocomplete. There is no JSON article-details endpoint.
- Related-paper ranking uses TF-IDF-style text similarity and a category
  overlap bonus over cached papers. LDA topics, a separate next-read
  recommendation model, logistic-regression classification, and the planned
  model evaluations are not implemented.
- Threaded replies use parent IDs and recursive rendering. Edit/delete,
  moderation, and forum-wide discovery are not implemented.
- SQLite and PostgreSQL schemas are present; the notifications table is an
  addition to the presentation's proposed tables. Production PostgreSQL has
  not been integration-tested against a live instance.
- The presentation's React/Tailwind front end was replaced with Flask/Jinja
  and responsive CSS to satisfy the Python-first requirement.

## Handoff status

Deployment configuration and instructions are present, but do not assume the
application is online. At the last environment check, Firebase CLI could list
the configured Firebase project, while `gcloud` was not installed and billing
status could not be verified. No Cloud Run or Cloud SQL deployment was
confirmed. Re-check the current CLI, account, billing, and cloud-resource state
before proceeding.
