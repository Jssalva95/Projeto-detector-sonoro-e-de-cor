"""Application assembly; routes and persistence live in separate modules."""

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.health import router
from app.api.auth import router as auth_router

app = FastAPI(title="Machine Monitor")
app.include_router(router)
app.include_router(auth_router)


@app.exception_handler(RequestValidationError)
async def safe_auth_validation(request: Request, error: RequestValidationError) -> Response:
    if request.url.path.startswith("/api/v1/auth/"):
        # FastAPI's default errors echo input, including passwords and tokens.
        return JSONResponse(status_code=422, content={"detail": "Invalid authentication payload"})
    return await request_validation_exception_handler(request, error)
