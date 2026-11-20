"""Cookie transport for browsers; existing JSON/Bearer contracts remain intact."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.auth import SessionDependency, SettingsDependency, no_cache
from app.api.dependencies import unauthorized
from app.cors import cors_origins
from app.schemas.auth import BrowserSessionResponse, LoginRequest
from app.security import InvalidCredentials, token_identity
from app.services import auth

COOKIE_PATH = "/api/v1/auth/browser"
ACCESS_COOKIE = "mm_access"
REFRESH_COOKIE = "mm_refresh"


def browser_request(request: Request) -> None:
    # A fixed custom header is a preflight barrier, not a secret CSRF token.
    # Require an exact approved Origin as well; reject simple/form requests.
    origin = request.headers.get("origin", "")
    if (origin not in cors_origins()
            or request.headers.get("x-csrf-protection") != "1"):
        raise HTTPException(403, "Browser origin or CSRF header rejected")
    # Strict cookies need a same-site deployment. Enforce the narrower,
    # deterministic same-host contract (ports may differ) without guessing a PSL.
    source = urlsplit(origin)
    if source.hostname != request.url.hostname or source.scheme != request.url.scheme:
        raise HTTPException(403, "Browser and API must use the same scheme and hostname")
    if request.url.scheme != "https" and request.url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise HTTPException(403, "HTTPS is required outside loopback development")


router = APIRouter(prefix=COOKIE_PATH, tags=["Browser authentication"],
                   dependencies=[Depends(browser_request)])


def set_token_cookie(response: Response, request: Request, name: str, token: str,
                     expiry: int) -> None:
    response.set_cookie(name, token, path=COOKIE_PATH, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict",
                        expires=datetime.fromtimestamp(expiry, timezone.utc),
                        max_age=max(0, expiry - int(datetime.now(timezone.utc).timestamp())))


@router.post("/login", response_model=BrowserSessionResponse)
def login(payload: LoginRequest, request: Request, response: Response,
          session: SessionDependency, settings: SettingsDependency) -> BrowserSessionResponse:
    no_cache(response)
    try:
        tokens = auth.login(session, payload.email, payload.password.get_secret_value(), settings)
        result = auth.browser_session(session, tokens.access_token, settings)
        for name, token, purpose in ((ACCESS_COOKIE, tokens.access_token, "access"),
                                     (REFRESH_COOKIE, tokens.refresh_token, "refresh")):
            _, expiry = token_identity(token, purpose, settings)
            set_token_cookie(response, request, name, token, expiry)
        return result
    except InvalidCredentials:
        raise unauthorized() from None


@router.post("/session", response_model=BrowserSessionResponse)
def restore(request: Request, response: Response, session: SessionDependency,
            settings: SettingsDependency) -> BrowserSessionResponse:
    no_cache(response)
    access = request.cookies.get(ACCESS_COOKIE, "")
    try:
        # Reload reuses a valid access, even after the refresh has expired.
        return auth.browser_session(session, access, settings)
    except InvalidCredentials:
        pass
    try:
        tokens = auth.refresh(session, request.cookies.get(REFRESH_COOKIE, ""), settings)
        result = auth.browser_session(session, tokens.access_token, settings)
        _, expiry = token_identity(tokens.access_token, "access", settings)
        set_token_cookie(response, request, ACCESS_COOKIE, tokens.access_token, expiry)
        # Never rewrite the refresh cookie or extend its original lifetime.
        return result
    except InvalidCredentials:
        raise unauthorized() from None


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    no_cache(response)
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(name, path=COOKIE_PATH, httponly=True,
                               secure=request.url.scheme == "https", samesite="strict")
