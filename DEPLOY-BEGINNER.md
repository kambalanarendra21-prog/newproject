# Deploy for beginners (click-by-click)

You do **not** need to understand Docker.  
Do **not** type `kennethreitz/httpbin` anywhere.

Use this path: **Render.com** (free to start) + your GitHub repo.

---

## Part 1 — Put the website online (about 10 minutes)

1. Open: https://render.com  
2. Click **Get Started** → sign in with **GitHub**  
3. Allow Render to access your GitHub account  
4. Click **New +** → **Web Service**  
5. Find repo: `kambalanarendra21-prog/newproject` → **Connect**  
6. Settings:
   - **Name:** `postmaster-dashboard`
   - **Branch:** `cursor/postmaster-dashboard-4ff7`  
     (or `main` after you merge the pull request)
   - **Runtime:** Docker (Render will detect the Dockerfile automatically)
7. Click **Advanced** → **Add Environment Variable** and add these 3:

| Key | Value |
|-----|--------|
| `DASHBOARD_PASSWORD` | invent a strong password (you will use this to log in) |
| `SECRET_KEY` | paste any long random text, e.g. `fincover-secret-93847-change-me` |
| `PUBLIC_BASE_URL` | your live URL, e.g. `https://newproject-p8x7.onrender.com` (not localhost) |

8. **Required so accounts and API keys survive restarts** — click **Advanced** → **Add Disk**:
   - Name: `postmaster-data`
   - Mount path: `/data`
   - Size: `1 GB` is enough
   Then add env var `DATA_DIR` = `/data`
9. Click **Create Web Service**  
10. Wait until the status says **Live**  
11. Click the URL Render gives you (looks like `https://postmaster-dashboard-xxxx.onrender.com`)  
12. You should see the FinCoverTech login page  
13. Sign in with username `admin` and the `DASHBOARD_PASSWORD` you set

Without the disk, Render gives the app a fresh empty folder on every deploy. That looks like “all user accounts were deleted.” The disk keeps `postmaster.db` (users, domains, API keys, Google files).

If the service is **already live** without a disk: Render → service → **Settings** → **Disks** → add `/data`, set `DATA_DIR=/data`, then redeploy. Create sub accounts and paste API keys again once after that; they will then stay.

---

## Part 2 — Connect your real domain (postmaster.fincovertech.com)

1. In Render → your service → **Settings** → **Custom Domains** → add:  
   `postmaster.fincovertech.com`
2. Render will show a DNS target (a CNAME value)
3. Open Cloudflare → domain `fincovertech.com` → **DNS** → **Add record**:
   - Type: **CNAME**
   - Name: `postmaster`
   - Target: the value Render showed you
   - Proxy: ON (orange cloud) is fine
4. Back in Render, update env var:
   - `PUBLIC_BASE_URL` = `https://postmaster.fincovertech.com`
5. Redeploy (Render has a **Manual Deploy** button)
6. Open https://postmaster.fincovertech.com and log in

---

## Part 3 — Connect Google + Cloudflare (inside the website)

After you can log in:

1. Open **Settings** in the dashboard  
2. Paste your **Cloudflare API token** → Save  
3. In Google Cloud Console create an OAuth client of type **Web application** (not Desktop)
4. Add Authorized redirect URI exactly as Settings shows, usually:  
   `https://newproject-p8x7.onrender.com/oauth/callback`
5. Download that client JSON and upload it in Settings  
6. Click **Authorize Site Verification** and **Authorize Postmaster**  
7. Then use **Overview** buttons 1 → 5 to run jobs

If Google says `redirect_uri_mismatch`, the callback URL in Settings is not listed on that Web client yet. Add it, wait a minute, try Authorize again.

---

## Important

- Ignore any screen that asks for a Docker image name like `kennethreitz/httpbin`
- Choose **GitHub / Git repository** deploy, not “Docker image from registry”
- If you get stuck, send a screenshot of the page you are on
