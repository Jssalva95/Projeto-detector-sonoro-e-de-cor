"""Minimal application for the bootstrap phase."""

from fastapi import FastAPI, HTTPException

from app.database.connection import check_database

app = FastAPI(title="Machine Monitor")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    if not check_database():
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok"}
