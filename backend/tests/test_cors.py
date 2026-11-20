"""Browser HTTP policy does not replace authorization or WebSocket origins."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.cors import ConfiguredCORSMiddleware, cors_origins
from app.main import app

ORIGIN = "http://frontend.example.invalid"


@pytest.mark.parametrize("value", [None, "", "[]", "{}", "null", '["*"]', '[1]',
    '["null"]', '["https://user:password@example.invalid"]', '["https://example.invalid/path"]',
    '["https://example.invalid?x=1"]', '["https://example.invalid#fragment"]',
    '["https://example.invalid:99999"]', '[" https://example.invalid"]'])
def test_invalid_configuration_is_sanitized(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS")
    else:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", value)
    with pytest.raises(ValueError, match="^Invalid or missing CORS configuration$"):
        cors_origins()


def test_allowed_preflight_and_auth_still_required():
    with TestClient(app) as client:
        preflight = client.options("/api/v1/machines", headers={
            "Origin": ORIGIN, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        })
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == ORIGIN
        assert preflight.headers["access-control-allow-credentials"] == "true"
        assert "Origin" in preflight.headers["vary"]
        denied = client.get("/api/v1/machines", headers={"Origin": ORIGIN})
        assert denied.status_code == 401
        assert denied.headers["access-control-allow-origin"] == ORIGIN


@pytest.mark.parametrize("origin, method, header", [
    ("http://other.example.invalid", "GET", "authorization"),
    (ORIGIN + ".evil.invalid", "GET", "authorization"),
    ("null", "GET", "authorization"),
    (ORIGIN, "PUT", "content-type"),
    (ORIGIN, "POST", "x-api-key"),
])
def test_preflight_rejects_unapproved_origins_methods_headers(origin, method, header):
    with TestClient(app) as client:
        response = client.options("/api/v1/machines", headers={"Origin": origin,
            "Access-Control-Request-Method": method, "Access-Control-Request-Headers": header})
        assert response.status_code == 400
        if origin != ORIGIN:
            assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("status", [403, 409, 422, 429, 503])
def test_handled_errors_and_retry_after_visible_to_browser(status):
    isolated = FastAPI()
    isolated.add_middleware(ConfiguredCORSMiddleware)

    @isolated.get("/probe")
    def probe():
        raise HTTPException(status, "fixture", headers={"Retry-After": "5"})

    with TestClient(isolated) as client:
        response = client.get("/probe", headers={"Origin": ORIGIN})
    assert response.status_code == status
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "Retry-After" in response.headers["access-control-expose-headers"]


def test_cors_independent_of_websocket_and_requests_without_origin(monkeypatch):
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", '["http://different.example.invalid"]')
    assert cors_origins() == [ORIGIN]
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
