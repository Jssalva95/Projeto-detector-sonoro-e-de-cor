"""SMTP in a worker thread; explicit verified TLS and no automatic retries."""

import asyncio
import logging
from email.message import EmailMessage
import smtplib
import ssl

from app.alerts.base import ProviderError
from app.alerts.config import EmailSettings, mailbox


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
        try:
            context = ssl.create_default_context()
            if self.settings.tls_mode == 'ssl':
                connection = smtplib.SMTP_SSL(self.settings.host, self.settings.port,
                                             timeout=self.settings.timeout, context=context)
            else:
                connection = smtplib.SMTP(self.settings.host, self.settings.port, timeout=self.settings.timeout)
                connection.ehlo()
                connection.starttls(context=context)
                connection.ehlo()
            if self.settings.username:
                connection.login(self.settings.username, self.settings.password.get_secret_value())
            refused = connection.send_message(mail, from_addr=self.settings.sender, to_addrs=[destination])
            if refused:
                raise ProviderError('email_rejected')
        except smtplib.SMTPResponseException:
            raise ProviderError('email_rejected') from None
        except (smtplib.SMTPException, OSError, ValueError, UnicodeError):
            raise ProviderError('delivery_unconfirmed') from None
        finally:
            # No QUIT round trip after acceptance: failure there must not invite a retry.
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    # Preserve the delivery outcome; never log server/exception text.
                    logging.getLogger(__name__).warning('smtp_cleanup_failed')
