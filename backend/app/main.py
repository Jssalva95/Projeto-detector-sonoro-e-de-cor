"""Application assembly; routes and persistence live in separate modules."""

from fastapi import FastAPI

from app.api.health import router

app = FastAPI(title="Machine Monitor")
app.include_router(router)
