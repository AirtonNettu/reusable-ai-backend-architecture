"""Middleware de rastreamento com ID de correlação e medição de latência."""

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class MiddlewareRastreamento(BaseHTTPMiddleware):
    """Garante a injeção de identificador de correlação e tempo de processamento."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        id_requisicao = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        inicio = time.monotonic()

        response = await call_next(request)

        duracao = time.monotonic() - inicio
        response.headers["X-Request-ID"] = id_requisicao
        response.headers["X-Process-Time"] = f"{duracao:.4f}"

        return response
