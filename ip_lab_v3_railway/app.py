import csv
import io
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask, Response, abort, flash, redirect, render_template,
    request, session, url_for
)
from werkzeug.middleware.proxy_fix import ProxyFix

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DB_PATH", str(APP_DIR / "ip_lab.sqlite3")))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))
CONSENT_VERSION = "1.0"

if not SECRET_KEY:
    raise RuntimeError("Set SECRET_KEY in Railway Variables.")
if not ADMIN_PASSWORD:
    raise RuntimeError("Set ADMIN_PASSWORD in Railway Variables.")

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=16 * 1024,
)

# Railway's ingress proxy is expected to be the only route to this app.
# If your deployment has a different trusted proxy chain, adjust this count.
trusted_hops = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=trusted_hops, x_proto=trusted_hops)


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consented_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                consent_version TEXT NOT NULL
            )
        """)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
        conn.execute(
            "DELETE FROM consented_visits WHERE created_at < ?", (cutoff,)
        )


def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


@app.context_processor
def inject_csrf():
    return {"csrf_token": csrf_token}


def verify_csrf():
    supplied = request.form.get("_csrf", "")
    expected = session.get("_csrf", "")
    if not supplied or not expected or not secrets.compare_digest(supplied, expected):
        abort(400, "Invalid form token. Reload and try again.")


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    )
    return response


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/consent", methods=["POST"])
def consent():
    verify_csrf()
    if request.form.get("consent") != "yes":
        flash("No information was recorded because consent was not given.", "info")
        return redirect(url_for("index"))

    # ProxyFix sets remote_addr from the trusted Railway proxy header.
    # Do not deploy this app outside the configured trusted-proxy topology.
    ip = request.remote_addr or "unknown"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with db() as conn:
        conn.execute(
            """INSERT INTO consented_visits
               (created_at, ip_address, consent_version)
               VALUES (?, ?, ?)""",
            (timestamp, ip, CONSENT_VERSION),
        )

    return render_template("thanks.html", timestamp=timestamp)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        verify_csrf()
        supplied = request.form.get("password", "")
        if secrets.compare_digest(supplied, ADMIN_PASSWORD):
            session.clear()
            session["is_admin"] = True
            session["_csrf"] = secrets.token_urlsafe(32)
            return redirect(url_for("admin"))
        flash("Incorrect password.", "error")
    return render_template("login.html")


@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    verify_csrf()
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin", methods=["GET"])
@admin_required
def admin():
    with db() as conn:
        rows = conn.execute(
            """SELECT id, created_at, ip_address, consent_version
               FROM consented_visits ORDER BY id DESC LIMIT 500"""
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM consented_visits"
        ).fetchone()["n"]
    return render_template(
        "admin.html", rows=rows, total=total, retention_days=RETENTION_DAYS
    )


@app.route("/admin/export.csv", methods=["GET"])
@admin_required
def export_csv():
    with db() as conn:
        rows = conn.execute(
            """SELECT id, created_at, ip_address, consent_version
               FROM consented_visits ORDER BY id DESC"""
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "timestamp_utc", "ip_address", "consent_version"])
    for row in rows:
        writer.writerow([row["id"], row["created_at"], row["ip_address"], row["consent_version"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ip_lab_consented_visits.csv"},
    )


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


init_db()

if __name__ == "__main__":
    # Local development only. Railway runs Gunicorn via Procfile.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8080")), debug=False)
