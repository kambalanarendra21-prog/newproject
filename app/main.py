from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, jobs
from .auth import (
    add_session_middleware,
    current_user,
    is_authenticated,
    is_super,
    login_user,
    logout_user,
    owner_scope,
    require_login,
    require_super,
)
from .config import DATA_DIR, get_settings, persist_public_base_url, public_base_from_request
from .services import google_auth

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Postmaster Dashboard", docs_url=None, redoc_url=None)
add_session_middleware(app)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def no_store_html(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type:
        response.headers["Cache-Control"] = "no-store"
    return response


def _load_runtime_env() -> None:
    import os

    runtime = DATA_DIR / "secrets" / "runtime.env"
    if not runtime.exists():
        return
    # Auth / session secrets always come from process env or .env — never from
    # leftover runtime.env lines (old password UI used to write them here).
    protected = {
        "DASHBOARD_PASSWORD",
        "SUPER_USERNAME",
        "SECRET_KEY",
        "HOST",
        "PORT",
    }
    for line in runtime.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in protected:
            continue
        os.environ[key] = value.strip()
    get_settings.cache_clear()


@app.on_event("startup")
async def startup() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "secrets").mkdir(parents=True, exist_ok=True)
    _load_runtime_env()
    await db.init_db()
    settings = get_settings()
    await db.ensure_super_user(
        settings.super_username,
        settings.dashboard_password,
        display_name=settings.admin_name or "Super Admin",
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    if exc.status_code == 401:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if exc.status_code == 403:
        return templates.TemplateResponse(
            "error.html",
            _ctx(request, status_code=403, detail="You do not have access to this page"),
            status_code=403,
        )
    return templates.TemplateResponse(
        "error.html",
        _ctx(request, status_code=exc.status_code, detail=exc.detail),
        status_code=exc.status_code,
    )


def _ctx(request: Request, **extra):
    user = current_user(request)
    return {
        "request": request,
        "authed": is_authenticated(request),
        "user": user,
        "is_super": bool(user and user.get("role") == "super"),
        "brand_name": "FinCoverTech",
        **extra,
    }


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", _ctx(request, error=None))


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if await login_user(request, username, password):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        _ctx(request, error="Incorrect username or password"),
        status_code=401,
    )


@app.post("/logout")
async def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def dashboard(request: Request):
    scope = owner_scope(request)
    stats = await db.domain_stats(owner_id=scope)
    recent_jobs = await db.list_jobs(8, user_id=None if is_super(request) else current_user(request)["id"])
    user = current_user(request)
    creds = await jobs.credential_status(user["id"], public_base_from_request(request))
    running = await db.get_running_job()
    return templates.TemplateResponse(
        "dashboard.html",
        _ctx(request, stats=stats, jobs=recent_jobs, creds=creds, running=running),
    )


@app.get("/domains", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def domains_page(request: Request, q: str | None = None, status: str | None = None):
    scope = owner_scope(request)
    domains = await db.list_domains(q=q, status=status, owner_id=scope)
    stats = await db.domain_stats(owner_id=scope)
    return templates.TemplateResponse(
        "domains.html",
        _ctx(request, domains=domains, stats=stats, q=q or "", status=status or ""),
    )


@app.post("/domains/add", dependencies=[Depends(require_login)])
async def domains_add(request: Request, domains_text: str = Form(...)):
    user = current_user(request)
    lines = [ln.strip() for ln in domains_text.replace(",", "\n").splitlines() if ln.strip()]
    # Each domain is owned by the account that adds it (super or sub).
    added = await db.upsert_domains(lines, owner_id=user["id"])
    return RedirectResponse(f"/domains?flash=added:{added}", status_code=303)


@app.post("/domains/{domain_id}/delete", dependencies=[Depends(require_login)])
async def domains_delete(request: Request, domain_id: int):
    scope = owner_scope(request)
    await db.delete_domain(domain_id, owner_id=scope)
    return RedirectResponse("/domains", status_code=303)


@app.get("/jobs", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def jobs_page(request: Request):
    user = current_user(request)
    all_jobs = await db.list_jobs(50, user_id=None if is_super(request) else user["id"])
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
    if not is_super(request) and job.get("user_id") != current_user(request)["id"]:
        return templates.TemplateResponse(
            "error.html",
            _ctx(request, status_code=403, detail="You do not have access to this job"),
            status_code=403,
        )
    return templates.TemplateResponse("job_detail.html", _ctx(request, job=job))


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_login)])
async def api_job(request: Request, job_id: int):
    job = await db.get_job(job_id)
    if not job:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not is_super(request) and job.get("user_id") != current_user(request)["id"]:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return job


@app.post("/jobs/run/{job_type}", dependencies=[Depends(require_login)])
async def run_job(request: Request, job_type: str):
    mapping = {
        "fetch_tokens": jobs.run_fetch_tokens,
        "cloudflare_txt": jobs.run_cloudflare_txt,
        "verify_sites": jobs.run_verify_sites,
        "sync_postmaster": jobs.run_sync_postmaster,
        "register_postmaster": jobs.run_register_postmaster,
    }
    if job_type not in mapping:
        return RedirectResponse("/jobs?error=unknown", status_code=303)
    runner = mapping[job_type]
    user = current_user(request)
    scope = owner_scope(request)
    try:
        domains = await db.list_domains(owner_id=scope)
        total = len(domains)
        if job_type == "cloudflare_txt":
            total = sum(
                1
                for d in domains
                if d.get("txt_record") and not str(d["txt_record"]).startswith("ERROR")
            )
        if job_type == "register_postmaster":
            total = sum(1 for d in domains if not d["postmaster_registered"])
        job_id = await jobs.start_job(job_type, runner, total=total, user_id=user["id"])
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/jobs?error={str(exc)[:120]}", status_code=303)


@app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def settings_page(request: Request):
    user = current_user(request)
    public_base = public_base_from_request(request)
    persist_public_base_url(public_base)
    creds = await jobs.credential_status(user["id"], public_base)
    return templates.TemplateResponse(
        "settings.html",
        _ctx(
            request,
            creds=creds,
            message=request.query_params.get("msg"),
            error=request.query_params.get("error"),
        ),
    )


@app.post("/settings/profile", dependencies=[Depends(require_login)])
async def save_profile(
    request: Request,
    display_name: str = Form(...),
    password: str = Form(""),
):
    user = current_user(request)
    try:
        # Only the main/super account may change a password from Settings.
        pwd = password.strip() or None if is_super(request) else None
        await db.update_user_profile(user["id"], display_name=display_name, password=pwd)
        # Keep session display name in sync
        request.session["user"]["display_name"] = display_name.strip()
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/settings?error={str(exc)[:120]}", status_code=303)
    return RedirectResponse("/settings?msg=Profile+updated", status_code=303)


@app.post("/settings/cloudflare", dependencies=[Depends(require_login)])
async def save_cloudflare(request: Request, token: str = Form(...)):
    from .services import user_secrets

    user = current_user(request)
    user_secrets.write_cloudflare_token(user["id"], token.strip())
    return RedirectResponse("/settings?msg=Cloudflare+token+saved", status_code=303)


@app.post("/settings/credentials", dependencies=[Depends(require_login)])
async def upload_credentials(request: Request, file: UploadFile = File(...)):
    user = current_user(request)
    try:
        content = await file.read()
        google_auth.save_uploaded_credentials(user["id"], content)
        return RedirectResponse("/settings?msg=Google+credentials+uploaded", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/settings?error={str(exc)[:120]}", status_code=303)


@app.get("/oauth/start/{kind}", dependencies=[Depends(require_login)])
async def oauth_start(request: Request, kind: str):
    if kind not in ("site", "postmaster"):
        return RedirectResponse("/settings?error=Invalid+OAuth+kind", status_code=303)
    user = current_user(request)
    state = secrets.token_urlsafe(24)
    public_base = public_base_from_request(request)
    persist_public_base_url(public_base)
    request.session["oauth_state"] = state
    request.session["oauth_kind"] = kind
    request.session["oauth_user_id"] = user["id"]
    request.session["oauth_redirect_base"] = public_base
    try:
        url = google_auth.authorization_url(user["id"], kind, state, public_base_url=public_base)
        return RedirectResponse(url, status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/settings?error={str(exc)[:160]}", status_code=303)


@app.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    if error:
        return RedirectResponse(f"/settings?error={error}", status_code=303)
    if not code or state != request.session.get("oauth_state"):
        return RedirectResponse("/settings?error=OAuth+state+mismatch", status_code=303)
    kind = request.session.get("oauth_kind", "site")
    user = current_user(request)
    oauth_user_id = int(request.session.get("oauth_user_id") or user["id"])
    if oauth_user_id != user["id"]:
        return RedirectResponse("/settings?error=OAuth+user+mismatch", status_code=303)
    try:
        public_base = request.session.get("oauth_redirect_base") or public_base_from_request(request)
        google_auth.exchange_code(user["id"], kind, code, public_base_url=public_base)
        request.session.pop("oauth_state", None)
        request.session.pop("oauth_kind", None)
        request.session.pop("oauth_user_id", None)
        request.session.pop("oauth_redirect_base", None)
        return RedirectResponse(f"/settings?msg=Google+{kind}+authorized", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/settings?error={str(exc)[:160]}", status_code=303)


@app.get("/users", response_class=HTMLResponse, dependencies=[Depends(require_super)])
async def users_page(request: Request):
    users = await db.list_users()
    return templates.TemplateResponse(
        "users.html",
        _ctx(
            request,
            users=users,
            message=request.query_params.get("msg"),
            error=request.query_params.get("error"),
        ),
    )


@app.post("/users/create", dependencies=[Depends(require_super)])
async def users_create(
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    role: str = Form("sub"),
):
    username = username.strip().lower()
    if not username or " " in username:
        return RedirectResponse("/users?error=Username+must+be+one+word", status_code=303)
    if len(password) < 8:
        return RedirectResponse("/users?error=Password+must+be+at+least+8+characters", status_code=303)
    if role not in ("super", "sub"):
        role = "sub"
    try:
        await db.create_user(username, password, display_name.strip() or username, role=role)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/users?error={str(exc)[:120]}", status_code=303)
    return RedirectResponse("/users?msg=User+created", status_code=303)


@app.post("/users/{user_id}/toggle", dependencies=[Depends(require_super)])
async def users_toggle(user_id: int, is_active: int = Form(...)):
    await db.set_user_active(user_id, bool(is_active))
    return RedirectResponse("/users?msg=User+updated", status_code=303)


@app.post("/users/{user_id}/password", dependencies=[Depends(require_super)])
async def users_reset_password(user_id: int, password: str = Form(...)):
    if len(password) < 8:
        return RedirectResponse("/users?error=Password+must+be+at+least+8+characters", status_code=303)
    await db.reset_user_password(user_id, password)
    return RedirectResponse("/users?msg=Password+reset", status_code=303)


@app.get("/healthz")
async def healthz():
    from .config import DATA_DIR, DB_PATH

    return {
        "ok": True,
        "data_dir": str(DATA_DIR),
        "db_exists": DB_PATH.exists(),
        "users": db.count_users(),
    }
