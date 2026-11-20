# Scholarly Insight

A Python/Flask application for searching arXiv, saving papers, tracking research
topics, and discussing articles.

For an AI-agent entry point, see [`AGENTS.md`](./AGENTS.md), then
[`Agent.md`](./Agent.md). For detailed local-run and hosting steps, see
[`run.md`](./run.md).

## Features

- Search arXiv by keyword, author, category, and submitted date; sort and page
  through results.
- View article details, arXiv/PDF links, related cached papers, and threaded
  comments.
- Sign in with Firebase Google authentication to manage favorites, reading
  history, trackers, and in-app alerts.
- Browse locally cached category/author/month summaries.
- Cache normalized searches in SQLite for 24 hours and serialize outbound
  arXiv requests with a minimum three-second gap.

arXiv does not provide citation, download, or readership counts. The insights
page only summarizes cached arXiv metadata and must not be interpreted as
those measures.

## Local setup

Use Python 3.11 or newer. From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and replace `SECRET_KEY` with a random value. Generate one with
`python -c "import secrets; print(secrets.token_hex(32))"`. For public search,
Firebase settings can stay blank. Start the server with:

```bash
flask --app wsgi run --debug
```

Open `http://localhost:5000`. Stop the server with Ctrl+C. The SQLite database
is created automatically at `instance/scholarly_insight.sqlite3`; set
`DATABASE_PATH` to choose another location.

The SQLite database is created automatically at `instance/scholarly_insight.sqlite3`.
Set `DATABASE_PATH` to choose another location.

For a local container, copy `.env.example` to `.env`, then run
`docker compose up --build`. The base Compose setup supports public search;
follow the Firebase Compose steps below to enable server-side authentication.

## Firebase Google sign-in

Firebase is used for authentication only. Favorites, reading history, trackers,
alerts, and discussions are stored in the local SQLite database; this project
does not need Firestore.

1. Open the [Firebase Console](https://console.firebase.google.com/) and
   create a project, or select an existing one.
2. In **Project settings → General → Your apps**, add a **Web app**. App
   registration does not require enabling Firebase Hosting. Copy the app's
   `apiKey`, `authDomain`, `projectId`, and `appId` into the matching
   `FIREBASE_WEB_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_PROJECT_ID`, and
   `FIREBASE_APP_ID` fields in your local `.env`.
3. In **Authentication → Sign-in method** (sometimes shown under
   **Authentication → Sign-in providers**), enable **Google** and choose a
   support email. Save the provider settings.
4. In **Authentication → Settings → Authorized domains**, ensure `localhost`
   is listed. If you open the app using `127.0.0.1`, add that hostname too.
   Authorized-domain entries do not include a port.
5. Configure credentials for Flask's Firebase Admin SDK so it can verify
   browser ID tokens. For local development, create a service-account key in
   **Project settings → Service accounts → Generate new private key**. Store
   the downloaded JSON outside this repository, then set
   `GOOGLE_APPLICATION_CREDENTIALS` in `.env` to its absolute path, for example:

   ```dotenv
   GOOGLE_APPLICATION_CREDENTIALS=/Users/yourname/.config/scholarly-insight/firebase-admin.json
   ```

   Protect the file and never commit, upload, or share it. Alternatively, use
   Google Application Default Credentials if they are configured for this
   project and have the required Firebase Authentication access.
6. Save `.env`, restart Flask, open `http://localhost:5000`, and click **Sign
   in**. The browser signs in with Google and sends the Firebase ID token to
   Flask; Flask verifies it before allowing account-specific operations.

The Firebase web app configuration is client configuration, not an Admin key.
The service-account JSON is a secret. If authentication returns a server
configuration error after Google sign-in succeeds, check that
`GOOGLE_APPLICATION_CREDENTIALS` points to a readable key for the same
Firebase project, then restart Flask.

For Docker Compose, place the key at
`firebase-service-account.json` locally (it is gitignored), then run:

```bash
docker compose -f docker-compose.yml -f docker-compose.firebase.yml up --build
```

The base Compose setup without the Firebase override still supports public
search and browse.

## Production deployment: Firebase Hosting + Cloud Run + Cloud SQL

Firebase Hosting serves the public `*.web.app` site and forwards requests to
the Flask service on Cloud Run. Cloud SQL for PostgreSQL stores the app data;
Firebase Authentication continues to handle Google sign-in. Firebase Hosting
does not run Python itself.

This deployment uses billable Google Cloud services. Upgrading the Firebase
project from Spark to Blaze requires linking a billing account, and Cloud Run,
Cloud SQL, Secret Manager, and network usage can incur charges. Set budget
alerts before creating resources; a budget alert is not a spending cap. These
steps prepare the project but do not create or deploy cloud resources.

### 1. Prepare Google Cloud and Firebase

1. Install and authenticate the Google Cloud CLI (`gcloud`) and Firebase CLI
   (`firebase`). Sign in to both with an account that can administer the
   `scholarly-insights-77069` project.
2. Link billing to that Firebase project in the Firebase Console and upgrade
   the project to Blaze. Review current Cloud Run and Cloud SQL pricing first.
3. In Google Cloud Console, enable Cloud Run, Cloud Build, Artifact Registry,
   Cloud SQL Admin, and Secret Manager APIs.
4. Create a Cloud SQL for PostgreSQL instance and database named
   `scholarly_insight` in `us-central1` (the same region as the configured
   Cloud Run service). Create a dedicated database user. The application's
   startup initializes its schema, so this user must be able to create tables
   and indexes in the database, as well as read and write application data.
5. Create a dedicated Cloud Run runtime service account. Grant it **Cloud SQL
   Client** (`roles/cloudsql.client`) and **Firebase Authentication Viewer**
   (`roles/firebaseauth.viewer`) in the project. The latter provides the
   read-only Firebase Auth access used to verify revoked ID tokens. Grant it
   **Secret Manager Secret Accessor** (`roles/secretmanager.secretAccessor`)
   only on the two secrets created in the next step.
6. In Secret Manager, create secrets named `scholarly-secret-key` and
   `scholarly-database-url`. Use a newly generated random Flask secret key.
   The database URL should use the Cloud SQL Unix socket and URL-encode
   reserved characters in the database password:

   ```text
   postgresql://DB_USER:URL_ENCODED_PASSWORD@/scholarly_insight?host=%2Fcloudsql%2FPROJECT_ID%3Aus-central1%3AINSTANCE_ID&sslmode=disable
   ```

   Keep both values in Secret Manager; do not put production credentials in
   `.env`, source control, or a service-account JSON file.

### 2. Deploy the Flask service

From the project directory, set the shell variables for your own Cloud SQL
instance and runtime service account, then deploy the existing Dockerfile:

```bash
PROJECT_ID=scholarly-insights-77069
REGION=us-central1
INSTANCE_CONNECTION_NAME="${PROJECT_ID}:us-central1:INSTANCE_ID"
RUNTIME_SERVICE_ACCOUNT=YOUR_RUNTIME_SERVICE_ACCOUNT

gcloud run deploy scholarly-insight \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service-account "$RUNTIME_SERVICE_ACCOUNT" \
  --add-cloudsql-instances "$INSTANCE_CONNECTION_NAME" \
  --set-env-vars "APP_ENV=production,FIREBASE_PROJECT_ID=$PROJECT_ID,FIREBASE_AUTH_DOMAIN=scholarly-insights-77069.firebaseapp.com,FIREBASE_WEB_API_KEY=YOUR_WEB_API_KEY,FIREBASE_APP_ID=YOUR_FIREBASE_APP_ID,ARXIV_MIN_INTERVAL=3" \
  --set-secrets "SECRET_KEY=scholarly-secret-key:latest,DATABASE_URL=scholarly-database-url:latest" \
  --allow-unauthenticated
```

Replace the instance, service-account, Web API key, and Firebase App ID
placeholders with their actual values. The Firebase web configuration values
are client configuration; never put the Admin SDK's private key in the
container. Cloud Run uses its attached runtime identity and Application
Default Credentials.

Wait for the deployment to finish and copy the Cloud Run service URL. Check
that `https://YOUR_CLOUD_RUN_URL/health` returns `{"status":"ok"}` before
deploying Hosting. If startup fails, inspect the Cloud Run logs for database
connectivity, schema permission, missing secret access, and Firebase Admin
permission errors.

### 3. Deploy Firebase Hosting

The checked-in `firebase.json` rewrites every Hosting path to the
`scholarly-insight` Cloud Run service in `us-central1`, and `.firebaserc`
selects `scholarly-insights-77069`. Once the Cloud Run service is healthy, run:

```bash
firebase deploy --only hosting --project scholarly-insights-77069
```

Firebase prints the public `https://scholarly-insights-77069.web.app` URL
(and typically a `firebaseapp.com` URL). In **Firebase Console →
Authentication → Settings → Authorized domains**, add
`scholarly-insights-77069.web.app` so Google sign-in works on the deployed
site. Open the Hosting URL, test search, sign-in, and an account-specific
feature, then review Cloud Run logs and billing.

These files prepare deployment but do not prove that the configured Cloud Run or
Firebase Hosting services are live. Keep any local Firebase Admin key out of
Git and Docker; check current cloud resources and billing before deployment.

## Run the tests

With the virtual environment active:

```bash
python -m unittest discover -s tests -v
```

Firebase's web configuration identifies the project and is intended for client
use; the Admin service-account credential is secret. Flask verifies every
protected request's Firebase ID token and derives the database user ID from
the verified token, never from client-provided user IDs. User data is stored
in the local SQLite database, not Firestore.

## Tracker refresh

Refresh trackers with `python -m app.refresh_trackers`. To run it nightly,
schedule that command with the host's scheduler. Tracker refreshes bypass a
fresh search-cache entry so newly published matches are checked; outbound
requests still share the three-second throttle. The command records matching
papers as in-app notifications. It does not send email.

## Data/API behavior

- arXiv is queried through its Atom API. The application makes at most one
  request at a time and waits at least three seconds between upstream calls.
- Python HTTPS requests use the `certifi` CA bundle; this avoids missing
  certificate-store configuration in some macOS Python installations while
  retaining normal TLS certificate verification.
- Results are fetched only on demand, in pages of up to 50. Repeated normalized
  searches use SQLite cache for 24 hours.
- If arXiv is unavailable, an expired cached result for that exact query can
  still be served and is marked stale.
- Search terms are encoded by the URL client and filters are validated before
  query construction. Every paper links back to arXiv.
- Keep requests reasonable and observe the current arXiv API User's Manual.
