"""SMTP in a worker thread; explicit verified TLS and no automatic retries."""

import asyncio
from collections.abc import Callable
import logging
from email.message import EmailMessage
import smtplib
import ssl

from app.alerts.base import ProviderError
from app.alerts.config import EmailSettings, mailbox


def _auth_error(error: smtplib.SMTPAuthenticationError) -> str:
    # Inspect only to classify; never expose or retain the server's free text.
    if error.smtp_code == 534 and b'application-specific password' in error.smtp_error.lower():
        return 'email_app_password_required'
    return 'email_auth_rejected'


class _AuthenticationDiagnostics:
    """Keep smtplib negotiation, but preserve its first rejection on failure."""

    _first_auth_error: str | None = None

    def auth(self, mechanism: str, authobject: Callable[..., str | None],
             *, initial_response_ok: bool = True) -> tuple[int, bytes]:
        try:
            return super().auth(mechanism, authobject, initial_response_ok=initial_response_ok)
        except smtplib.SMTPAuthenticationError as error:
            if self._first_auth_error is None:
                self._first_auth_error = _auth_error(error)
            raise

    def login(self, user: str, password: str, *, initial_response_ok: bool = True) -> tuple[int, bytes]:
        self._first_auth_error = None
        try:
            self.ehlo_or_helo_if_needed()
            advertised = self.esmtp_features.get('auth', '').split()
            # These are the mechanisms implemented by Python 3.11 smtplib.
            if not any(method in advertised for method in ('CRAM-MD5', 'PLAIN', 'LOGIN')):
                raise smtplib.SMTPNotSupportedError('No compatible SMTP authentication')
            return super().login(user, password, initial_response_ok=initial_response_ok)
        except (smtplib.SMTPException, OSError, ValueError, UnicodeError):
            if self._first_auth_error is not None:
                raise ProviderError(self._first_auth_error) from None
            raise
        finally:
            self._first_auth_error = None


class _SMTP(_AuthenticationDiagnostics, smtplib.SMTP):
    pass


class _SMTP_SSL(_AuthenticationDiagnostics, smtplib.SMTP_SSL):
    pass


def _ehlo(connection: smtplib.SMTP) -> None:
    code, reply = connection.ehlo()
    if code != 250:
        raise smtplib.SMTPHeloError(code, reply)


class EmailProvider:
    def __init__(self, settings: EmailSettings):
        self.settings = settings

    async def send(self, message: str, destination: str) -> None:
        try:
            mailbox(destination)
            if not message or '\x00' in message:
                raise ValueError
            message.encode('utf-8')
        except (ValueError, UnicodeError):
            raise ProviderError('invalid_email_input') from None
        await asyncio.to_thread(self._send, message, destination)

    def _send(self, message: str, destination: str) -> None:
        mail = EmailMessage()
        mail['From'] = self.settings.sender
        mail['To'] = destination
        mail['Subject'] = 'Machine Monitor — alerta'
        mail.set_content(message)
        connection: smtplib.SMTP | None = None
        stage = 'email_connection_failed'
        try:
            context = ssl.create_default_context()
            if self.settings.tls_mode == 'ssl':
                connection = _SMTP_SSL(self.settings.host, self.settings.port,
                                             timeout=self.settings.timeout, context=context)
            else:
                connection = _SMTP(self.settings.host, self.settings.port, timeout=self.settings.timeout)
                stage = 'email_protocol_failed'
                _ehlo(connection)
                stage = 'email_tls_failed'
                connection.starttls(context=context)
            stage = 'email_protocol_failed'
            _ehlo(connection)
            if self.settings.username:
                stage = 'email_auth_connection_failed'
                connection.login(self.settings.username, self.settings.password.get_secret_value())
            stage = 'delivery_unconfirmed'
            refused = connection.send_message(mail, from_addr=self.settings.sender, to_addrs=[destination])
            if refused:
                raise ProviderError('email_rejected')
        except smtplib.SMTPAuthenticationError as error:
            raise ProviderError(_auth_error(error)) from None
        except smtplib.SMTPNotSupportedError:
            code = 'email_auth_unavailable' if stage == 'email_auth_connection_failed' else stage
            raise ProviderError(code) from None
        except smtplib.SMTPRecipientsRefused:
            raise ProviderError('email_rejected') from None
        except smtplib.SMTPResponseException:
            code = 'email_rejected' if stage == 'delivery_unconfirmed' else stage
            raise ProviderError(code) from None
        except ssl.SSLError:
            code = 'delivery_unconfirmed' if stage == 'delivery_unconfirmed' else 'email_tls_failed'
            raise ProviderError(code) from None
        except (smtplib.SMTPException, OSError, ValueError, UnicodeError):
            raise ProviderError(stage) from None
        finally:
            # No QUIT round trip after acceptance: failure there must not invite a retry.
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    # Preserve the delivery outcome; never log server/exception text.
                    logging.getLogger(__name__).warning('smtp_cleanup_failed')
