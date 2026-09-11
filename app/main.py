from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, jobs
from .auth import add_session_middleware, is_authenticated, login_user, logout_user, require_login
from .config import DATA_DIR, get_settings
from .services import google_auth

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Postmaster Dashboard", docs_url=None, redoc_url=None)
add_session_middleware(app)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _load_runtime_env() -> None:
    """Load optional secrets written by the Settings UI."""
    import os

    runtime = DATA_DIR / "secrets" / "runtime.env"
    if not runtime.exists():
        return
    for line in runtime.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()
    get_settings.cache_clear()


@app.on_event("startup")
async def startup() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "secrets").mkdir(parents=True, exist_ok=True)
    _load_runtime_env()
    await db.init_db()
    # Fresh installs should start empty; wipe any previously seeded demo domains once.
    await db.clear_demo_seed_once()


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    if exc.status_code == 401:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "authed": is_authenticated(request),
            "status_code": exc.status_code,
            "detail": exc.detail,
        },
        status_code=exc.status_code,
    )


def _ctx(request: Request, **extra):
    settings = get_settings()
    return {
        "request": request,
        "authed": is_authenticated(request),
        "admin_name": settings.admin_name,
        "brand_name": "FinCoverTech",
        **extra,
    }


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", _ctx(request, error=None))


@app.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    if login_user(request, password):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        _ctx(request, error="Incorrect password"),
        status_code=401,
    )


@app.post("/logout")
async def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def dashboard(request: Request):
    stats = await db.domain_stats()
    recent_jobs = await db.list_jobs(8)
    creds = await jobs.credential_status()
    running = await db.get_running_job()
    return templates.TemplateResponse(
        "dashboard.html",
        _ctx(request, stats=stats, jobs=recent_jobs, creds=creds, running=running),
    )


@app.get("/domains", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def domains_page(request: Request, q: str | None = None, status: str | None = None):
    domains = await db.list_domains(q=q, status=status)
    stats = await db.domain_stats()
    return templates.TemplateResponse(
        "domains.html",
        _ctx(request, domains=domains, stats=stats, q=q or "", status=status or ""),
    )


@app.post("/domains/add", dependencies=[Depends(require_login)])
async def domains_add(request: Request, domains_text: str = Form(...)):
    lines = [ln.strip() for ln in domains_text.replace(",", "\n").splitlines() if ln.strip()]
    added = await db.upsert_domains(lines)
    return RedirectResponse(f"/domains?flash=added:{added}", status_code=303)


@app.post("/domains/{domain_id}/delete", dependencies=[Depends(require_login)])
async def domains_delete(domain_id: int):
    await db.delete_domain(domain_id)
    return RedirectResponse("/domains", status_code=303)


@app.get("/jobs", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def jobs_page(request: Request):
    all_jobs = await db.list_jobs(50)
    running = await db.get_running_job()
    return templates.TemplateResponse(
        "jobs.html",
        _ctx(request, jobs=all_jobs, running=running),
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def job_detail(request: Request, job_id: int):
    job = await db.get_job(job_id)
    if not job:
        return templates.TemplateResponse(
            "error.html",
            _ctx(request, status_code=404, detail="Job not found"),
            status_code=404,
        )
    return templates.TemplateResponse("job_detail.html", _ctx(request, job=job))


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_login)])
async def api_job(job_id: int):
    job = await db.get_job(job_id)
    if not job:
        return JSONResponse({"error": "not found"}, status_code=404)
    return job


@app.post("/jobs/run/{job_type}", dependencies=[Depends(require_login)])
async def run_job(job_type: str):
    mapping = {
        "fetch_tokens": (jobs.run_fetch_tokens, "Fetch TXT tokens"),
        "cloudflare_txt": (jobs.run_cloudflare_txt, "Add Cloudflare TXT"),
        "verify_sites": (jobs.run_verify_sites, "Verify with Google"),
        "sync_postmaster": (jobs.run_sync_postmaster, "Sync Postmaster status"),
        "register_postmaster": (jobs.run_register_postmaster, "Register in Postmaster"),
    }
    if job_type not in mapping:
        return RedirectResponse("/jobs?error=unknown", status_code=303)
    runner, _label = mapping[job_type]
    try:
        domains = await db.list_domains()
        total = len(domains)
        if job_type == "cloudflare_txt":
            total = sum(
                1
                for d in domains
                if d.get("txt_record") and not str(d["txt_record"]).startswith("ERROR")
            )
        if job_type == "register_postmaster":
            total = sum(1 for d in domains if not d["postmaster_registered"])
        job_id = await jobs.start_job(job_type, runner, total=total)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/jobs?error={str(exc)[:120]}", status_code=303)


@app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def settings_page(request: Request):
    creds = await jobs.credential_status()
    settings = get_settings()
    return templates.TemplateResponse(
        "settings.html",
        _ctx(
            request,
            creds=creds,
            has_password=bool(settings.dashboard_password),
            message=request.query_params.get("msg"),
            error=request.query_params.get("error"),
        ),
    )


def _upsert_runtime_env(key: str, value: str) -> None:
    import os

    secrets_env = DATA_DIR / "secrets" / "runtime.env"
    secrets_env.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if secrets_env.exists():
        lines = [
            ln
            for ln in secrets_env.read_text(encoding="utf-8").splitlines()
            if not ln.startswith(f"{key}=")
        ]
    lines.append(f"{key}={value}")
    secrets_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value
    get_settings.cache_clear()


@app.post("/settings/password", dependencies=[Depends(require_login)])
async def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    settings = get_settings()
    if current_password != settings.dashboard_password:
        return RedirectResponse("/settings?error=Current+password+is+incorrect", status_code=303)
    if len(new_password) < 8:
        return RedirectResponse("/settings?error=New+password+must+be+at+least+8+characters", status_code=303)
    if new_password != confirm_password:
        return RedirectResponse("/settings?error=New+passwords+do+not+match", status_code=303)
    _upsert_runtime_env("DASHBOARD_PASSWORD", new_password)
    return RedirectResponse(
        "/settings?msg=Password+updated.+Also+set+DASHBOARD_PASSWORD+in+Render+Environment.",
        status_code=303,
    )


@app.post("/settings/admin-name", dependencies=[Depends(require_login)])
async def change_admin_name(admin_name: str = Form(...)):
    name = " ".join(admin_name.strip().split())
    if not name or len(name) > 60:
        return RedirectResponse("/settings?error=Admin+name+must+be+1-60+characters", status_code=303)
    _upsert_runtime_env("ADMIN_NAME", name)
    return RedirectResponse("/settings?msg=Admin+name+updated", status_code=303)


@app.post("/settings/cloudflare", dependencies=[Depends(require_login)])
async def save_cloudflare(token: str = Form(...)):
    _upsert_runtime_env("CLOUDFLARE_API_TOKEN", token.strip())
    return RedirectResponse("/settings?msg=Cloudflare+token+saved", status_code=303)


@app.post("/settings/credentials", dependencies=[Depends(require_login)])
async def upload_credentials(file: UploadFile = File(...)):
    try:
        content = await file.read()
        google_auth.save_uploaded_credentials(content)
        return RedirectResponse("/settings?msg=Google+credentials+uploaded", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/settings?error={str(exc)[:120]}", status_code=303)


@app.get("/oauth/start/{kind}", dependencies=[Depends(require_login)])
async def oauth_start(request: Request, kind: str):
    if kind not in ("site", "postmaster"):
        return RedirectResponse("/settings?error=Invalid+OAuth+kind", status_code=303)
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_kind"] = kind
    try:
        url = google_auth.authorization_url(kind, state)
        return RedirectResponse(url, status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/settings?error={str(exc)[:160]}", status_code=303)


@app.get("/oauth/callback")
async def oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    if error:
        return RedirectResponse(f"/settings?error={error}", status_code=303)
    if not code or state != request.session.get("oauth_state"):
        return RedirectResponse("/settings?error=OAuth+state+mismatch", status_code=303)
    kind = request.session.get("oauth_kind", "site")
    try:
        google_auth.exchange_code(kind, code)
        request.session.pop("oauth_state", None)
        request.session.pop("oauth_kind", None)
        return RedirectResponse(f"/settings?msg=Google+{kind}+authorized", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/settings?error={str(exc)[:160]}", status_code=303)


@app.get("/healthz")
async def healthz():
    return {"ok": True}
