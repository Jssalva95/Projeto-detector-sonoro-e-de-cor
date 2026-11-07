"""Separate opt-in process: python -m app.alerts.worker [--once]."""

import argparse
import asyncio
import logging
import signal

from sqlalchemy import select

from app.alerts.config import poll_interval
from app.alerts.providers import configured_providers
from app.database.session import session_scope
from app.models import Alert
from app.services.alert_delivery import process_one

logger = logging.getLogger(__name__)


async def run(once: bool = False) -> None:
    interval = poll_interval()
    providers = configured_providers()
    # Fail before delivery if the migration/database is unavailable.
    with session_scope() as session:
        session.execute(select(Alert.attempt_started_at).limit(0))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Wake the selector immediately, also with signal.signal on Windows;
        # setting Event directly can leave an idle selector asleep until poll.
        previous[sig] = signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    logger.info('alert_worker_ready channels=%s', ','.join(sorted(providers)) or 'none')
    try:
        while not stop.is_set():
            worked = await process_one(providers)
            if once:
                return
            # An async function need not suspend (e.g. an ineligible alert).
            # Let queued signal callbacks run before reserving the next item,
            # without adding polling delay or interrupting the current attempt.
            await asyncio.sleep(0)
            if not worked:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except TimeoutError:
                    pass  # Expected idle polling, not a delivery retry.
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Process at most one unstarted alert')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        asyncio.run(run(args.once))
    except KeyboardInterrupt:
        return 0
    except Exception:
        # Stop on operational failure (including result-commit failure). Never
        # expose DB/provider/config exception text or resume an uncertain send.
        logger.error('alert_worker_stopped operational_failure')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
