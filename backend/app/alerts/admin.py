"""Manual host-admin CLI; no credentials, recipients or alerts are auto-seeded."""

import argparse
import json

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.session import DatabaseConfigurationError, session_scope
from app.models import Alert, AlertRecipient
from app.services.alert_admin import AlertAdminError, add_recipient, retry, set_active


def positive(value: str) -> int:
    try:
        parsed = int(value)
        if not 0 < parsed <= 9223372036854775807:
            raise ValueError
        return parsed
    except ValueError:
        raise argparse.ArgumentTypeError('Expected a positive BIGINT') from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add-recipient')
    add.add_argument('--name', required=True)
    add.add_argument('--channel', choices=['EMAIL', 'TELEGRAM'], required=True)
    add.add_argument('--destination', required=True)
    for command in ('activate-recipient', 'deactivate-recipient'):
        commands.add_parser(command).add_argument('id', type=positive)
    for command in ('list-recipients', 'list-alerts'):
        commands.add_parser(command).add_argument('--limit', type=positive, required=True)
    retry_parser = commands.add_parser('retry')
    retry_parser.add_argument('id', type=positive)
    retry_parser.add_argument('--accept-duplicate-risk', action='store_true')
    retry_parser.add_argument('--workers-stopped', action='store_true')
    args = parser.parse_args()
    try:
        with session_scope() as session:
            if args.command == 'add-recipient':
                result = {'recipient_id': add_recipient(session, args.name, args.channel, args.destination).id}
            elif args.command in ('activate-recipient', 'deactivate-recipient'):
                set_active(session, args.id, args.command == 'activate-recipient')
                result = {'recipient_id': args.id, 'updated': True}
            elif args.command == 'retry':
                row = retry(session, args.id, accept_duplicate_risk=args.accept_duplicate_risk,
                            workers_stopped=args.workers_stopped)
                result = {'alert_id': row.id, 'previous_alert_id': args.id}
            elif args.command == 'list-recipients':
                result = [{'id': r.id, 'name': r.name, 'channel': r.channel, 'active': r.is_active}
                          for r in session.scalars(select(AlertRecipient).order_by(AlertRecipient.id).limit(args.limit))]
            else:
                result = [{'id': r.id, 'event_id': r.event_id, 'recipient_id': r.recipient_id,
                           'channel': r.channel, 'status': r.status,
                           'attempt_started_at': r.attempt_started_at.isoformat() if r.attempt_started_at else None}
                          for r in session.scalars(select(Alert).order_by(Alert.id.desc()).limit(args.limit))]
        print(json.dumps(result, ensure_ascii=True))  # Only after successful commit.
    except AlertAdminError as error:
        print(str(error))  # Service errors are fixed codes, never user input.
        return 1
    except (SQLAlchemyError, DatabaseConfigurationError):
        print('database_operation_failed')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
