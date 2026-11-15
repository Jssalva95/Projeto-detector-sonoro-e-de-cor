"""One externally visible attempt after a durable claim; never auto-retry."""

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
import logging

from sqlalchemy.orm import Session

from app.alerts.base import AlertProvider, ProviderError
from app.database.session import session_scope
from app.repositories import alert_delivery as repository

SessionFactory = Callable[[], AbstractContextManager[Session]]
SAFE_ERRORS = frozenset({'invalid_message', 'invalid_destination', 'invalid_email_input',
                         'telegram_rejected', 'email_rejected', 'delivery_unconfirmed',
                         'email_connection_failed', 'email_tls_failed', 'email_protocol_failed',
                         'email_auth_rejected', 'email_app_password_required',
                         'email_auth_unavailable', 'email_auth_connection_failed'})
logger = logging.getLogger(__name__)


async def deliver(providers: Mapping[str, AlertProvider], delivery: repository.Delivery) -> str | None:
    """Shared sanitized transport outcome; cancellation keeps the durable claim."""
    try:
        await providers[delivery.channel].send(delivery.message, delivery.destination)
    except ProviderError as failure:
        return str(failure) if str(failure) in SAFE_ERRORS else 'delivery_unconfirmed'
    except Exception:
        return 'delivery_unconfirmed'
    return None


async def process_one(providers: Mapping[str, AlertProvider],
                      sessions: SessionFactory = session_scope) -> bool:
    with sessions() as session:
        found, delivery = repository.reserve(session, tuple(providers))
    # The context above must have committed before any external side effect.
    if delivery is None:
        return found
    error = await deliver(providers, delivery)
    # Cancellation/process death is deliberately not caught: the durable marker
    # remains and prevents automatic redispatch after restart.
    with sessions() as session:
        repository.finish(session, delivery, error)
    logger.info('alert_result id=%s status=%s', delivery.identifier, 'SENT' if error is None else 'FAILED')
    return True
