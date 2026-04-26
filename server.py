import os
from flask import Flask, send_from_directory, send_file
from flask_cors import CORS
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Serve files from the same directory as this script (no public/ subfolder)
WEB_ROOT = os.path.dirname(os.path.abspath(__file__))

# Set SECRET_KEY in your environment — never hardcode it
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is not set")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static")
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB request limit

# CORS — restrict to your actual domain in production
CORS(app, origins=os.environ.get("ALLOWED_ORIGINS", "*"))

# Security headers
# FORCE_HTTPS=1 only if Flask is terminating SSL directly (not needed behind Nginx+SSL)
force_https = os.environ.get("FORCE_HTTPS", "0") == "1"
Talisman(
    app,
    force_https=force_https,
    strict_transport_security=force_https,
    content_security_policy={
        "default-src": "'self'",
        "script-src":  ["'self'", "'unsafe-inline'", "cdn.tailwindcss.com", "cdn.jsdelivr.net"],
        "style-src":   ["'self'", "'unsafe-inline'"],
        "img-src":     ["'self'", "data:", "https:"],
        "connect-src": ["'self'", "https://*.supabase.co"],
        "font-src":    ["'self'", "data:"],
    },
)

# Rate limiting — backed by memory by default
# Swap for Redis in production: RATELIMIT_STORAGE_URL=redis://localhost:6379
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute", "20 per second"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URL", "memory://"),
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_file(os.path.join(WEB_ROOT, "index.html"))


@app.route("/<path:path>")
def serve(path):
    full_path = os.path.join(WEB_ROOT, path)

    # If the exact file exists (JS, CSS, images, etc.), serve it directly
    if os.path.isfile(full_path):
        return send_from_directory(WEB_ROOT, path)

    # Fall back to index.html so the frontend router handles the path
    return send_file(os.path.join(WEB_ROOT, "index.html"))


# ---------------------------------------------------------------------------
# Dev entry point — Gunicorn is used in production (see gunicorn.conf.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)