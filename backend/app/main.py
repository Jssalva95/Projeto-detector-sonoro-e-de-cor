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
from app.services.equipment import EquipmentError, NotFound, InactiveDevice

app = FastAPI(title="Machine Monitor")
app.include_router(router)
app.include_router(auth_router)
app.include_router(machines_router)
app.include_router(devices_router)
app.include_router(readings_router)
app.include_router(events_router)


@app.exception_handler(EquipmentError)
async def equipment_error(request: Request, error: EquipmentError) -> JSONResponse:
    status_code = 404 if isinstance(error, NotFound) else 403 if isinstance(error, InactiveDevice) else 409
    return JSONResponse(status_code=status_code, content={"detail": str(error)})


@app.exception_handler(RequestValidationError)
async def safe_auth_validation(request: Request, error: RequestValidationError) -> Response:
    if request.url.path.startswith("/api/v1/auth/"):
        # FastAPI's default errors echo input, including passwords and tokens.
        return JSONResponse(status_code=422, content={"detail": "Invalid authentication payload"})
    if request.url.path == "/api/v1/readings" and any(
        item["type"] == "finite_number" for item in error.errors()
    ):
        # Numeric JSON overflow (e.g. 1e309) becomes infinity in the parser.
        # Do not echo that non-JSON value in the validation error response.
        return JSONResponse(status_code=422, content={"detail": "Reading numbers must be finite"})
    if request.url.path == "/api/v1/events" and any(
        item["type"] == "finite_number" for item in error.errors()
    ):
        return JSONResponse(status_code=422, content={"detail": "Event numbers must be finite"})
    return await request_validation_exception_handler(request, error)
