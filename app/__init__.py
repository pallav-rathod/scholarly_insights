from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from .db import close_db, init_app as init_db_app
from .routes import bp


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app_env = os.environ.get("APP_ENV", "development")
    secret_key = os.environ.get("SECRET_KEY")
    if app_env == "production" and not secret_key:
        raise RuntimeError("SECRET_KEY must be configured in production.")
    if app_env == "production" and not os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL must be configured in production.")
    app.config.from_mapping(
        APP_ENV=app_env,
        SECRET_KEY=secret_key or "local-development-only",
        DATABASE_URL=os.environ.get("DATABASE_URL", ""),
        DATABASE_PATH=os.environ.get(
            "DATABASE_PATH", str(Path(app.instance_path) / "scholarly_insight.sqlite3")
        ),
        FIREBASE_PROJECT_ID=os.environ.get("FIREBASE_PROJECT_ID", ""),
        FIREBASE_WEB_API_KEY=os.environ.get("FIREBASE_WEB_API_KEY", ""),
        FIREBASE_AUTH_DOMAIN=os.environ.get("FIREBASE_AUTH_DOMAIN", ""),
        FIREBASE_APP_ID=os.environ.get("FIREBASE_APP_ID", ""),
        FIREBASE_SERVICE_ACCOUNT_JSON=os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", ""),
        ARXIV_API_URL=os.environ.get(
            "ARXIV_API_URL", "https://export.arxiv.org/api/query"
        ),
        ARXIV_MIN_INTERVAL=float(os.environ.get("ARXIV_MIN_INTERVAL", "3")),
        ARXIV_CACHE_TTL=int(os.environ.get("ARXIV_CACHE_TTL", str(24 * 60 * 60))),
    )
    if test_config:
        app.config.update(test_config)
    try:
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    app.teardown_appcontext(close_db)
    init_db_app(app)
    app.register_blueprint(bp)
    return app
