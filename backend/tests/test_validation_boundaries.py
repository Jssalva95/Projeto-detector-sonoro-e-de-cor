"""Regression coverage for the three approved Phase 5 validation corrections."""

import json
from datetime import timedelta

import pytest
from pydantic import TypeAdapter
from sqlalchemy import func, select

from app.models import Event, SensorReading
from app.schemas.domain import UtcDateTime
from test_auth import settings, user
from test_domain import db
from test_equipment import KEY, admin, client, device, machine
from test_events import payload
from test_readings import payload as make_reading_payload

EXTREMES = ['0001-01-01T00:00:00+14:00', '9999-12-31T23:59:59-14:00']
HEADERS = {'X-API-Key': KEY}


@pytest.mark.parametrize('value', EXTREMES)
@pytest.mark.parametrize('field', ['started_at', 'ended_at'])
def test_event_utc_overflow_no_write_then_valid(client, db, payload, field, value):
    response = client.post('/api/v1/events', headers=HEADERS, json=payload | {field: value})
    assert response.status_code == 422
    assert response.json()['detail'][0]['loc'] == ['body', field]
    assert db.scalar(select(func.count()).select_from(Event)) == 0
    assert client.post('/api/v1/events', headers=HEADERS, json=payload).status_code == 201


@pytest.mark.parametrize('value', EXTREMES)
@pytest.mark.parametrize('field', ['start_date', 'end_date'])
@pytest.mark.parametrize('path', ['/api/v1/events', '/api/v1/readings'])
def test_filter_utc_overflow_then_valid(client, admin, path, field, value):
    assert client.get(path, headers=admin, params={field: value}).status_code == 422
    assert client.get(path, headers=admin, params={field: '2026-10-22T08:00:00-04:00'}).status_code == 200


@pytest.mark.parametrize('value', EXTREMES)
def test_reading_utc_overflow_no_write_then_valid(client, db, machine, device, value):
    payload = make_reading_payload.__wrapped__(machine, device)
    response = client.post('/api/v1/readings', headers=HEADERS, json=payload | {'timestamp': value})
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(SensorReading)) == 0
    valid = client.post('/api/v1/readings', headers=HEADERS, json=payload)
    assert valid.status_code == 201
    assert valid.json()['timestamp'] == '2026-10-20T12:00:00Z'


def test_message_nul_rejected_without_rewriting_valid_text(client, db, payload):
    response = client.post('/api/v1/events', headers=HEADERS, json=payload | {'message': 'antes\x00depois'})
    assert response.status_code == 422
    assert response.json()['detail'][0]['loc'] == ['body', 'message']
    assert db.scalar(select(func.count()).select_from(Event)) == 0
    message = 'Atenção: máquina — 🔔\nSegunda linha\tcom tabulação'
    valid = client.post('/api/v1/events', headers=HEADERS, json=payload | {'message': message})
    assert valid.status_code == 201 and valid.json()['message'] == message
    assert db.get(Event, valid.json()['id']).message == message


@pytest.mark.parametrize('field', ['event_type', 'unexpected', 'sound_amplitude', 'message'])
def test_validation_json_safe_for_all_error_categories(client, db, payload, field):
    body = json.dumps(payload | {field: 'overflow'}).replace('"overflow"', '1e309')
    response = client.post('/api/v1/events', headers=HEADERS | {'Content-Type': 'application/json'}, content=body)
    assert response.status_code == 422
    errors = response.json()['detail']
    assert errors and errors[0]['loc'] == ['body', field]
    assert all(set(error) == {'loc', 'type', 'msg'} for error in errors)
    json.dumps(response.json(), allow_nan=False)
    assert db.scalar(select(func.count()).select_from(Event)) == 0
    assert client.post('/api/v1/events', headers=HEADERS, json=payload).status_code == 201


@pytest.mark.parametrize('value', ['0001-01-01T00:00:00Z', '9999-12-31T23:59:59Z',
                                  '0001-01-01T14:00:00+14:00', '9999-12-31T09:59:59-14:00'])
def test_representable_utc_boundaries_remain_valid(value):
    assert TypeAdapter(UtcDateTime).validate_python(value).utcoffset() == timedelta(0)
