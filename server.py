import json
import os
import urllib.request
import urllib.error
import stripe
from flask import Flask, Response, send_from_directory, send_file, request, jsonify
from flask_cors import CORS
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Serve files from the same directory as this script (no public/ subfolder)
WEB_ROOT = os.path.dirname(os.path.abspath(__file__))

# Set SECRET_KEY in your environment — never hardcode it
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is not set")

SUPABASE_URL          = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY     = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY  = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

STRIPE_SECRET_KEY     = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID       = os.environ.get("STRIPE_PRICE_ID", "")
SITE_URL              = os.environ.get("SITE_URL", "").rstrip("/")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static")
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB request limit

# Trust one upstream reverse proxy so rate-limiting uses the real client IP
# Set BEHIND_PROXY=1 when running behind Nginx, Heroku router, etc.
if os.environ.get("BEHIND_PROXY", "0") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# CORS — only enable when ALLOWED_ORIGINS is explicitly set (never default to *)
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "")
if _allowed_origins:
    CORS(app, origins=[o.strip() for o in _allowed_origins.split(",")])

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

@app.route("/config.js")
def config_js():
    js = f"window.FILEO_CONFIG={{url:{json.dumps(SUPABASE_URL)},anon:{json.dumps(SUPABASE_ANON_KEY)}}};"
    return Response(js, mimetype="application/javascript",
                    headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


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
# Stripe helpers
# ---------------------------------------------------------------------------

def _verify_supabase_token(token):
    """Call Supabase /auth/v1/user to verify the JWT and return (user_id, email)."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None, None
    try:
        req = urllib.request.Request(
            SUPABASE_URL + "/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_ANON_KEY,
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("id"), data.get("email", "")
    except Exception:
        return None, None


def _activate_pro(user_id):
    """Set app_metadata.is_pro=true for a Supabase user via the Admin API."""
    if not SUPABASE_SERVICE_KEY or not SUPABASE_URL:
        return False
    try:
        body = json.dumps({"app_metadata": {"is_pro": True}}).encode()
        req = urllib.request.Request(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            data=body,
            method="PUT",
        )
        req.add_header("apikey", SUPABASE_SERVICE_KEY)
        req.add_header("Authorization", f"Bearer {SUPABASE_SERVICE_KEY}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


@app.route("/create-checkout-session", methods=["POST"])
@limiter.limit("10 per minute")
def create_checkout_session():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401

    token = auth[7:]
    user_id, user_email = _verify_supabase_token(token)
    if not user_id:
        return jsonify({"error": "Invalid or expired session"}), 401

    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        return jsonify({"error": "Payments not configured on this server"}), 503

    base = SITE_URL or request.host_url.rstrip("/")
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            customer_email=user_email or None,
            allow_promotion_codes=True,
            success_url=base + "/?upgrade=success&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base + "/?upgrade=cancelled",
            metadata={"user_id": user_id},
        )
        return jsonify({"url": session.url})
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stripe-webhook", methods=["POST"])
@limiter.exempt
def stripe_webhook():
    payload   = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({"error": "Webhook not configured"}), 503

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("metadata", {}).get("user_id")
        if user_id:
            _activate_pro(user_id)

    return jsonify({"received": True})


# ---------------------------------------------------------------------------
# Dev entry point — Gunicorn is used in production (see gunicorn.conf.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=int(os.environ.get("PORT", 5001)))