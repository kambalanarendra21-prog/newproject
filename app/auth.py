from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings


def add_session_middleware(app) -> None:
    settings = get_settings()
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="pm_session",
        same_site="lax",
        https_only=settings.public_base_url.startswith("https://"),
        max_age=60 * 60 * 12,
    )


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


async def require_login(request: Request):
    if not is_authenticated(request):
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )


def login_user(request: Request, password: str) -> bool:
    settings = get_settings()
    if password and password == settings.dashboard_password:
        request.session["authenticated"] = True
        return True
    return False


def logout_user(request: Request) -> None:
    request.session.clear()


def redirect_if_authed(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return None
