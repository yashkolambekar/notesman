from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

SAFE = {"GET", "HEAD", "OPTIONS"}


class OriginCheck(BaseHTTPMiddleware):
    """CSRF defence on top of SameSite=Lax: a state-changing request carrying our session
    cookie must come from our own origin."""

    def __init__(self, app, allowed_origin: str, cookie_name: str):
        super().__init__(app)
        self.allowed = allowed_origin
        self.cookie_name = cookie_name

    async def dispatch(self, request: Request, call_next):
        if request.method not in SAFE:
            origin = request.headers.get("origin")
            if origin is not None and origin != self.allowed:
                return JSONResponse({"detail": "Bad origin"}, status_code=403)
            if origin is None and self.cookie_name in request.cookies:
                return JSONResponse({"detail": "Origin header required"}, status_code=403)
        return await call_next(request)
