# IP Lab v3.0 — Railway deployment

A consent-based public IP logging lab. The public page explains what is collected and only records a visit after the visitor actively checks the consent box and submits the form. The admin dashboard and CSV export require a password.

## Included
- Public consent page
- IP address and UTC timestamp recorded only after consent
- Password-protected admin dashboard
- CSRF protection on forms
- Secure session cookie settings and basic security headers
- CSV export
- Automatic deletion of records older than `RETENTION_DAYS` when the app starts
- SQLite storage

## Deploy to Railway
1. Create a new GitHub repository and upload the contents of this folder.
2. In Railway, create a new project and deploy from that GitHub repository.
3. In the service's **Variables**, set:
   - `SECRET_KEY`: a long random secret (at least 32 random bytes).
   - `ADMIN_PASSWORD`: a unique, strong admin password.
   - `DB_PATH`: `/data/ip_lab.sqlite3`
   - `RETENTION_DAYS`: `30` (or your chosen retention period).
   - `TRUSTED_PROXY_HOPS`: `1` for the expected single trusted ingress proxy.
4. Add a Railway Volume to the service and mount it at `/data`. This is important: without a persistent volume, SQLite data may be lost when the container is replaced.
5. Generate a Railway public domain and wait for deployment to become healthy.
6. Visit the public domain. The admin dashboard is at `/admin/login`.

## Local test
Python 3.10+ is recommended.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

Set environment variables before running. For local HTTP development, set `COOKIE_SECURE=0`, use `DB_PATH=./ip_lab.sqlite3`, and set `SECRET_KEY` and `ADMIN_PASSWORD`. Keep `COOKIE_SECURE=1` on Railway HTTPS, then run:

```bash
python app.py
```

Open `http://127.0.0.1:8080`.

## Important proxy/IP note
The app uses Werkzeug `ProxyFix` to read the client address from the forwarding header supplied by the configured trusted proxy. `TRUSTED_PROXY_HOPS=1` assumes requests reach the app only through Railway's ingress proxy. Do not expose the app through an additional untrusted reverse proxy or allow direct access to the application port. If your proxy topology changes, review and adjust the trusted hop count. Never trust arbitrary client-supplied forwarding headers.

## Privacy and operational notes
- Do not use this to identify, profile, threaten, or target people.
- The consent page states the exact data collected and that the administrator can see it.
- Declining consent creates no database record.
- IP addresses are personal data in many jurisdictions. Provide any additional privacy notice or legal basis required where you operate.
- Use a unique admin password and keep it private. Do not commit `.env` files or secrets to GitHub.
- SQLite is configured for a single Gunicorn worker. Do not increase worker count without moving to a database designed for concurrent multi-process writes.
- The app does not collect geolocation, browser fingerprints, or user-agent strings.
