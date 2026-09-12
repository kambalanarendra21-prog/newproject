# Postmaster Automation Dashboard

Private admin console for FinCoverTech to manage Google Postmaster Tools domain registration and DNS verification across many domains.

Recommended public URL: `https://postmaster.fincovertech.com` (subdomain — keeps the main marketing site untouched).

## What it does

- Password-protected dashboard
- Manage domain list (seeded with your existing 119 domains)
- Run jobs:
  1. Fetch Google DNS TXT verification tokens
  2. Add TXT records in Cloudflare
  3. Verify ownership with Google Site Verification
  4. Sync which domains exist in Postmaster
  5. Register missing domains in Postmaster
- Live job logs
- Settings UI for Cloudflare token + Google OAuth (stored under `data/secrets/`, not in git)

## Quick start (local)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set DASHBOARD_PASSWORD, SECRET_KEY, PUBLIC_BASE_URL=http://localhost:8080
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open http://localhost:8080 and sign in.

## Docker

```bash
cp .env.example .env
# set DASHBOARD_PASSWORD, SECRET_KEY, PUBLIC_BASE_URL
docker compose up -d --build
```

## Deploy on postmaster.fincovertech.com

Your apex domain already uses Cloudflare + S3. This app needs a **server** (VPS, Railway, Render, Fly.io, ECS, etc.), not static S3.

### 1. Deploy the container

Run the Docker image on any host with HTTPS in front (Caddy/Nginx/Traefik or a PaaS).

Example env:

```env
DASHBOARD_PASSWORD=use-a-long-random-password
SECRET_KEY=generate-with-python-secrets
PUBLIC_BASE_URL=https://postmaster.fincovertech.com
CLOUDFLARE_API_TOKEN=
```

Persist `/data` as a volume (`DATA_DIR=/data`) so the SQLite DB, user accounts, API keys, and OAuth tokens survive restarts. On Render, attach a 1 GB disk mounted at `/data`.

### 2. Cloudflare DNS

In Cloudflare for `fincovertech.com`:

| Type | Name | Value |
|------|------|-------|
| A / CNAME | `postmaster` | your server IP or PaaS hostname |
| Proxied | yes (orange cloud) | optional but recommended |

### 3. Google Cloud OAuth

1. Google Cloud Console → APIs & Services → enable **Site Verification API** and **Gmail Postmaster Tools API**
2. Create an OAuth client of type **Web application**
3. Authorized redirect URI:
   `https://postmaster.fincovertech.com/oauth/callback`
4. Download JSON → upload it in Dashboard → Settings
5. Click **Authorize Site Verification** and **Authorize Postmaster**

### 4. Cloudflare API token

Create a token with **Zone → DNS → Edit** for the zones you manage, then paste it in Settings.

## Security notes

- Do **not** commit `credentials.json`, OAuth tokens, Cloudflare tokens, or browser profiles
- Rotate any tokens that were previously hardcoded in local scripts
- Keep the dashboard password strong; this UI can change DNS and register domains
- Prefer IP allowlisting / Cloudflare Access in front of the subdomain for extra lockdown

## Project layout

```
app/           FastAPI app + UI
seed/          Initial domains.txt
data/          SQLite DB + secrets (gitignored)
Dockerfile
docker-compose.yml
```
