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
| `PUBLIC_BASE_URL` | leave as `https://temp` for now — you will update after first deploy |

8. Click **Create Web Service**  
9. Wait until the status says **Live**  
10. Click the URL Render gives you (looks like `https://postmaster-dashboard-xxxx.onrender.com`)  
11. You should see the FinCoverTech login page  
12. Sign in with the `DASHBOARD_PASSWORD` you set

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
3. Upload your Google `credentials.json`  
4. Click **Authorize Site Verification** and **Authorize Postmaster**  
5. Then use **Overview** buttons 1 → 5 to run jobs

---

## Important

- Ignore any screen that asks for a Docker image name like `kennethreitz/httpbin`
- Choose **GitHub / Git repository** deploy, not “Docker image from registry”
- If you get stuck, send a screenshot of the page you are on
