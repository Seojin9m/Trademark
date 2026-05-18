"""Static app-token middleware — first line of defense for every /api/* route.

Every request must include the shared secret in ``X-App-Token`` (or
``app_token`` query param for SSE / EventSource paths that can't set headers).
The token is compared via ``secrets.compare_digest`` to dodge timing attacks.

This sits *above* per-user JWT auth. The JWT identifies the user; the app
token identifies the deployed frontend. Without the app token, even public
endpoints (rankings, market summary) would be open to anyone on the internet
who knows the URL, which would happily burn your Polygon / LLM quota.

Configured via env:
    APP_API_TOKEN              required; the shared secret
    APP_TOKEN_EXEMPT_PATHS     optional CSV of path prefixes that bypass the
                               check (defaults to docs + openapi). Use sparingly.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


_DEFAULT_EXEMPT = ("/docs", "/redoc", "/openapi.json")


def _exempt_paths() -> tuple[str, ...]:
    extra = os.getenv("APP_TOKEN_EXEMPT_PATHS", "")
    extras = tuple(p.strip() for p in extra.split(",") if p.strip())
    return _DEFAULT_EXEMPT + extras


class AppTokenMiddleware(BaseHTTPMiddleware):
    """Reject requests to /api/* that don't carry the shared app token.

    Token lookup order:
      1. ``X-App-Token`` header (preferred)
      2. ``app_token`` query string param (fallback for EventSource / SSE)
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only guard /api/* — the static asset routes and FastAPI docs
        # don't need to know about app tokens.
        if not path.startswith("/api"):
            return await call_next(request)

        for exempt in _exempt_paths():
            if path.startswith(exempt):
                return await call_next(request)

        expected = os.getenv("APP_API_TOKEN")
        if not expected:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "APP_API_TOKEN not configured on the backend. "
                             "Set it in backend/.env to enable app-token auth.",
                },
            )

        provided = (
            request.headers.get("x-app-token")
            or request.query_params.get("app_token")
            or ""
        )
        if not provided or not secrets.compare_digest(provided, expected):
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or invalid X-App-Token."},
            )

        return await call_next(request)
