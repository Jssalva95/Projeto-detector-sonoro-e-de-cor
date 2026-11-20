"""Real cookie transport against isolated, migration-backed user records."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.browser_auth import ACCESS_COOKIE, REFRESH_COOKIE, COOKIE_PATH
from app.api.dependencies import get_session
from app.main import app
from app.security import issue_token
from test_auth import db, user, settings, PASSWORD

ORIGIN = "https://localhost:5173"
HEADERS = {"Origin": ORIGIN, "X-CSRF-Protection": "1"}


@pytest.fixture
def isolated_application_stack():
    previous_stack = app.middleware_stack
    previous_overrides = app.dependency_overrides.copy()
    app.middleware_stack = None
    try:
        yield
    finally:
        app.middleware_stack = previous_stack
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


@pytest.fixture
def browser(db, monkeypatch, isolated_application_stack):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["https://localhost:5173", "http://localhost:5173"]')
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app, base_url="https://localhost", headers=HEADERS) as client:
        yield client
    app.dependency_overrides.clear()


def sign_in(browser, user):
    return browser.post(COOKIE_PATH + "/login", json={"email": user.email, "password": PASSWORD})


def test_login_cookie_flags_restore_and_original_contract(browser, user):
    result = sign_in(browser, user)
    assert result.status_code == 200
    assert set(result.json()) == {"access_token", "expires_in", "token_type", "user"}
    assert "password_hash" not in result.text and PASSWORD not in result.text
    cookies = result.headers.get_list("set-cookie")
    assert len(cookies) == 2
    for cookie in cookies:
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        assert "Path=" + COOKIE_PATH in cookie and "Domain=" not in cookie
    restored = browser.post(COOKIE_PATH + "/session")
    assert restored.status_code == 200
    assert restored.json()["access_token"] == result.json()["access_token"]
    assert "set-cookie" not in restored.headers
    assert restored.headers["cache-control"] == "no-store"
    # Cookies do not authenticate ordinary Bearer resources.
    assert browser.get("/api/v1/auth/me").status_code == 401
    legacy = browser.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert "refresh_token" in legacy.json()


def test_refresh_only_replaces_access_and_rechecks_user(browser, user, db):
    sign_in(browser, user)
    original_refresh = browser.cookies.get(REFRESH_COOKIE)
    browser.cookies.delete(ACCESS_COOKIE)
    renewed = browser.post(COOKIE_PATH + "/session")
    assert renewed.status_code == 200
    assert len(renewed.headers.get_list("set-cookie")) == 1
    assert renewed.headers["set-cookie"].startswith(ACCESS_COOKIE + "=")
    assert browser.cookies.get(REFRESH_COOKIE) == original_refresh
    user.role = "VIEWER"
    db.commit()
    assert browser.post(COOKIE_PATH + "/session").json()["user"]["role"] == "VIEWER"
    user.is_active = False
    db.commit()
    assert browser.post(COOKIE_PATH + "/session").status_code == 401
    browser.cookies.delete(ACCESS_COOKIE)
    assert browser.post(COOKIE_PATH + "/session").status_code == 401


@pytest.mark.parametrize("kind", ["expired", "access", "invalid"])
def test_invalid_refresh_cannot_restore(browser, user, settings, kind):
    now = datetime.now(timezone.utc)
    token = jwt.encode({"sub": str(user.id), "iat": now - timedelta(minutes=2),
                       "exp": now - timedelta(minutes=1), "token_type": "refresh"},
                      settings.secret, algorithm=settings.algorithm)
    if kind == "access":
        token = issue_token(user.id, "access", settings)
    if kind == "invalid":
        token = "invalid-fixture"
    browser.cookies.set(REFRESH_COOKIE, token, path=COOKIE_PATH)
    assert browser.post(COOKIE_PATH + "/session").status_code == 401


def test_valid_access_survives_missing_refresh_and_logout_clears_both(browser, user):
    signed = sign_in(browser, user)
    browser.cookies.delete(REFRESH_COOKIE)
    assert browser.post(COOKIE_PATH + "/session").json()["access_token"] == signed.json()["access_token"]
    logged_out = browser.post(COOKIE_PATH + "/logout")
    assert logged_out.status_code == 204 and not logged_out.content
    assert len(logged_out.headers.get_list("set-cookie")) == 2
    assert not browser.cookies
    assert browser.post(COOKIE_PATH + "/session").status_code == 401


def test_expired_access_signature_is_checked_and_refresh_expiry_is_not_extended(browser, user, settings):
    sign_in(browser, user)
    original_refresh = browser.cookies.get(REFRESH_COOKIE)
    now = datetime.now(timezone.utc)
    expired_access = jwt.encode({"sub": str(user.id), "iat": now - timedelta(minutes=2),
                                "exp": now - timedelta(minutes=1), "token_type": "access"},
                               settings.secret, algorithm=settings.algorithm)
    browser.cookies.delete(ACCESS_COOKIE)
    browser.cookies.set(ACCESS_COOKIE, expired_access, path=COOKIE_PATH)
    restored = browser.post(COOKIE_PATH + "/session")
    assert restored.status_code == 200
    assert restored.json()["access_token"] != expired_access
    assert browser.cookies.get(REFRESH_COOKIE) == original_refresh
    assert 0 < restored.json()["expires_in"] <= settings.access_minutes * 60


@pytest.mark.parametrize("path", ["/login", "/session", "/logout"])
@pytest.mark.parametrize("headers", [
    {}, {"Origin": ORIGIN}, {"X-CSRF-Protection": "1"},
    {"Origin": "https://evil.invalid", "X-CSRF-Protection": "1"},
    {"Origin": "null", "X-CSRF-Protection": "1"},
    {"Origin": ORIGIN, "X-CSRF-Protection": "wrong"},
])
def test_csrf_rejection_before_cookie_operations(browser, user, path, headers):
    browser.headers.clear()
    result = browser.post(COOKIE_PATH + path, headers=headers,
                          json={"email": user.email, "password": PASSWORD} if path == "/login" else None)
    assert result.status_code == 403
    assert "set-cookie" not in result.headers


def test_preflight_requires_exact_origin(browser):
    result = browser.options(COOKIE_PATH + "/session", headers={"Origin": ORIGIN,
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-csrf-protection"})
    assert result.status_code == 200
    assert result.headers["access-control-allow-origin"] == ORIGIN
    assert result.headers["access-control-allow-credentials"] == "true"


def test_wrong_password_and_validation_do_not_echo_inputs(browser, user):
    response = browser.post(COOKIE_PATH + "/login", json={"email": user.email, "password": "private-fixture"})
    assert response.status_code == 401 and "private-fixture" not in response.text
    response = browser.post(COOKIE_PATH + "/login", json={"password": "private-fixture"})
    assert response.status_code == 422 and "private-fixture" not in response.text


def test_http_only_allowed_on_loopback_and_same_host(db, user, monkeypatch, isolated_application_stack):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://localhost:5173", "http://example.invalid"]')
    app.dependency_overrides[get_session] = lambda: db
    try:
        with TestClient(app, base_url="http://localhost", headers={**HEADERS, "Origin": "http://localhost:5173"}) as local:
            response = sign_in(local, user)
            assert response.status_code == 200
            assert "Secure" not in response.headers["set-cookie"]
            assert local.post(COOKIE_PATH + "/session").status_code == 200
        for api, origin in [("http://example.invalid", "http://example.invalid"),
                            ("http://127.0.0.1", "http://localhost:5173")]:
            with TestClient(app, base_url=api, headers={**HEADERS, "Origin": origin}) as denied:
                assert denied.post(COOKIE_PATH + "/session").status_code == 403
    finally:
        app.dependency_overrides.clear()
