# GitHub Pages + Server Setup

GitHub Pages can host the frontend files in this repo, but it cannot run
`server.py`. Keep Pages for the static site and run the Flask API on a separate
server, for example `https://api.fileo.ca`.

## GitHub Pages

1. In GitHub, open the repo settings.
2. Go to Pages.
3. Set the source to the `main` branch and the repo root.
4. Keep `CNAME` set to `fileo.ca` if this site should use that domain.
5. Edit `config.js` before publishing:

```js
window.FILEO_CONFIG = {
  url: "https://YOUR-PROJECT.supabase.co",
  anon: "YOUR-SUPABASE-ANON-KEY",
  apiBaseUrl: "https://api.fileo.ca",
};
```

## API Server

Create a Linux server for the Flask API. These commands assume Ubuntu and the
app directory `/var/www/fileo`.

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx
sudo mkdir -p /var/www/fileo
sudo chown -R www-data:www-data /var/www/fileo
```

Copy the repo files to `/var/www/fileo`, then install Python dependencies:

```bash
cd /var/www/fileo
sudo -u www-data python3 -m venv venv
sudo -u www-data ./venv/bin/pip install -r requirements.txt
```

Create `/var/www/fileo/.env` from `.env.example` and set real values:

```bash
SECRET_KEY=generate-a-long-random-secret
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_ANON_KEY=YOUR-SUPABASE-ANON-KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR-SUPABASE-SERVICE-ROLE-KEY
R2_ACCOUNT_ID=YOUR-CLOUDFLARE-ACCOUNT-ID
R2_ACCESS_KEY_ID=YOUR-R2-ACCESS-KEY
R2_SECRET_ACCESS_KEY=YOUR-R2-SECRET
R2_BUCKET_NAME=YOUR-R2-BUCKET
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
SITE_URL=https://fileo.ca
API_BASE_URL=https://api.fileo.ca
BEHIND_PROXY=1
ALLOWED_ORIGINS=https://fileo.ca,https://www.fileo.ca
FORCE_HTTPS=0
```

Protect the env file:

```bash
sudo chown www-data:www-data /var/www/fileo/.env
sudo chmod 600 /var/www/fileo/.env
```

Install the systemd service:

```bash
sudo cp /var/www/fileo/myapp.service /etc/systemd/system/fileo-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now fileo-api
sudo systemctl status fileo-api
```

## Nginx for `api.fileo.ca`

Point a DNS `A` record for `api.fileo.ca` to the API server, then create this
Nginx site:

```nginx
server {
    server_name api.fileo.ca;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable TLS with Certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.fileo.ca
sudo nginx -t
sudo systemctl reload nginx
```

## Required External Settings

Supabase:

- Add `https://fileo.ca` to allowed auth redirect URLs.
- Add `https://fileo.ca/index.html` and `https://fileo.ca/upload.html` too if
  Google login should return users to those exact pages.
- Keep the service role key only on the API server. Never put it in `config.js`.

Cloudflare R2:

- Create the bucket named in `R2_BUCKET_NAME`.
- Create R2 API credentials with object read/write/delete access to that bucket.
- Add bucket CORS allowing `https://fileo.ca` for `PUT`, `GET`, and `HEAD`, with
  headers `Authorization` and `Content-Type`.

Stripe:

- Create the product price and set `STRIPE_PRICE_ID`.
- Add a webhook endpoint at `https://api.fileo.ca/stripe-webhook`.
- Subscribe the webhook to `checkout.session.completed`.
- Put the webhook signing secret in `STRIPE_WEBHOOK_SECRET`.

After these are set, GitHub Pages serves the site and the API server handles
upload signing, download signing, deletion, cleanup, and Stripe checkout.
