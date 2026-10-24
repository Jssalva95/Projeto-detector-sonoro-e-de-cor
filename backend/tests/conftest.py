"""Never inherit operator delivery enablement in automated tests."""

import pytest


@pytest.fixture(autouse=True)
def isolated_alert_environment(monkeypatch):
    monkeypatch.setenv('TELEGRAM_ENABLED', 'false')
    monkeypatch.setenv('EMAIL_ENABLED', 'false')
    monkeypatch.delenv('ALERT_COOLDOWN_SECONDS', raising=False)
