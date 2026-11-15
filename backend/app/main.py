"""Application assembly; routes and persistence live in separate modules."""

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.health import router
from app.api.auth import router as auth_router
from app.api.machines import router as machines_router
from app.api.devices import router as devices_router
from app.api.readings import router as readings_router
from app.api.events import router as events_router
from app.api.websocket import router as websocket_router
from app.api.dashboard import router as dashboard_router
from app.api.alert_admin import router as alert_admin_router
from app.api.alert_tests import router as alert_tests_router
from app.services.alert_tests import CooldownActive, RequesterDenied
from app.services.alert_admin import AlertAdminError, AlertAdminNotFound, AlertAdminConflict
from app.services.equipment import EquipmentError, NotFound, InactiveDevice
from app.alerts.config import AlertConfigurationError

app = FastAPI(title="Machine Monitor")
app.include_router(router)
app.include_router(auth_router)
app.include_router(machines_router)
app.include_router(devices_router)
app.include_router(readings_router)
app.include_router(events_router)
app.include_router(websocket_router)
app.include_router(dashboard_router)
app.include_router(alert_admin_router)
app.include_router(alert_tests_router)


@app.exception_handler(CooldownActive)
async def test_cooldown_error(request: Request, error: CooldownActive) -> JSONResponse:
    return JSONResponse(status_code=429, content={'detail': 'test_cooldown_active'},
                        headers={'Retry-After': str(error.retry_after), 'Cache-Control': 'no-store'})


@app.exception_handler(RequesterDenied)
async def test_requester_error(request: Request, error: RequesterDenied) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={'detail': 'requester_not_authorized'},
                        headers={'Cache-Control': 'no-store'})


@app.exception_handler(AlertAdminError)
async def alert_admin_error(request: Request, error: AlertAdminError) -> JSONResponse:
    status_code = 404 if isinstance(error, AlertAdminNotFound) else 409 if isinstance(error, AlertAdminConflict) else 422
    return JSONResponse(status_code=status_code, content={'detail': str(error)}, headers={'Cache-Control': 'no-store'})


@app.exception_handler(AlertConfigurationError)
async def alert_configuration_error(request: Request, error: AlertConfigurationError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Alert configuration unavailable"})


@app.exception_handler(EquipmentError)
async def equipment_error(request: Request, error: EquipmentError) -> JSONResponse:
    status_code = 404 if isinstance(error, NotFound) else 403 if isinstance(error, InactiveDevice) else 409
    return JSONResponse(status_code=status_code, content={"detail": str(error)})


@app.exception_handler(RequestValidationError)
async def safe_auth_validation(request: Request, error: RequestValidationError) -> Response:
    if request.url.path.startswith(('/api/v1/alert-recipients', '/api/v1/alerts', '/api/v1/alert-tests', '/api/v1/settings')):
        # Recipient destinations and unexpected input must not be echoed.
        return JSONResponse(status_code=422, content={'detail': 'Invalid administrative input'},
                            headers={'Cache-Control': 'no-store'})
    if request.url.path.startswith("/api/v1/auth/"):
        # FastAPI's default errors echo input, including passwords and tokens.
        return JSONResponse(status_code=422, content={"detail": "Invalid authentication payload"})
    if request.url.path == "/api/v1/readings" and any(
        item["type"] == "finite_number" for item in error.errors()
    ):
        # Numeric JSON overflow (e.g. 1e309) becomes infinity in the parser.
        # Do not echo that non-JSON value in the validation error response.
        return JSONResponse(status_code=422, content={"detail": "Reading numbers must be finite"})
    if (request.url.path == "/api/v1/events" or request.url.path.startswith("/api/v1/events/")
            or request.url.path.startswith("/api/v1/dashboard/")):
        # Input and ctx can contain infinity or exception objects. Return only
        # diagnostic metadata, independent of the validation error category.
        details = [{key: item[key] for key in ("loc", "type", "msg")} for item in error.errors()]
        return JSONResponse(status_code=422, content={"detail": details})
    return await request_validation_exception_handler(request, error)
