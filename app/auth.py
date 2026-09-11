from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from . import db
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


def current_user(request: Request) -> dict | None:
    return request.session.get("user")


def is_authenticated(request: Request) -> bool:
    return bool(current_user(request))


def is_super(request: Request) -> bool:
    user = current_user(request)
    return bool(user and user.get("role") == "super")


def owner_scope(request: Request) -> int | None:
    """None = all records (super user). Otherwise filter by that user id."""
    user = current_user(request)
    if not user:
        return -1
    if user.get("role") == "super":
        return None
    return int(user["id"])


async def require_login(request: Request):
    if not is_authenticated(request):
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )


async def require_super(request: Request):
    await require_login(request)
    if not is_super(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Main account only")


async def login_user(request: Request, username: str, password: str) -> bool:
    user = await db.get_user_by_username(username)
    if not user or not user.get("is_active"):
        return False
    if not db.verify_password(password, user["password_hash"]):
        return False
    request.session["user"] = {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
    }
    return True


def logout_user(request: Request) -> None:
    request.session.clear()
