import json
import os
import urllib.request
import urllib.error
import urllib.parse
import stripe

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

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM    = os.environ.get("RESEND_FROM_EMAIL", "Fileo <noreply@fileo.ca>")

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
Talisman(
    app,
    force_https=force_https,
    strict_transport_security=force_https,
    content_security_policy={
        "default-src": "'self'",
        "script-src":  ["'self'", "'unsafe-inline'", "cdn.tailwindcss.com", "cdn.jsdelivr.net"],
        "style-src":   ["'self'", "'unsafe-inline'"],
        "img-src":     ["'self'", "data:", "https:"],
        "connect-src": ["'self'", "https://*.supabase.co", "https://*.r2.cloudflarestorage.com"],
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


def _send_email(to_email, subject, html_body):
    """Send a transactional email via the Resend API."""
    if not RESEND_API_KEY:
        return False
    try:
        body = json.dumps({
            "from": RESEND_FROM,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }).encode()
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=body,
            method="POST",
        )
        req.add_header("Authorization", f"Bearer {RESEND_API_KEY}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception:
        return False


def _find_user_by_email(email):
    """Return the Supabase user_id for a given email, or None."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None
    try:
        safe_email = urllib.parse.quote(email, safe="@")
        req = urllib.request.Request(
            f"{SUPABASE_URL}/auth/v1/admin/users?email={safe_email}&page=1&per_page=1",
        )
        req.add_header("apikey", SUPABASE_SERVICE_KEY)
        req.add_header("Authorization", f"Bearer {SUPABASE_SERVICE_KEY}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            for user in data.get("users", []):
                if user.get("email", "").lower() == email.lower():
                    return user.get("id")
    except Exception:
        pass
    return None


def _invite_user(email, name=""):
    """Invite a new Supabase user (creates account + sends magic-link email).
    Returns user_id on success, None otherwise."""
    if not SUPABASE_SERVICE_KEY or not SUPABASE_URL:
        return None
    redirect = f"{SITE_URL}/upload.html" if SITE_URL else ""
    body = json.dumps({
        "email": email,
        "data": {"full_name": name},
        **({"options": {"redirect_to": redirect}} if redirect else {}),
    }).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/auth/v1/admin/invite",
        data=body,
        method="POST",
    )
    req.add_header("apikey", SUPABASE_SERVICE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_SERVICE_KEY}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("id")
    except Exception:
        return None


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
        session  = event["data"]["object"]
        meta     = session.get("metadata") or {}
        user_id  = meta.get("user_id")
        details  = session.get("customer_details") or {}
        email    = details.get("email") or session.get("customer_email", "")
        name     = details.get("name") or meta.get("name", "")
        base     = SITE_URL or ""
        dashboard = base + "/upload.html"

        if user_id:
            _activate_pro(user_id)
        elif email:
            uid = _invite_user(email, name) or _find_user_by_email(email)
            if uid:
                _activate_pro(uid)

        if email:
            greeting = f"Welcome, {name}!" if name else "Welcome to Fileo Pro!"
            _send_email(
                email,
                "You're in — Fileo Pro is ready",
                f"""<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:480px;margin:0 auto;padding:40px 24px;background:#F5F0E8;color:#1C1917">
  <div style="margin-bottom:20px">
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="14" cy="14" r="14" fill="#1C1917"/>
      <polygon points="14,8 21,20 7,20" fill="#F5F0E8"/>
    </svg>
  </div>
  <h1 style="font-size:24px;font-weight:700;margin:0 0 8px;letter-spacing:-0.02em">{greeting}</h1>
  <p style="color:rgba(28,25,23,0.55);margin:0 0 8px;line-height:1.65">Payment confirmed. Your Pro account is active.</p>
  <ul style="color:rgba(28,25,23,0.55);margin:0 0 28px;padding-left:20px;line-height:2">
    <li>10 GB max file size</li>
    <li>3 GB weekly storage</li>
    <li>7-day &amp; 30-day expiry options</li>
    <li>Password protection &amp; download limits</li>
    <li>Cloud storage workspace</li>
  </ul>
  <a href="{dashboard}" style="display:inline-block;background:#1C1917;color:#F5F0E8;text-decoration:none;padding:14px 28px;border-radius:999px;font-weight:600;font-size:15px">Go to dashboard →</a>
  <p style="color:rgba(28,25,23,0.35);font-size:12px;margin-top:28px;line-height:1.6">Sign in with <strong>{email}</strong>. If you don't have an account yet, check your inbox for a setup email — or create one at the dashboard link above using this address.</p>
</div>""",
            )

    return jsonify({"received": True})


@app.route("/request-access", methods=["POST"])
@limiter.limit("5 per hour")
def request_access():
    """Form submission: create a Stripe checkout session and email the payment link."""
    body  = request.get_json(silent=True) or {}
    name  = str(body.get("name", "")).strip()[:120]
    email = str(body.get("email", "")).strip()[:254]

    if not email or "@" not in email:
        return jsonify({"error": "A valid email is required"}), 400
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        return jsonify({"error": "Payments not configured on this server"}), 503
    if not RESEND_API_KEY:
        return jsonify({"error": "Email not configured on this server"}), 503

    base = SITE_URL or request.host_url.rstrip("/")
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            customer_email=email,
            allow_promotion_codes=True,
            success_url=base + "/?upgrade=success&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base + "/#get-access",
            metadata={"name": name, "email": email},
        )
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 500

    greeting = f"Hi {name}," if name else "Hi,"
    _send_email(
        email,
        "Your Fileo Pro payment link",
        f"""<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:480px;margin:0 auto;padding:40px 24px;background:#F5F0E8;color:#1C1917">
  <div style="margin-bottom:20px">
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="14" cy="14" r="14" fill="#1C1917"/>
      <polygon points="14,8 21,20 7,20" fill="#F5F0E8"/>
    </svg>
  </div>
  <h1 style="font-size:24px;font-weight:700;margin:0 0 8px;letter-spacing:-0.02em">{greeting}</h1>
  <p style="color:rgba(28,25,23,0.55);margin:0 0 24px;line-height:1.65">Here's your Fileo Pro payment link. Click the button to complete your purchase — $10/month, cancel anytime.</p>
  <a href="{session.url}" style="display:inline-block;background:#1C1917;color:#F5F0E8;text-decoration:none;padding:14px 28px;border-radius:999px;font-weight:600;font-size:15px">Complete payment →</a>
  <p style="color:rgba(28,25,23,0.35);font-size:12px;margin-top:28px;line-height:1.6">Once payment is confirmed, you'll receive a second email with your dashboard link. This payment link expires in 24 hours.</p>
</div>""",
    )

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Dev entry point — Gunicorn is used in production (see gunicorn.conf.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=int(os.environ.get("PORT", 5001)))
