"""Flask application factory for the Study 4 rating web app.

Run locally from this directory:
    python run.py

The app is intentionally single-process and stateless per request: all
durable state lives in the participant's server-side session plus the
append-only JSONL log written by :mod:`study4.storage`.
"""
from __future__ import annotations

from pathlib import Path
from datetime import timedelta

from flask import Flask, request
from werkzeug.middleware.proxy_fix import ProxyFix

_THIS = Path(__file__).resolve()

from .settings import settings
from .routes import bp


def create_app(config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(_THIS.parent / "templates"),
        static_folder=str(_THIS.parent / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=settings.SECRET_KEY,
        STUDY_SETTINGS=settings,
        LOCAL_ASSIGNMENT=None,
        SESSION_COOKIE_NAME="uncertainty_grading_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=settings.COOKIE_SECURE,
        SESSION_COOKIE_SAMESITE=settings.COOKIE_SAMESITE,
        PERMANENT_SESSION_LIFETIME=timedelta(
            minutes=settings.SESSION_LIFETIME_MINUTES),
        TRUST_PROXY_PROTO=settings.TRUST_PROXY_PROTO,
        HSTS_ENABLED=settings.HSTS_ENABLED,
        HSTS_MAX_AGE=settings.HSTS_MAX_AGE,
        HSTS_INCLUDE_SUBDOMAINS=settings.HSTS_INCLUDE_SUBDOMAINS,
        HSTS_PRELOAD=settings.HSTS_PRELOAD,
    )
    if config:
        app.config.update(config)

    if app.config["TRUST_PROXY_PROTO"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

    hsts_directives = [f"max-age={app.config['HSTS_MAX_AGE']}"]
    if app.config["HSTS_INCLUDE_SUBDOMAINS"]:
        hsts_directives.append("includeSubDomains")
    if app.config["HSTS_PRELOAD"]:
        hsts_directives.append("preload")
    hsts_value = "; ".join(hsts_directives)

    @app.after_request
    def add_hsts_header(response):
        if app.config["HSTS_ENABLED"] and request.is_secure:
            response.headers["Strict-Transport-Security"] = hsts_value
        return response

    app.register_blueprint(bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=settings.HOST, port=settings.PORT, debug=settings.DEBUG)
