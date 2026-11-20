"""Explicit HTTP browser origins, independent of WebSocket configuration."""

import json
import os
from urllib.parse import urlsplit

from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp


def cors_origins() -> list[str]:
    try:
        origins = json.loads(os.environ.get("CORS_ALLOWED_ORIGINS", ""))
        if not isinstance(origins, list) or not origins:
            raise ValueError
        for origin in origins:
            if not isinstance(origin, str) or any(char.isspace() for char in origin):
                raise ValueError
            parts = urlsplit(origin)
            if (parts.scheme not in ("http", "https") or not parts.hostname
                    or parts.username is not None or parts.password is not None
                    or parts.path or parts.query or parts.fragment or "*" in origin
                    or parts.port == 0 or origin.endswith(":")
                    or origin != f"{parts.scheme}://{parts.netloc}"):
                raise ValueError
        return list(dict.fromkeys(origins))
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Invalid or missing CORS configuration") from None


class ConfiguredCORSMiddleware(CORSMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(
            app, allow_origins=cors_origins(), allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Protection"],
            expose_headers=["Retry-After"],
        )
