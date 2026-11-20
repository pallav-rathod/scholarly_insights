from __future__ import annotations

from functools import wraps

from flask import current_app, g, jsonify, request


def _firebase_admin():
    if not current_app.config["FIREBASE_PROJECT_ID"]:
        raise RuntimeError("Firebase is not configured. Set FIREBASE_PROJECT_ID.")
    import firebase_admin
    from firebase_admin import auth, credentials

    try:
        app = firebase_admin.get_app()
    except ValueError:
        app = firebase_admin.initialize_app(
            credentials.ApplicationDefault(),
            {"projectId": current_app.config["FIREBASE_PROJECT_ID"]},
        )
    return auth, app


def require_user(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return jsonify(error="Sign in to continue."), 401
        try:
            from google.auth.exceptions import DefaultCredentialsError
            from firebase_admin.exceptions import FirebaseError

            firebase_auth, app = _firebase_admin()
            claims = firebase_auth.verify_id_token(token, app=app, check_revoked=True)
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 503
        except DefaultCredentialsError:
            current_app.logger.exception("Firebase Admin credentials are unavailable")
            return jsonify(error="Firebase server credentials are not configured."), 503
        except FirebaseError:
            current_app.logger.exception("Firebase ID token verification failed")
            return jsonify(error="Authentication could not be verified."), 401
        except ValueError:
            current_app.logger.info("Firebase ID token was invalid")
            return jsonify(error="Authentication could not be verified."), 401
        if not claims.get("uid"):
            return jsonify(error="Verified token did not contain a user ID."), 401
        g.user = {
            "uid": claims["uid"],
            "email": claims.get("email", ""),
            "display_name": claims.get("name", ""),
        }
        return view(*args, **kwargs)

    return wrapped
