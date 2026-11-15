"""Test delivery after durable reservation, without automatic retry."""

from collections.abc import Mapping
import logging

from app.alerts.base import AlertProvider
from app.database.session import session_scope
from app.repositories import alert_tests as repository
from app.services.alert_delivery import SessionFactory, deliver

logger = logging.getLogger(__name__)


async def process_one(providers: Mapping[str, AlertProvider], sessions: SessionFactory = session_scope) -> bool:
    with sessions() as session:
        found, delivery = repository.reserve(session, tuple(providers))
    if delivery is None:
        return found
    error = await deliver(providers, delivery)
    with sessions() as session:
        repository.finish(session, delivery, error)
    logger.info('alert_test_result id=%s status=%s', delivery.identifier, 'SENT' if error is None else 'FAILED')
    return True
