"""Authentication integration in the existing transactional PostgreSQL test schema."""

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import seed_admin
from app.api.auth import router
from app.api.dependencies import get_session, require_roles
from app.main import app, safe_auth_validation
from app.models import User
from app.models.enums import Role
from app.schemas.auth import LoginRequest, TokenResponse
from app.security import (
    AuthConfigurationError, InvalidCredentials, auth_settings, hash_password,
    issue_token, token_subject, verify_password,
)
from app.services.auth import UserAlreadyExists, create_admin
from test_domain import db  # Reuse migration-based fixture; no production rows.

PASSWORD = "isolated-test-password"
SECRET = "isolated-jwt-test-key-" * 4


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    for key, value in {
        "JWT_SECRET": SECRET, "JWT_ALGORITHM": "HS256",
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": "5", "JWT_REFRESH_TOKEN_EXPIRE_MINUTES": "30",
    }.items():
        monkeypatch.setenv(key, value)
    return auth_settings()


@pytest.fixture
def user(db):
    result = create_admin(db, "Fixture", "Admin@example.invalid", PASSWORD)
    db.commit()
    return result


@pytest.fixture
def client(db):
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.add_exception_handler(RequestValidationError, safe_auth_validation)
    test_app.dependency_overrides[get_session] = lambda: db

    @test_app.get("/test-admin")
    def admin_only(user: Annotated[User, Depends(require_roles(Role.ADMIN))]):
        return {"id": user.id}

    with TestClient(test_app) as instance:
        yield instance


def authorization(token):
    return {"Authorization": "Bearer " + token}


def test_seed_hash_and_duplicate_preserves_user(db, user):
    original = user.password_hash
    assert original.startswith("$argon2id$")
    assert original != PASSWORD
    assert verify_password(PASSWORD, original)
    assert not verify_password("incorrect", original)
    assert hash_password(PASSWORD) != original
    assert user.role == "ADMIN" and user.is_active
    with pytest.raises(UserAlreadyExists):
        create_admin(db, "Replacement", "admin@example.invalid", "replacement")
    db.expire_all()
    assert user.name == "Fixture" and user.password_hash == original
    assert db.scalar(select(func.count()).select_from(User)) == 1


def test_login_me_refresh_reuse(client, user, settings):
    response = client.post("/api/v1/auth/login", json={"email": user.email.lower(), "password": PASSWORD})
    assert response.status_code == 200
    result = response.json()
    assert set(result) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert result["token_type"] == "bearer" and result["expires_in"] == 300
    assert response.headers["cache-control"] == "no-store"
    claims = jwt.decode(result["access_token"], settings.secret, algorithms=[settings.algorithm])
    assert set(claims) == {"sub", "iat", "exp", "token_type"}
    assert claims["sub"] == str(user.id) and claims["token_type"] == "access"
    assert claims["exp"] - claims["iat"] == 300
    me = client.get("/api/v1/auth/me", headers=authorization(result["access_token"]))
    assert me.status_code == 200 and me.json()["id"] == user.id
    assert "password_hash" not in me.json() and "password" not in me.json()
    for _ in range(2):
        renewed = client.post("/api/v1/auth/refresh", json={"refresh_token": result["refresh_token"]})
        assert renewed.status_code == 200
        assert set(renewed.json()) == {"access_token", "token_type", "expires_in"}
        assert token_subject(renewed.json()["access_token"], "access", settings) == user.id


@pytest.mark.parametrize("case", ["wrong_password", "unknown", "inactive", "malformed_hash"])
def test_invalid_login_generic(client, db, user, case):
    email, password = user.email, PASSWORD
    if case == "wrong_password": password = "wrong"
    if case == "unknown": email = "unknown@example.invalid"
    if case == "inactive": user.is_active = False
    if case == "malformed_hash": user.password_hash = "$argon2id$invalid"
    db.commit()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}


def test_token_purpose_is_exclusive(client, user, settings):
    access = issue_token(user.id, "access", settings)
    refresh = issue_token(user.id, "refresh", settings)
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": access}).status_code == 401
    assert client.get("/api/v1/auth/me", headers=authorization(refresh)).status_code == 401
    assert client.get("/test-admin", headers=authorization(refresh)).status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize("action", ["deactivate", "delete"])
def test_current_user_rechecked_for_access_and_refresh(client, db, user, settings, action):
    access = issue_token(user.id, "access", settings)
    refresh = issue_token(user.id, "refresh", settings)
    if action == "delete": db.delete(user)
    else: user.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=authorization(access)).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 401


@pytest.mark.parametrize("role", [Role.OPERATOR, Role.VIEWER])
def test_rbac_uses_current_role(client, db, user, settings, role):
    headers = authorization(issue_token(user.id, "access", settings))
    assert client.get("/test-admin", headers=headers).status_code == 200
    user.role = role.value
    db.commit()
    assert client.get("/test-admin", headers=headers).status_code == 403
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["role"] == role.value


@pytest.mark.parametrize("purpose", ["access", "refresh"])
@pytest.mark.parametrize("case", ["expired", "signature", "algorithm", "missing_exp", "missing_type",
                                  "bad_subject", "large_subject", "future_iat", "invalid", "none"])
def test_invalid_tokens(client, user, settings, purpose, case):
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user.id), "iat": now - timedelta(minutes=2),
              "exp": now + timedelta(minutes=5), "token_type": purpose}
    secret, algorithm = settings.secret, settings.algorithm
    if case == "expired": claims["exp"] = now - timedelta(minutes=1)
    if case == "signature": secret = "wrong-test-key-" * 8
    if case == "algorithm": algorithm = "HS512"
    if case == "missing_exp": del claims["exp"]
    if case == "missing_type": del claims["token_type"]
    if case == "bad_subject": claims["sub"] = "not-an-internal-id"
    if case == "large_subject": claims["sub"] = "9" * 40
    if case == "future_iat": claims["iat"] = now + timedelta(minutes=1)
    if case == "none": secret, algorithm = "", "none"
    token = "malformed-token" if case == "invalid" else jwt.encode(claims, secret, algorithm=algorithm)
    if purpose == "access":
        response = client.get("/api/v1/auth/me", headers=authorization(token))
    else:
        response = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert response.status_code == 401
    assert token not in response.text


@pytest.mark.parametrize("path,payload", [
    ("login", {"email": "test", "password": {"secret": PASSWORD}}),
    ("login", {"email": "test", "password": PASSWORD, "extra": SECRET}),
    ("login", {"email": "test", "password": ""}),
    ("refresh", {"refresh_token": {"secret": SECRET}}),
])
def test_validation_never_echoes_secrets(client, path, payload):
    response = client.post("/api/v1/auth/" + path, json=payload)
    assert response.status_code == 422
    assert PASSWORD not in response.text and SECRET not in response.text


def test_logs_and_representations_hide_secrets(client, user, caplog, settings):
    caplog.set_level(logging.DEBUG)
    result = client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}).json()
    for value in (PASSWORD, SECRET, user.password_hash, result["access_token"], result["refresh_token"]):
        assert value not in caplog.text
    assert PASSWORD not in repr(LoginRequest(email=user.email, password=PASSWORD))
    assert SECRET not in repr(settings)
    assert result["access_token"] not in repr(TokenResponse(**result))


@pytest.mark.parametrize("key,value", [
    ("JWT_SECRET", ""), ("JWT_SECRET", "short"), ("JWT_ALGORITHM", "none"),
    ("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "0"), ("JWT_REFRESH_TOKEN_EXPIRE_MINUTES", ""),
    ("JWT_REFRESH_TOKEN_EXPIRE_MINUTES", "-1"), ("JWT_REFRESH_TOKEN_EXPIRE_MINUTES", "invalid"),
])
def test_configuration_is_required(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(AuthConfigurationError):
        auth_settings()


def test_missing_configuration_fails_closed(client, monkeypatch):
    monkeypatch.delenv("JWT_REFRESH_TOKEN_EXPIRE_MINUTES")
    response = client.post("/api/v1/auth/login", json={"email": "test", "password": PASSWORD})
    assert response.status_code == 503
    assert PASSWORD not in response.text and SECRET not in response.text


def test_manual_seed_requires_config_and_never_overwrites(db, monkeypatch, capsys):
    @contextmanager
    def isolated_scope():
        with db.begin_nested():
            yield db
    monkeypatch.setattr(seed_admin, "session_scope", isolated_scope)
    for key in ("ADMIN_NAME", "ADMIN_EMAIL", "ADMIN_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    assert seed_admin.main() == 1
    assert db.scalar(select(func.count()).select_from(User)) == 0
    monkeypatch.setenv("ADMIN_NAME", "Seed fixture")
    monkeypatch.setenv("ADMIN_EMAIL", "seed@example.invalid")
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    assert seed_admin.main() == 0
    monkeypatch.setenv("ADMIN_PASSWORD", "replacement")
    assert seed_admin.main() == 1
    row = db.scalar(select(User))
    assert row is not None and verify_password(PASSWORD, row.password_hash)
    assert db.scalar(select(func.count()).select_from(User)) == 1
    output = capsys.readouterr().out
    assert PASSWORD not in output and row.password_hash not in output


def test_production_openapi_only_approved_endpoints():
    schema = app.openapi()
    assert set(schema["paths"]) == {
        "/health", "/ready", "/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/me",
    }
    assert schema["paths"]["/api/v1/auth/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert all("password_hash" not in model.get("properties", {})
               for model in schema["components"]["schemas"].values())
    assert schema["components"]["schemas"]["LoginRequest"]["properties"]["password"]["writeOnly"]
