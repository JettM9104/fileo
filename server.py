import json
import logging
import os
import urllib.request
import urllib.error
import urllib.parse
import stripe

log = logging.getLogger(__name__)

try:
    import boto3
    _HAS_BOTO3 = True
except ImportError:
    _HAS_BOTO3 = False

try:
    from dotenv import load_dotenv
    _here = os.path.dirname(os.path.abspath(__file__))
    for _candidate in [
        os.path.join(_here, ".env"),
        os.path.join(_here, "../../../.env"),  # git worktree: up to repo root
    ]:
        if os.path.exists(_candidate):
            load_dotenv(_candidate)
            break
except ImportError:
    pass
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
API_BASE_URL          = os.environ.get("API_BASE_URL", "").rstrip("/")

R2_ACCOUNT_ID        = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID     = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME       = os.environ.get("R2_BUCKET_NAME", "")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

_r2 = None
if _HAS_BOTO3 and all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
    _r2 = boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )

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
_connect_src = ["'self'", "https://*.supabase.co", "https://*.r2.cloudflarestorage.com"]
if API_BASE_URL:
    _connect_src.append(API_BASE_URL)
Talisman(
    app,
    force_https=force_https,
    strict_transport_security=force_https,
    content_security_policy={
        "default-src": "'self'",
        "script-src":  ["'self'", "'unsafe-inline'", "cdn.tailwindcss.com", "cdn.jsdelivr.net"],
        "style-src":   ["'self'", "'unsafe-inline'"],
        "img-src":     ["'self'", "data:", "https:"],
        "connect-src": _connect_src,
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
    js = (
        "window.FILEO_CONFIG="
        + json.dumps({
            "url": SUPABASE_URL,
            "anon": SUPABASE_ANON_KEY,
            "apiBaseUrl": API_BASE_URL,
        })
        + ";"
    )
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
        log.error("_activate_pro: missing SUPABASE_SERVICE_KEY or SUPABASE_URL")
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
            ok = resp.status == 200
            if not ok:
                log.error("_activate_pro: Supabase returned HTTP %s for user %s", resp.status, user_id)
            return ok
    except Exception as exc:
        log.error("_activate_pro failed for user %s: %s", user_id, exc)
        return False


# ---------------------------------------------------------------------------
# R2 helpers
# ---------------------------------------------------------------------------

def _get_file_record(file_id):
    """Fetch a file record from Supabase by id."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None
    try:
        safe_id = urllib.parse.quote(file_id, safe="")
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/files?id=eq.{safe_id}&select=id,storage_path,expires_at,user_id",
        )
        req.add_header("apikey", SUPABASE_SERVICE_KEY)
        req.add_header("Authorization", f"Bearer {SUPABASE_SERVICE_KEY}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            rows = json.loads(resp.read())
            return rows[0] if rows else None
    except Exception:
        return None


def _delete_file_db(file_id, user_id):
    """Delete a file record owned by user_id."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return False
    try:
        safe_id  = urllib.parse.quote(file_id, safe="")
        safe_uid = urllib.parse.quote(user_id, safe="")
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/files?id=eq.{safe_id}&user_id=eq.{safe_uid}",
            method="DELETE",
        )
        req.add_header("apikey", SUPABASE_SERVICE_KEY)
        req.add_header("Authorization", f"Bearer {SUPABASE_SERVICE_KEY}")
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


def _delete_r2_object(key):
    if _r2:
        try:
            _r2.delete_object(Bucket=R2_BUCKET_NAME, Key=key)
        except Exception:
            pass


@app.route("/upload-url", methods=["POST"])
@limiter.limit("30 per minute")
def upload_url():
    """Return a presigned PUT URL so the browser can upload directly to R2."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth[7:]
    user_id, _ = _verify_supabase_token(token)
    if not user_id:
        return jsonify({"error": "Invalid or expired session"}), 401

    if not _r2:
        return jsonify({"error": "Storage not configured"}), 503

    body = request.get_json(silent=True) or {}
    key          = body.get("key", "")
    content_type = body.get("content_type", "application/octet-stream")

    if not key or not key.startswith(user_id + "/"):
        return jsonify({"error": "Invalid key"}), 400

    try:
        url = _r2.generate_presigned_url(
            "put_object",
            Params={"Bucket": R2_BUCKET_NAME, "Key": key, "ContentType": content_type},
            ExpiresIn=900,
        )
        return jsonify({"url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download-url/<file_id>", methods=["GET"])
@limiter.limit("120 per minute")
def download_url(file_id):
    """Return a short-lived presigned GET URL for a file stored in R2."""
    if not _r2:
        return jsonify({"error": "Storage not configured"}), 503

    rec = _get_file_record(file_id)
    if not rec or not rec.get("storage_path"):
        return jsonify({"error": "File not found"}), 404

    try:
        url = _r2.generate_presigned_url(
            "get_object",
            Params={"Bucket": R2_BUCKET_NAME, "Key": rec["storage_path"]},
            ExpiresIn=3600,
        )
        return jsonify({"url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/file/<file_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
def delete_file(file_id):
    """Delete a file from R2 and the Supabase DB (owner only)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth[7:]
    user_id, _ = _verify_supabase_token(token)
    if not user_id:
        return jsonify({"error": "Invalid or expired session"}), 401

    rec = _get_file_record(file_id)
    if not rec:
        return jsonify({"error": "Not found"}), 404
    if rec.get("user_id") != user_id:
        return jsonify({"error": "Forbidden"}), 403

    if rec.get("storage_path"):
        _delete_r2_object(rec["storage_path"])

    _delete_file_db(file_id, user_id)
    return jsonify({"ok": True})


@app.route("/r2-cleanup", methods=["POST"])
@limiter.limit("10 per minute")
def r2_cleanup():
    """Delete an R2 object the caller owns (used to roll back a failed upload)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth[7:]
    user_id, _ = _verify_supabase_token(token)
    if not user_id:
        return jsonify({"error": "Invalid or expired session"}), 401

    body = request.get_json(silent=True) or {}
    key = body.get("key", "")
    if not key or not key.startswith(user_id + "/"):
        return jsonify({"error": "Forbidden"}), 403

    _delete_r2_object(key)
    return jsonify({"ok": True})


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


@app.route("/activate-pro-from-session", methods=["POST"])
@limiter.limit("5 per minute")
def activate_pro_from_session():
    """Fallback: verify a completed Stripe checkout session and activate Pro.

    Called by the client when the webhook may have been missed. Security is
    enforced by requiring the authenticated user's own session_id — the
    checkout metadata must carry the same user_id as the bearer token.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401
    token = auth[7:]
    user_id, _ = _verify_supabase_token(token)
    if not user_id:
        return jsonify({"error": "Invalid or expired session"}), 401

    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Payments not configured"}), 503

    body = request.get_json(silent=True) or {}
    session_id = body.get("session_id", "").strip()
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    try:
        checkout = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError as e:
        log.error("activate_pro_from_session: stripe error for user %s: %s", user_id, e)
        return jsonify({"error": str(e)}), 400

    if checkout.get("metadata", {}).get("user_id") != user_id:
        log.warning("activate_pro_from_session: session %s does not belong to user %s", session_id, user_id)
        return jsonify({"error": "Session does not belong to this account"}), 403

    if checkout.get("payment_status") not in ("paid", "no_payment_required"):
        return jsonify({"activated": False, "reason": "payment_incomplete"}), 200

    ok = _activate_pro(user_id)
    log.info("activate_pro_from_session: _activate_pro(%s) -> %s", user_id, ok)
    return jsonify({"activated": ok})


@app.route("/stripe-webhook", methods=["POST"], strict_slashes=False)
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
        log.info("stripe webhook: checkout.session.completed user_id=%s", user_id)
        if user_id:
            ok = _activate_pro(user_id)
            log.info("stripe webhook: _activate_pro(%s) -> %s", user_id, ok)
        else:
            log.error("stripe webhook: no user_id in metadata — metadata=%s", session.get("metadata"))

    return jsonify({"received": True})


# ---------------------------------------------------------------------------
# Dev entry point — Gunicorn is used in production (see gunicorn.conf.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=int(os.environ.get("PORT", 5001)))
