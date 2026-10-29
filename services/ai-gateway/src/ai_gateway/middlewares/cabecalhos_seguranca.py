"""Middleware de segurança para injeção de cabeçalhos HTTP defensivos padronizados (SEC-005)."""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class MiddlewareCabecalhosSeguranca(BaseHTTPMiddleware):
    """Injeta cabeçalhos defensivos recomendados pela OWASP."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)

        # Prevenção de MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevenção de Clickjacking / enquadramento não autorizado
        response.headers["X-Frame-Options"] = "DENY"

        # Política de Referrer defensiva
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # HSTS injetado estritamente em conexões HTTPS
        eh_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").lower() == "https"
        )
        if eh_https:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Content-Security-Policy (CSP) estrito para a interface web do piloto (SEC-005 e SEC-009)
        if request.url.path.startswith("/piloto"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none';"
            )

        return response
