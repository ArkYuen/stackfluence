from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        if "server" in response.headers:
            del response.headers["server"]
        if "X-Powered-By" in response.headers:
            del response.headers["X-Powered-By"]

        path = request.url.path

        if path.startswith("/v1/") or path.startswith("/c/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        if path.startswith("/c/"):
            response.headers["Referrer-Policy"] = "no-referrer"
        else:
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        response.headers["X-Frame-Options"] = "DENY"
        # Only set CSP if the response doesn't already have one (e.g. collector sets nonce-based CSP)
        if "Content-Security-Policy" not in response.headers:
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response