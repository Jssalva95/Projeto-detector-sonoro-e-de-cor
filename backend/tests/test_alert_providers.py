"""Provider contract tests: fake credentials and transports, no external delivery."""

import asyncio
import json
import logging
import smtplib
import ssl
import threading
from unittest.mock import MagicMock

import httpx
import pytest

from app.alerts.base import ProviderError
from app.alerts.config import AlertConfigurationError, EmailSettings, TelegramSettings
from app.alerts.providers import configured_providers
from app.alerts.email import EmailProvider
from app.alerts.telegram import TelegramProvider


@pytest.fixture
def clean_env(monkeypatch):
    for name in ('TELEGRAM_ENABLED', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_TIMEOUT_SECONDS',
                 'EMAIL_ENABLED', 'SMTP_HOST', 'SMTP_PORT', 'SMTP_TLS_MODE',
                 'SMTP_TIMEOUT_SECONDS', 'SMTP_FROM', 'SMTP_USER', 'SMTP_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_disabled_channels(clean_env):
    assert configured_providers() == {}


@pytest.mark.parametrize('channel', ['TELEGRAM', 'EMAIL'])
def test_enabled_requires_configuration(clean_env, channel):
    clean_env.setenv(channel + '_ENABLED', 'true')
    with pytest.raises(AlertConfigurationError):
        configured_providers()


@pytest.mark.parametrize('value', ['yes', '1', 'invalid'])
def test_invalid_enable_flag(clean_env, value):
    clean_env.setenv('TELEGRAM_ENABLED', value)
    with pytest.raises(AlertConfigurationError):
        configured_providers()


def setup_env(monkeypatch):
    values = dict(TELEGRAM_ENABLED='true', TELEGRAM_BOT_TOKEN='123:test_only',
                  TELEGRAM_TIMEOUT_SECONDS='2', EMAIL_ENABLED='true',
                  SMTP_HOST='smtp.invalid', SMTP_PORT='587', SMTP_TLS_MODE='starttls',
                  SMTP_TIMEOUT_SECONDS='2', SMTP_FROM='sender@example.invalid',
                  SMTP_USER='test', SMTP_PASSWORD='fake_secret')
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_factory_without_network(clean_env):
    setup_env(clean_env)
    providers = configured_providers()
    assert set(providers) == {'TELEGRAM', 'EMAIL'}
    assert 'test_only' not in repr(providers['TELEGRAM'].settings)
    assert 'fake_secret' not in repr(providers['EMAIL'].settings)


@pytest.mark.parametrize('key,value', [
    ('TELEGRAM_TIMEOUT_SECONDS', '0'), ('TELEGRAM_TIMEOUT_SECONDS', 'nan'),
    ('TELEGRAM_BOT_TOKEN', 'secret/invalid'), ('SMTP_PORT', '0'),
    ('SMTP_PORT', '65536'), ('SMTP_TIMEOUT_SECONDS', 'inf'),
    ('SMTP_TLS_MODE', 'plain'), ('SMTP_FROM', 'a@b\r\nBcc:x@y'),
    ('SMTP_PASSWORD', ''), ('SMTP_USER', ''), ('SMTP_HOST', 'bad host'),
])
def test_invalid_configuration_safe_errors(clean_env, key, value):
    setup_env(clean_env)
    clean_env.setenv(key, value)
    with pytest.raises(AlertConfigurationError) as caught:
        configured_providers()
    assert 'fake_secret' not in str(caught.value)
    assert 'test_only' not in str(caught.value)


def telegram(handler):
    return TelegramProvider(TelegramSettings(token='123:test_only', timeout=2),
                            transport=httpx.MockTransport(handler))


def test_telegram_contract_and_redaction(caplog):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.method == 'POST'
        assert request.url.host == 'api.telegram.org'
        assert json.loads(request.content) == {'chat_id': '-123', 'text': 'Alerta <teste> ç'}
        assert request.extensions['timeout']['read'] == 2
        return httpx.Response(200, json={'ok': True, 'result': {'message_id': 1}})
    with caplog.at_level(logging.INFO, logger='httpx'):
        asyncio.run(telegram(handle).send('Alerta <teste> ç', '-123'))
    assert len(requests) == 1
    assert 'test_only' not in caplog.text
    assert '[REDACTED]' in caplog.text


@pytest.mark.parametrize('response,code', [
    (httpx.Response(401), 'telegram_rejected'),
    (httpx.Response(429), 'telegram_rejected'),
    (httpx.Response(500), 'delivery_unconfirmed'),
    (httpx.Response(302, headers={'location': 'https://example.invalid'}), 'delivery_unconfirmed'),
    (httpx.Response(200, text='not json'), 'delivery_unconfirmed'),
    (httpx.Response(200, json={'ok': False}), 'telegram_rejected'),
    (httpx.Response(200, json={'ok': True, 'result': {}}), 'delivery_unconfirmed'),
    (httpx.Response(200, json=[]), 'delivery_unconfirmed'),
])
def test_telegram_failure_no_retry(response, code):
    calls = []
    def handle(request):
        calls.append(request)
        return response
    with pytest.raises(ProviderError, match=code):
        asyncio.run(telegram(handle).send('Test', '123'))
    assert len(calls) == 1


def test_telegram_timeout_safe():
    def handle(request):
        raise httpx.ReadTimeout('fake_secret', request=request)
    with pytest.raises(ProviderError) as caught:
        asyncio.run(telegram(handle).send('Test', '123'))
    assert str(caught.value) == 'delivery_unconfirmed'


@pytest.mark.parametrize('message,destination', [('', '123'), ('a' * 4097, '123'),
    ('a\x00', '123'), ('\ud800', '123'), ('Test', '123/other'), ('Test', '')])
def test_telegram_invalid_input_no_network(message, destination):
    def handle(request):
        pytest.fail('Unexpected network request')
    with pytest.raises(ProviderError):
        asyncio.run(telegram(handle).send(message, destination))


def email_settings(mode='starttls'):
    return EmailSettings(host='smtp.invalid', port=587, tls_mode=mode, timeout=2,
                         sender='from@example.invalid', username='test', password='fake_secret')


@pytest.mark.parametrize('mode', ['starttls', 'ssl'])
def test_email_tls_thread_and_contract(monkeypatch, mode):
    connection = MagicMock()
    connection.send_message.return_value = {}
    main_thread = threading.get_ident()
    def connect(*args, **kwargs):
        assert threading.get_ident() != main_thread
        assert args == ('smtp.invalid', 587)
        assert kwargs['timeout'] == 2
        if mode == 'ssl':
            assert kwargs['context'].verify_mode == ssl.CERT_REQUIRED
            assert kwargs['context'].check_hostname
        return connection
    monkeypatch.setattr('app.alerts.email.smtplib.' + ('SMTP_SSL' if mode == 'ssl' else 'SMTP'), connect)
    asyncio.run(EmailProvider(email_settings(mode)).send('Alerta ç', 'to@example.invalid'))
    names = [c[0] for c in connection.method_calls]
    assert names == (['ehlo', 'starttls', 'ehlo'] if mode == 'starttls' else []) + ['login', 'send_message', 'close']
    if mode == 'starttls':
        context = connection.starttls.call_args.kwargs['context']
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    mail = connection.send_message.call_args.args[0]
    assert mail['To'] == 'to@example.invalid'
    assert mail.get_content().strip() == 'Alerta ç'


@pytest.mark.parametrize('stage,error,code', [
    ('starttls', smtplib.SMTPNotSupportedError('fake_secret'), 'delivery_unconfirmed'),
    ('login', smtplib.SMTPAuthenticationError(535, b'fake_secret'), 'email_rejected'),
    ('send_message', TimeoutError('fake_secret'), 'delivery_unconfirmed'),
    ('send_message', smtplib.SMTPDataError(550, b'fake_secret'), 'email_rejected'),
])
def test_email_errors_safe_and_no_retry(monkeypatch, stage, error, code):
    connection = MagicMock()
    getattr(connection, stage).side_effect = error
    monkeypatch.setattr('app.alerts.email.smtplib.SMTP', lambda *a, **k: connection)
    with pytest.raises(ProviderError) as caught:
        asyncio.run(EmailProvider(email_settings()).send('Test', 'to@example.invalid'))
    assert str(caught.value) == code
    assert connection.send_message.call_count <= 1
    connection.close.assert_called_once()
    if stage == 'starttls':
        connection.login.assert_not_called()
        connection.send_message.assert_not_called()


@pytest.mark.parametrize('accepted', [True, False])
def test_cleanup_preserves_delivery_outcome(monkeypatch, caplog, accepted):
    connection = MagicMock()
    connection.send_message.return_value = {} if accepted else {'to@example.invalid': (550, b'rejected')}
    connection.close.side_effect = OSError('fake_secret')
    monkeypatch.setattr('app.alerts.email.smtplib.SMTP', lambda *a, **k: connection)
    if accepted:
        asyncio.run(EmailProvider(email_settings()).send('Test', 'to@example.invalid'))
    else:
        with pytest.raises(ProviderError, match='email_rejected'):
            asyncio.run(EmailProvider(email_settings()).send('Test', 'to@example.invalid'))
    assert 'smtp_cleanup_failed' in caplog.text
    assert 'fake_secret' not in caplog.text


@pytest.mark.parametrize('message,destination', [('', 'a@b'), ('a\x00', 'a@b'),
    ('\ud800', 'a@b'), ('Test', 'a@b\r\nBcc:c@d'), ('Test', 'a@b,c@d')])
def test_email_invalid_input(monkeypatch, message, destination):
    def connect(*args, **kwargs):
        pytest.fail('Unexpected SMTP connection')
    monkeypatch.setattr('app.alerts.email.smtplib.SMTP', connect)
    with pytest.raises(ProviderError):
        asyncio.run(EmailProvider(email_settings()).send(message, destination))
