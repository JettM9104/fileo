# Fileo — Complete Repository Reference

## What It Is

Fileo is a temporary file-sharing web app hosted at **fileo.ca**. Users drop any file, get a short link, and share it. Links expire automatically (1 hour or 24 hours free; 7 or 30 days for Pro). The Pro plan ($10/month, billed via Stripe) unlocks larger files, longer expiry, password protection, download limits, access control, and a version-controlled cloud workspace.

---

## Architecture

```
fileo.ca (GitHub Pages)         api.fileo.ca (VPS)
┌──────────────────────┐        ┌─────────────────────────┐
│ index.html           │ ──────▶│ Caddy reverse proxy      │
│ upload.html          │        │ → Gunicorn (port 5001)   │
│ cloud.html           │        │   → server.py (Flask)    │
│ config.js            │        └─────────────────────────┘
└──────────────────────┘                  │
         │                               │
         ▼                               ▼
  Supabase (auth + DB)         Cloudflare R2 (file storage)
         │                               ▲
         └───────────────────────────────┘
                  presigned PUT/GET URLs
```

The frontend is **pure static HTML + vanilla JS** (no build step). The Flask backend handles anything the browser can't do safely: generating presigned R2 URLs, verifying JWTs, processing Stripe webhooks, activating Pro accounts, and file deletion.

---

## File Structure

| File | Purpose |
|---|---|
| `index.html` | Landing page — hero, how-it-works, features mockup demo, pricing section, download overlay, ToS/Privacy modals |
| `upload.html` | Main upload UI — drag-and-drop, expiry picker, advanced options (Pro), My Files tab, progress/success states |
| `cloud.html` | Pro-only Cloud workspace — versioned folder uploads, conflict detection, ZIP download, shared notes, member management |
| `server.py` | Flask API — presigned URLs, file deletion, Stripe checkout + webhook, Pro activation |
| `config.js` | Runtime config injected into every page — Supabase URL/anon key, `apiBaseUrl` |
| `gunicorn.conf.py` | Gunicorn settings: `127.0.0.1:5001`, 2 workers × 4 threads, 120s timeout |
| `Caddyfile` | Caddy config: reverse-proxies `api.fileo.ca` → `127.0.0.1:5001` |
| `myapp.service` | systemd unit file for `fileo-api` — runs Gunicorn as `www-data`, loads `/var/www/fileo/.env` |
| `requirements.txt` | Python deps: flask, flask-cors, flask-talisman, flask-limiter, gunicorn, python-dotenv, stripe, boto3 |
| `GITHUB_PAGES_SERVER_SETUP.md` | Step-by-step deployment guide for both GitHub Pages and the API VPS |
| `to_do.md` | Known issue: `access_control` column missing from DB causes upload errors for Pro users |
| `expenses.md` | $18.07 GoDaddy (fileo.ca domain), $25.00 Supabase SQL servers |

---

## External Services

### Supabase
- **Auth**: Email/password and Google OAuth. JWT tokens carry `app_metadata.is_pro` to gate Pro features client-side.
- **Database**: Postgres tables (queried via Supabase JS client and REST API):
  - `files` — uploaded file records (`id`, `filename`, `size`, `storage_path`, `expires_at`, `downloads`, `user_id`, `password_hash`, `download_limit`, `access_control`, `allowed_emails`, `is_pro`) — *Note: Pro columns are not yet in the schema; a fallback insert skips them*
  - `workspaces` — Cloud workspace records (`id`, `name`, `owner_id`, `created_at`)
  - `workspace_members` — Collaborator invites (`workspace_id`, `email`, `role`, `added_at`)
  - `workspace_folders` — Named versioned entries inside a workspace (`id`, `workspace_id`, `name`, `created_by`, `created_by_email`)
  - `workspace_folder_snapshots` — A version of a folder (`id`, `folder_id`, `version_number`, `uploaded_by`, `uploaded_by_email`, `file_count`, `total_size`, `uploaded_at`)
  - `workspace_folder_files` — Individual files within a snapshot (`snapshot_id`, `folder_id`, `filename`, `storage_path`, `size`)
  - `workspace_notes` — Shared notes per workspace (`workspace_id`, `content`, `updated_by`, `updated_by_email`, `updated_at`)
- **Admin API**: Server calls `PUT /auth/v1/admin/users/{user_id}` with `SUPABASE_SERVICE_ROLE_KEY` to set `app_metadata.is_pro = true` on Pro activation.

### Cloudflare R2
- Stores all uploaded files. The Flask server generates presigned PUT URLs (15-minute expiry) for direct browser-to-R2 uploads, and presigned GET URLs (1-hour expiry) for downloads.
- Path convention: `{user_id}/{file_id}.{ext}` for ephemeral uploads; `ws/{workspace_id}/folders/{folder_id}/{snapshot_id}/{relative_path}` for Cloud workspace files.
- Cloud workspace files are fetched via Supabase Storage public URLs (bucket named `uploads`).

### Stripe
- Subscription checkout at `$10/month` (price ID from env).
- Checkout session created server-side with `metadata.user_id` so the webhook can identify the buyer.
- Success URL: `/?upgrade=success&session_id={CHECKOUT_SESSION_ID}`
- Cancel URL: `/?upgrade=cancelled`
- Webhook event handled: `checkout.session.completed`

---

## Environment Variables (`.env` on API server)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session secret (required, no default) |
| `SUPABASE_URL` | e.g. `https://xxx.supabase.co` |
| `SUPABASE_ANON_KEY` | Public anon key (also in `config.js`) |
| `SUPABASE_SERVICE_ROLE_KEY` | Admin key for Pro activation — server only, never in frontend |
| `R2_ACCOUNT_ID` | Cloudflare account ID |
| `R2_ACCESS_KEY_ID` | R2 API key |
| `R2_SECRET_ACCESS_KEY` | R2 API secret |
| `R2_BUCKET_NAME` | R2 bucket name |
| `STRIPE_SECRET_KEY` | `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` |
| `STRIPE_PRICE_ID` | `price_...` |
| `SITE_URL` | `https://fileo.ca` — used for Stripe redirect URLs |
| `API_BASE_URL` | `https://api.fileo.ca` — also injected into CSP headers |
| `BEHIND_PROXY` | Set to `1` when behind Caddy/Nginx so rate limiting uses real IPs |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins, e.g. `https://fileo.ca,https://www.fileo.ca` |
| `FORCE_HTTPS` | `0` — SSL terminated by Caddy, not Flask |
| `RATELIMIT_STORAGE_URL` | Defaults to `memory://`; set to `redis://...` in production |

---

## Flask API Endpoints (`server.py`)

### `GET /config.js`
Returns a JS snippet setting `window.FILEO_CONFIG` with Supabase URL, anon key, and `apiBaseUrl`. `Cache-Control: no-store`.

### `POST /upload-url`
- Rate limit: 30/min
- Auth: Bearer (Supabase JWT verified via `/auth/v1/user`)
- Body: `{ key, content_type }`
- Validates that `key` starts with `{user_id}/`
- Returns a presigned R2 PUT URL (900s expiry)

### `GET /download-url/<file_id>`
- Rate limit: 120/min
- No auth required
- Fetches file record from Supabase (via service key), returns presigned R2 GET URL (3600s expiry)

### `DELETE /file/<file_id>`
- Rate limit: 30/min
- Auth: Bearer — caller must own the file
- Deletes from R2, then deletes DB record

### `POST /r2-cleanup`
- Rate limit: 10/min
- Auth: Bearer — caller must own the key (starts with `{user_id}/`)
- Deletes an R2 object (rollback for failed DB inserts)

### `POST /create-checkout-session`
- Rate limit: 10/min
- Auth: Bearer
- Creates a Stripe Checkout `subscription` session with `metadata.user_id`
- Returns `{ url }` — frontend redirects to Stripe

### `POST /activate-pro-from-session`
- Rate limit: 5/min
- Auth: Bearer
- Body: `{ session_id }` (Stripe checkout session ID from redirect URL)
- Retrieves Stripe session, checks `metadata.user_id === authenticated_user_id`, checks `payment_status === "paid"`
- Calls `_activate_pro(user_id)` — fallback for missed webhooks

### `POST /stripe-webhook` (also `/stripe-webhook/`)
- Rate limit: exempt
- Signature verified with `STRIPE_WEBHOOK_SECRET`
- Handles `checkout.session.completed`: extracts `metadata.user_id`, calls `_activate_pro(user_id)`

### `GET /` and `GET /<path>`
- Serves static files from `WEB_ROOT`; falls back to `index.html` for client-side routing

---

## Security & Middleware

- **Flask-Talisman**: Sets Content Security Policy — `script-src` allows `cdn.tailwindcss.com` and `cdn.jsdelivr.net`; `connect-src` includes Supabase and R2 origins, plus `API_BASE_URL` when set.
- **Flask-Limiter**: In-memory rate limiting (swap for Redis via `RATELIMIT_STORAGE_URL`). Default: 200/min, 20/s. Individual endpoint limits as above.
- **Flask-CORS**: Only enabled when `ALLOWED_ORIGINS` is set. Never defaults to `*`.
- **ProxyFix**: Applied when `BEHIND_PROXY=1` — trusts one upstream `X-Forwarded-For` header.
- **No HTTPS forcing in Flask**: Caddy handles TLS termination; `FORCE_HTTPS=0`.

---

## Pro Activation Flow (Full Sequence)

1. Signed-in user clicks "Subscribe — $10/mo" → `openUpgradeModal()` → `startCheckout()`
2. Frontend calls `POST /create-checkout-session` with Bearer token
3. Server creates Stripe session with `metadata.user_id`, returns `url`
4. Browser redirects to Stripe Checkout
5. User pays; Stripe redirects to `/?upgrade=success&session_id=cs_...`
6. Client captures `session_id` before clearing URL with `history.replaceState`
7. After 2 seconds, `_pollPro()` fires:
   - On first attempt: calls `POST /activate-pro-from-session` with the `session_id` (webhook fallback)
   - Then calls `_sb.auth.refreshSession()` to get updated JWT
   - If `app_metadata.is_pro === true`: shows "You're now Pro!" toast; `onAuthStateChange` fires and applies Pro UI
   - Else: retries every 2 seconds, up to 15 attempts (30 seconds total)
   - Timeout message: "Pro activation is taking longer than expected — please refresh in a minute."
8. In parallel, Stripe fires `checkout.session.completed` webhook → `_activate_pro(user_id)` sets `app_metadata.is_pro=true` in Supabase admin API

The fallback endpoint ensures activation even if the webhook is dropped or delayed.

**Bug fixed (2026-05-03)**: The original `_triggerActivation` used `getSession()` (returns cached/possibly-expired JWT), never checked the fetch response status, and only attempted activation once. All three issues silently blocked Pro activation after payment. Fixed: use `refreshSession()` for a guaranteed-fresh token, check HTTP status and log errors, and retry activation on every poll iteration until it succeeds (`_activationOk` flag). Also explicitly set `isPro = true` and call `applyProPricingCard()` in the success branch rather than relying solely on `onAuthStateChange`.

---

## Free vs Pro Limits

| Feature | Free | Pro |
|---|---|---|
| Max file size | 500 MB | 10 GB |
| Active links | 3 | 10 |
| Total storage | 500 MB | 3 GB/week |
| Expiry options | 1h, 24h | 1h, 24h, 7d, 30d |
| Password protection | No | Yes |
| Download limits | No | Yes |
| Access control | No | Yes (anyone / signed-in / specific emails) |
| Malware scanning UI | No | Yes (scan animation + "no threats" badge) |
| Cloud workspace | No | Yes |

---

## Upload Flow (`upload.html`)

1. User drops file or clicks browse; zip created on-the-fly if a folder is dropped (JSZip)
2. Free users checked against 3-link and 500 MB quota before upload
3. `POST /upload-url` fetched → presigned R2 PUT URL returned
4. XHR PUT to R2 with real-time progress bar (speed, "Slow connection" badge)
5. On success, DB record inserted into `files` table via Supabase JS client
6. If insert fails due to missing Pro columns (e.g. `access_control`): retries with basic columns only; shows toast for Pro users noting the schema issue
7. If DB insert fails entirely: calls `POST /r2-cleanup` to delete the uploaded R2 object
8. Success state shows shareable link (`{base}/index.html#d/{file_id}`)

---

## Download Flow (`index.html`)

Hash routing: `index.html#d/{file_id}` opens the download overlay.

1. Fetches file record from Supabase (`files` table) by `id`
2. Checks expiry — shows "Link expired" state if past
3. Checks `access_control`:
   - `anyone`: proceeds
   - `signed_in`: requires auth — shows sign-in prompt, re-checks after login
   - `specific`: checks `allowed_emails` — not yet enforced client-side (noted in code)
4. Checks `download_limit` vs `downloads` count — shows "Download limit reached" if hit
5. If `password_hash` set: shows password prompt; verifies via PBKDF2 (100k iterations, SHA-256) client-side
6. If `is_pro` file: shows "malware scan" animation for ~1.8 seconds, then "no threats" badge
7. Calls `GET /download-url/{file_id}` → presigned R2 GET URL → sets as `<a>` href
8. Increments `downloads` count in Supabase

---

## Cloud Workspace (`cloud.html`) — Pro Only

A simple shared file storage with notes and member management.

**States**: loading → sign-in required → upgrade prompt (not Pro) → workspace

**On load (Pro users)**:
- Looks for owned workspace in `workspaces` table
- Falls back to workspace where user is a member (`workspace_members`)
- Creates new workspace if none found

**Files tab** (default):
- Flat list of all uploaded files, sorted newest-first
- File type icons based on extension (image, video, audio, doc, zip, generic)
- Per-file actions: Download (direct via Supabase Storage public URL), Delete
- Drop zone with two upload buttons: "Upload files" (any file, multiple) and "Photos" (`accept="image/*,video/*" multiple` — allows multi-select from camera roll on iOS)
- Upload progress bar with per-file label and count

**Upload flow**:
- Each file is stored as a `workspace_folders` entry (name = filename) + `workspace_folder_snapshots` (version 1+) + `workspace_folder_files` record
- Re-uploading the same filename increments the version; only latest version shown in list
- Storage path: `ws/{workspace_id}/files/{folder_id}/{snapshot_id}/{sanitized_filename}`
- Uses existing DB tables — no new schema needed

**Delete flow**: Deletes all snapshots + file records + storage objects for that folder entry, then deletes the folder record.

**Notes tab**: Shared markdown-free textarea. Auto-saves 3.5 seconds after last keystroke. Upserts `workspace_notes` record.

**Members tab**: Invite by email (inserted into `workspace_members`). Owner sees "Remove" buttons. Avatar row in header shows up to 4 members + overflow count.

---

## Auth (`index.html`, `upload.html`, `cloud.html`)

- Supabase JS SDK v2 (`onAuthStateChange`) used everywhere
- Email/password sign-in and sign-up; Google OAuth (`signInWithOAuth`)
- Rate limiting client-side: 5 failed attempts → 60-second lockout
- `isPro` read from `session.user.app_metadata?.is_pro === true`
- Pro UI applied in `applyProUI()` / `applyProPricingCard()`:
  - Shows PRO badge in nav
  - Unlocks 7d/30d expiry buttons
  - Shows "Advanced options" panel toggle
  - Sets file size limit display to 10 GB
  - Sets Pro plan text in account menu

---

## Password Hashing

Client-side PBKDF2 (Web Crypto API):
- 100,000 iterations, SHA-256, 256-bit key
- Format stored: `pbkdf2:{salt}:{hex_hash}`
- Salt is a random UUID generated at upload time
- Legacy SHA-256 (no PBKDF2) also supported in download verification for old uploads

---

## Animations & UI Details

- Color palette: `#F5F0E8` (warm off-white bg), `#1C1917` (near-black), `#8B6F47` (warm brown accent), `#EAE4D9` (subtle beige)
- CSS animations: `fadeUp`, `slideIn`, `modalIn`, `spin`, `slideR`, `scanPulse`
- Nav pill with backdrop blur; transitions to floating pill on scroll (desktop)
- Mobile nav collapses to hamburger with dropdown
- Mockup demo on landing page: animated cursor moves to "Upload file" button, progress bar fills, success screen fades in — triggered by IntersectionObserver at 55% visibility

---

## Deployment

**Frontend** (GitHub Pages):
- Main branch, repo root
- CNAME: `fileo.ca`
- `config.js` sets `apiBaseUrl: "https://api.fileo.ca"`

**API server** (Ubuntu VPS):
- App directory: `/var/www/fileo`
- Python venv at `/var/www/fileo/venv`
- Env file: `/var/www/fileo/.env` (chmod 600, owned by www-data)
- systemd service: `fileo-api` (from `myapp.service`)
- Caddy reverse-proxies `api.fileo.ca` → `127.0.0.1:5001`
- Gunicorn: 2 workers, 4 threads, 120s timeout, logs to stdout/stderr

**Required external config**:
- Supabase: add `https://fileo.ca`, `https://fileo.ca/index.html`, `https://fileo.ca/upload.html` to allowed auth redirect URLs
- R2: bucket CORS allows `https://fileo.ca` for PUT, GET, HEAD with `Authorization` and `Content-Type` headers
- Stripe: webhook at `https://api.fileo.ca/stripe-webhook`, subscribed to `checkout.session.completed`

---

## Known Issues / To-Do (`to_do.md`)

- **Missing DB columns**: The `files` table is missing Pro-only columns (`access_control`, `password_hash`, `download_limit`, `allowed_emails`, `is_pro`). Uploading as Pro triggers error "Could not find the 'access_control' column." A client-side fallback retries with basic columns only so uploads still complete, but advanced settings are not saved.

---

## Costs

| Item | Cost |
|---|---|
| GoDaddy — fileo.ca domain | $18.07 |
| Supabase SQL servers | $25.00 |
