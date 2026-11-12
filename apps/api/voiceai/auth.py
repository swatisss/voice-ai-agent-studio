"""Studio sign-in: two fixed demo accounts, a signed session cookie, the admin-only guard, who is recorded.

Spec: /architecture/studio-auth.md
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from voiceai.config import get_settings
from voiceai.errors import ApiError

COOKIE = "studio_session"
SESSION_SECONDS = 12 * 3600


@dataclass(frozen=True)
class User:
    email: str
    name: str
    role: str  # admin | reviewer

    def out(self) -> dict[str, str]:
        return {"email": self.email, "name": self.name, "role": self.role}


ADMIN = User("admin@echomind.test", "Alex Admin", "admin")
REVIEWER = User("reviewer@echomind.test", "Riley Reviewer", "reviewer")
STUDIO = User("", "Studio", "admin")  # sign-in off: every request acts as this (AUTH-06)
ACCOUNTS = {ADMIN.email: ADMIN, REVIEWER.email: REVIEWER}


def _passwords() -> dict[str, str]:
    st = get_settings()
    return {ADMIN.email: st.studio_admin_password or "", REVIEWER.email: st.studio_reviewer_password or ""}


def enabled() -> bool:
    return any(_passwords().values())


def _key() -> bytes:
    st = get_settings()
    if st.studio_session_secret:
        return st.studio_session_secret.encode()
    pw = _passwords()  # derived: sessions survive a restart and end when a password changes
    return hashlib.sha256(f"studio-session|{pw[ADMIN.email]}|{pw[REVIEWER.email]}".encode()).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(user: User, now: float | None = None) -> str:
    payload = _b64(json.dumps({"email": user.email, "role": user.role, "exp": int((now or time.time()) + SESSION_SECONDS)}).encode())
    mac = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{mac}"


def verify(token: str | None, now: float | None = None) -> User | None:
    if not token or "." not in token:
        return None
    payload, mac = token.rsplit(".", 1)
    expected = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except ValueError:
        return None
    user = ACCOUNTS.get(data.get("email", ""))
    if user is None or data.get("role") != user.role or not _passwords()[user.email]:
        return None
    if int(data.get("exp", 0)) < (now or time.time()):
        return None
    return user


# Admin-only requests (/architecture/studio-auth.md, Guard): (methods, path pattern)
_W = ("POST", "PUT", "PATCH", "DELETE")
ADMIN_ONLY: list[tuple[tuple[str, ...], re.Pattern[str]]] = [(m, re.compile(p)) for m, p in [
    (("POST",), r"^/api/agents$"),
    (("PUT",), r"^/api/agents/[^/]+$"),
    (("POST",), r"^/api/agents/[^/]+/publish$"),
    (("POST",), r"^/api/proposals/[^/]+/approve$"),
    (_W, r"^/api/(tools|skills|personas|use-cases)(/.*)?$"),
    (_W, r"^/api/routing/cases(/.*)?$"),
    (_W, r"^/api/agents/[^/]+/scenarios$"),
    (_W, r"^/api/scenarios/[^/]+$"),
    (_W, r"^/api/knowledge/(?!search$).*$"),
    (_W, r"^/api/tenant-settings(/.*)?$"),
    (_W, r"^/api/(api-keys|webhooks|phone-numbers)(/.*)?$"),
    (("POST",), r"^/api/members/[^/]+/memory/(erase|[^/]+/restore)$"),
]]


def admin_only(method: str, path: str) -> bool:
    return any(method in methods and pattern.match(path) for methods, pattern in ADMIN_ONLY)


def _guarded(path: str) -> bool:
    return path.startswith("/api/") and not path.startswith(("/api/auth/", "/api/telephony/"))


def _cookie(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name == b"cookie":
            for part in value.decode("latin-1").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE:
                    return v
    return None


class AuthMiddleware:
    """Pure ASGI, so event streams are not buffered; the user lands in `request.state.studio_user`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        user: User | None = STUDIO
        if enabled():
            user = verify(_cookie(scope))
        scope.setdefault("state", {})["studio_user"] = user
        path, method = scope["path"], scope["method"]
        if _guarded(path) and method != "OPTIONS":
            if user is None:
                await JSONResponse({"error": "login_required", "detail": "Sign in to the Studio"}, status_code=401)(scope, receive, send)
                return
            if user.role != "admin" and admin_only(method, path):
                await JSONResponse({"error": "admin_required", "detail": "Only an admin can do this: it changes what callers hear or how the business unit is set up"},
                                   status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def current_user(request: Request) -> User | None:
    return getattr(request.state, "studio_user", None)


def actor(request: Request, given: str) -> str:
    """The name recorded for a decision: the signed-in user when sign-in is on, else the body's name (AUTH-05, AUTH-06)."""
    user = current_user(request)
    return user.name if enabled() and user else given


def publisher(request: Request) -> str:
    user = current_user(request)
    return user.name if user else STUDIO.name


router = APIRouter(prefix="/api/auth")


class Login(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: Login, request: Request, response: Response) -> dict[str, Any]:
    user = ACCOUNTS.get(body.email.strip().lower())
    expected = _passwords().get(user.email, "") if user else ""
    ok = hmac.compare_digest(body.password.encode(), expected.encode()) if expected else False
    if not (user and ok):
        raise ApiError(401, "bad_credentials", "Email or password is wrong")
    response.set_cookie(COOKIE, sign(user), max_age=SESSION_SECONDS, httponly=True, samesite="lax", path="/",
                        secure=request.url.scheme == "https")
    return {"user": user.out()}


@router.post("/logout", status_code=204)
async def logout(response: Response) -> Response:
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me")
async def me(request: Request) -> dict[str, Any]:
    on = enabled()
    user = current_user(request) if on else STUDIO
    return {"enabled": on, "user": user.out() if user else None}
