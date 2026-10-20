from fastapi import APIRouter, HTTPException

from app.schemas.health import HealthResponse
from app.services.availability import database_available

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@router.get("/ready", response_model=HealthResponse)
def ready() -> HealthResponse:
    if not database_available():
        raise HTTPException(status_code=503, detail="Database unavailable")
    return HealthResponse()
