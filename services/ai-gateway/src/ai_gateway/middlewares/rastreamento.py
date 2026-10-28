"""Middleware assíncrono para injeção de Request-ID, rastreamento OpenTelemetry e métricas Prometheus."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ai_gateway.dependencias import (
    obter_gerenciador_rastreamento,
    obter_metricas_prometheus,
)

logger = logging.getLogger("ai_gateway.acesso")


class MiddlewareRastreamento(BaseHTTPMiddleware):
    """Injeta identificador de correlação, span OpenTelemetry e registra métricas de tráfego."""

    def _obter_rota_normalizada(self, request: Request) -> str:
        """Extrai o template de rota registrado para evitar alta cardinalidade com IDs dinâmicos."""
        route = request.scope.get("route")
        if route and hasattr(route, "path") and route.path:
            return str(route.path)
        return request.url.path or "/"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        id_requisicao = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        inicio = time.monotonic()
        metodo = request.method.upper()
        caminho = request.url.path

        rastreador = obter_gerenciador_rastreamento()
        metricas = obter_metricas_prometheus()

        atributos_iniciais = {
            "http.method": metodo,
            "http.url": str(request.url),
            "http.target": caminho,
            "http.request_id": id_requisicao,
        }

        cabecalhos_w3c = {
            chave.lower(): valor
            for chave, valor in request.headers.items()
            if chave.lower() in ("traceparent", "tracestate")
        }

        traceparent_header: str | None = None

        async with rastreador.iniciar_span_assincrono(
            f"HTTP {metodo} {caminho}",
            atributos=atributos_iniciais,
            contexto_externo=cabecalhos_w3c,
        ) as span:
            traceparent_header = rastreador.obter_traceparent_w3c()

            try:
                response = await call_next(request)
            except Exception as erro:
                duracao = time.monotonic() - inicio
                rota_normalizada = self._obter_rota_normalizada(request)
                metricas.registrar_requisicao_http(
                    metodo, rota_normalizada, 500, duracao
                )
                logger.exception(
                    "Erro não tratado na requisição HTTP",
                    extra={
                        "request_id": id_requisicao,
                        "metodo": metodo,
                        "rota": rota_normalizada,
                        "status": 500,
                        "duracao_segundos": duracao,
                        "erro": str(erro),
                    },
                )
                raise

            duracao = time.monotonic() - inicio
            status_code = response.status_code
            rota_normalizada = self._obter_rota_normalizada(request)

            metricas.registrar_requisicao_http(
                metodo, rota_normalizada, status_code, duracao
            )

            if span.is_recording():
                span.set_attribute("http.status_code", status_code)
                span.set_attribute("http.duration_seconds", duracao)

            response.headers["X-Request-ID"] = id_requisicao
            response.headers["X-Process-Time"] = f"{duracao:.4f}"
            if traceparent_header:
                response.headers["traceparent"] = traceparent_header

            return response
