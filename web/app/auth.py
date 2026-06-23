from __future__ import annotations

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

API_KEY = os.getenv("SAI_API_KEY", "")

_EXEMPT_PATHS = frozenset({"/", "/health", "/api/servers"})


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not API_KEY:
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in _EXEMPT_PATHS or path.startswith("/static"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key", "")

        if hmac.compare_digest(auth_header, f"Bearer {API_KEY}") or hmac.compare_digest(api_key_header, API_KEY):
            return await call_next(request)

        return JSONResponse({"error": "Unauthorized", "hint": "Set Authorization: Bearer <key> or X-API-Key header"}, status_code=401)
