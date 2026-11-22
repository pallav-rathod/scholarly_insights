# Run and hosting guide

This runbook covers local execution, Firebase sign-in, tests, optional
containers, and the prepared public-hosting architecture. Read
[`Agent.md`](./Agent.md) for handoff guidance, [`README.md`](./README.md) for
the project overview, and [`checklist.md`](./checklist.md) for the tracked
feature and deployment status.

## 1. What the application does

Scholarly Insight is a Python/Flask web app that searches the arXiv Atom API.
It renders search results and article pages, caches normalized search results
and article records, and offers Firebase-authenticated features including
favorites, reading history, trackers, in-app alerts, and article discussions.

Firebase Auth is used for identity. Application data is stored in SQLite for
local development and PostgreSQL for the prepared production deployment. The
app does not use Firestore.

## 2. Run locally

### Requirements

- Python 3.11 or newer.
- Internet access for live arXiv searches.
- Firebase configuration and credentials are optional for public search, but
  required for Google sign-in and protected account features.

### Setup

From the project directory:

```bash
cd /path/to/scholarly_insights
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If `.env` does not exist, create it from the example:

```bash
cp .env.example .env
```

Do not overwrite an existing `.env`; it may contain local Firebase settings.
At minimum, replace the example `SECRET_KEY` with a random value. Generate one
without putting it in source control:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

The app defaults to SQLite at
`instance/scholarly_insight.sqlite3`. The database and tables are initialized
automatically. Keep the `DATABASE_URL` field empty for local SQLite.

### Start and open the app

```bash
flask --app wsgi run --debug --host 127.0.0.1
```

Visit **http://127.0.0.1:5000**. Use `127.0.0.1` rather than `localhost` if
`localhost:5000` reaches another service or returns an unexpected response.
Stop the server with Ctrl+C.

If port 5000 is already occupied, use another port:

```bash
flask --app wsgi run --debug --host 127.0.0.1 --port 5001
```

Then open `http://127.0.0.1:5001`.

### Firebase Google sign-in (local)

1. In Firebase Console, confirm Google is enabled under
   **Authentication → Sign-in method**.
2. Under **Authentication → Settings → Authorized domains**, add
   `localhost` and, if using it in the browser, `127.0.0.1`.
3. Set the Web app values in `.env`:
   `FIREBASE_PROJECT_ID`, `FIREBASE_WEB_API_KEY`, `FIREBASE_AUTH_DOMAIN`,
   `FIREBASE_APP_ID`.
4. Configure Firebase Admin credentials for the same Firebase project. Prefer
   Application Default Credentials when available. Otherwise, keep the
   service-account JSON outside the repository and set
   `GOOGLE_APPLICATION_CREDENTIALS` in `.env` to its absolute path.
5. Restart Flask and test Google sign-in.

Never paste or commit the Admin service-account JSON. The Firebase web app
configuration is client configuration; the Admin key is secret.

### Local Docker Compose (optional)

Start Docker Desktop first, then from the repository root:

```bash
docker compose up --build
```

Open `http://127.0.0.1:8080` (or the host port set by `PORT` in `.env`). Compose
persists SQLite data in a named Docker volume. For Firebase Admin credentials,
use the optional override:

```bash
docker compose -f docker-compose.yml -f docker-compose.firebase.yml up --build
```

The override mounts `firebase-service-account.json` read-only. Place the key
there only for local use, and never commit it.

## 3. Run tests

With the virtual environment active:

```bash
python -m unittest discover -s tests -v
```

Python syntax compilation can also be checked with:

```bash
python -m compileall -q app tests wsgi.py
```

The suite covers query validation and parsing, arXiv cache behavior, routes,
authentication guards, favorites/history, trackers, comments, and the
PostgreSQL connection adapter. Unit tests do not prove live Firebase OAuth,
Cloud SQL connectivity, Cloud Run deployment, or Firebase Hosting behavior.

## 4. Useful routes and maintenance

- `/` - home and cached-data summary.
- `/search` - HTML search page.
- `/api/search?q=graph` - JSON arXiv search endpoint.
- `/api/insights` - summary calculated from cached article records.
- `/article/<arxiv-id>` - article details, related cached papers, and comments.
- `/health` - returns `{"status":"ok"}` when the Flask app is responding.
- `/api/library`, `/api/trackers`, and `/api/alerts` - authenticated user
  features.

Searches are on-demand, paginated (up to 50 papers), and cached for 24 hours by
default. The app attempts to maintain at least a three-second gap between
arXiv requests. Cached insights describe only records the app has collected;
they are not global arXiv statistics. arXiv does not provide citation,
download, or readership counts.

Refresh all trackers manually with:

```bash
python -m app.refresh_trackers
```

No scheduler is configured by this command. To refresh nightly, provision an
external scheduler after deployment and monitor its logs. Alerts are stored in-app. When `RESEND_API_KEY` is configured, each refresh
also emails the tracker owner (their account email) about newly created
alerts only; without it, email delivery is skipped.

## 5. Production hosting architecture and status

The prepared architecture is:

```text
Public browser
    -> Firebase Hosting
    -> Cloud Run service scholarly-insight (Flask/Gunicorn)
    -> Cloud SQL for PostgreSQL

Google sign-in -> Firebase Authentication -> verified ID token in Flask
```

Firebase Hosting does not execute Python. The checked-in `firebase.json`
rewrites all requests to Cloud Run service `scholarly-insight` in
`us-central1`. The project configured in `.firebaserc` is
`scholarly-insights-77069`.

**Deployment is not confirmed live.** The workspace contains preparation and
deployment configuration, but no successful Cloud Run or Hosting deployment
was verified in this conversation. At the last check, Firebase CLI could list
the Firebase project; `gcloud` was not installed and billing status remained
unknown. Check the current project state rather than relying on this note.

The intended default public URL is:

- `https://scholarly-insights-77069.web.app`
- `https://scholarly-insights-77069.firebaseapp.com`

Firebase does not provide a default `*.firebase.com` domain. A custom domain
must be registered/owned by the user and then connected in Firebase Hosting.

## 6. Deploy to Firebase Hosting + Cloud Run + Cloud SQL

This deployment requires a Firebase project on the Blaze plan with a linked
billing account. Cloud Run, Cloud SQL, Secret Manager, builds, storage, and
network usage can incur charges. Set budget alerts, but note that budget alerts
are not hard spending limits. Review current prices and confirm the selected
database sizing before creating resources.

### Step A: install and authenticate CLIs

Install the Google Cloud CLI from [Google's official installation
guide](https://cloud.google.com/sdk/docs/install), choosing the package for
your operating system and CPU. Install Firebase CLI with Node.js/npm:

```bash
npm install -g firebase-tools
```

Open a new terminal after installation, then authenticate:

```bash
gcloud auth login
gcloud config set project scholarly-insights-77069
firebase login
firebase projects:list
```

Do not paste access tokens, OAuth codes, passwords, or service-account JSON
into chat or source files.

Check whether billing is linked:

```bash
gcloud billing projects describe scholarly-insights-77069
```

If it is not linked, the project owner must link a billing account and upgrade
the Firebase project to Blaze in the Firebase/Google Cloud Console before
billable resources can be provisioned.

### Step B: enable APIs and prepare the database

Enable the APIs needed for source builds and runtime services:

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  --project scholarly-insights-77069
```

Create a Cloud SQL for PostgreSQL instance in `us-central1`, a database named
`scholarly_insight`, and a dedicated application database user. Record the
instance connection name (`PROJECT_ID:REGION:INSTANCE_ID`). The app initializes
tables/indexes on startup; the runtime database user therefore needs permission
to create them in the database schema as well as read and write application
data.

Do not use the local SQLite database for production. Cloud Run's container
filesystem is not durable across instance replacement.

### Step C: create runtime identity and secrets

Create a dedicated Cloud Run runtime service account. Grant it:

- `roles/cloudsql.client` for the Cloud SQL instance.
- `roles/firebaseauth.viewer` for Firebase ID-token revocation checks.
- `roles/secretmanager.secretAccessor` on only the two secrets below.

Create these Secret Manager secrets and add secret versions:

- `scholarly-secret-key`: a newly generated random Flask `SECRET_KEY`.
- `scholarly-database-url`: the Cloud SQL PostgreSQL connection URI.

Use the Unix socket URI format below, substituting your values and URL-encoding
reserved characters in the database password:

```text
postgresql://DB_USER:URL_ENCODED_PASSWORD@/scholarly_insight?host=%2Fcloudsql%2FPROJECT_ID%3Aus-central1%3AINSTANCE_ID&sslmode=disable
```

Keep the values in Secret Manager; do not put production secrets in `.env`,
GitHub, or a service-account key file.

### Step D: deploy Cloud Run

Get the Firebase Web app's `apiKey` and `appId` from Firebase Console. They are
client configuration values, not the Admin key. From the project root, replace
the placeholders and deploy:

```bash
PROJECT_ID=scholarly-insights-77069
REGION=us-central1
INSTANCE_CONNECTION_NAME="${PROJECT_ID}:us-central1:YOUR_INSTANCE_ID"
RUNTIME_SERVICE_ACCOUNT="YOUR_RUNTIME_SERVICE_ACCOUNT_EMAIL"

gcloud run deploy scholarly-insight \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service-account "$RUNTIME_SERVICE_ACCOUNT" \
  --add-cloudsql-instances "$INSTANCE_CONNECTION_NAME" \
  --set-env-vars "APP_ENV=production,FIREBASE_PROJECT_ID=$PROJECT_ID,FIREBASE_AUTH_DOMAIN=${PROJECT_ID}.firebaseapp.com,FIREBASE_WEB_API_KEY=YOUR_WEB_API_KEY,FIREBASE_APP_ID=YOUR_FIREBASE_APP_ID,ARXIV_MIN_INTERVAL=3" \
  --set-secrets "SECRET_KEY=scholarly-secret-key:latest,DATABASE_URL=scholarly-database-url:latest" \
  --allow-unauthenticated
```

The service is publicly invokable so Firebase Hosting can proxy requests.
Account-specific Flask APIs still require a valid Firebase token. Cloud Run
uses its attached runtime service account; do not upload the Admin service
account JSON.

Wait for Cloud Run to finish deploying. Check the service's `/health` endpoint:

```bash
curl -fsS "https://YOUR_CLOUD_RUN_URL/health"
```

Expected response:

```json
{"status":"ok"}
```

If startup fails, inspect Cloud Run logs. Common causes include a malformed
`DATABASE_URL`, missing Cloud SQL attachment, database schema permissions,
missing Secret Manager access, or missing Firebase Auth Viewer permission.

### Step E: deploy Firebase Hosting and enable sign-in domain

After Cloud Run is healthy, from the project root run:

```bash
firebase deploy --only hosting --project scholarly-insights-77069
```

Add `scholarly-insights-77069.web.app` to **Firebase Console →
Authentication → Settings → Authorized domains**. Then test the Hosting URL:

1. Search for a paper and open its article page.
2. Sign in with Google.
3. Save a favorite and check the library.
4. Create a tracker and confirm alerts are in-app.
5. Check the Cloud Run health endpoint and logs.
6. Review billing and budgets.

## 7. GitHub and secret-safety checklist

Before pushing this project:

- Ensure `.env`, `.venv/`, `instance/`, `firebase-admin.json`, and
  `firebase-service-account.json` are not staged or tracked.
- `.gitignore` and `.dockerignore` include these local secret/data paths, but
  ignored files can still be present locally. If a key has ever been committed,
  removing it from the latest commit is insufficient: revoke/rotate the key and
  clean the repository history as appropriate.
- Do not include production `DATABASE_URL`, `SECRET_KEY`, OAuth tokens, or
  database passwords in commits or issue reports.
- Public Firebase Web config values may be used by the browser, but do not
  confuse them with Firebase Admin credentials.
- Do not claim the website is deployed until the Cloud Run health check and
  Firebase Hosting URL both work.

## 8. Presentation audit highlights

These highlights summarize the earlier presentation review; verify the current
source and tests before claiming any item is complete. See
[`checklist.md`](./checklist.md) for the detailed itemized status.

- Search, article detail pages, history, and threaded discussion are present.
- Firebase account features depend on correct external Firebase configuration.
- Trackers and deduplicated in-app alerts are present, but no nightly scheduler
  or email delivery is configured.
- The app has no category directory, autocomplete/trie, REST article-detail
  endpoint, comment moderation/edit/delete, or forum-wide discovery.
- Related-paper ranking uses TF-IDF-style text similarity over cached papers
  plus category overlap. LDA topic modeling, next-read recommendations,
  logistic-regression classification, and model evaluation are not implemented.
- The schema follows the proposed SQLite tables and adds notifications.
  PostgreSQL support is prepared but has not been verified against a live
  PostgreSQL instance.
- The original requirements are in the supplied midterm presentation PDF.
