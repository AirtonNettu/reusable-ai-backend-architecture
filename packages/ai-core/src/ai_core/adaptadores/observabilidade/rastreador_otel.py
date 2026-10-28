"""Gerenciador de rastreamento distribuído com OpenTelemetry e exportação OTLP resiliente."""

import logging
import os
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import (
    TraceContextTextMapPropagator,
)

logger = logging.getLogger("ai_core.observabilidade.otel")


class ExportadorSpansMemoria(SpanExporter):
    """Exportador em memória seguro para inspeção, testes e execução sem collector externo."""

    def __init__(self) -> None:
        self._spans: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def obter_spans_finalizados(self) -> tuple[ReadableSpan, ...]:
        return tuple(self._spans)

    def limpar(self) -> None:
        self._spans.clear()


class GerenciadorRastreamento:
    """Configura e provê instrumentação distribuída OpenTelemetry sem expor dados sensíveis."""

    def __init__(
        self,
        nome_servico: str = "ai-gateway",
        habilitado: bool = True,
        endpoint_otlp: str | None = None,
        exportador_customizado: SpanExporter | None = None,
    ) -> None:
        self._habilitado = habilitado
        self._nome_servico = nome_servico
        self._endpoint_otlp = endpoint_otlp or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        self._exportador_memoria: ExportadorSpansMemoria | None = None
        self._propagador_w3c = TraceContextTextMapPropagator()

        if not self._habilitado:
            self._tracer = trace.get_tracer("noop")
            return

        recurso = Resource.create({"service.name": self._nome_servico})
        self._provider = TracerProvider(resource=recurso)

        if exportador_customizado is not None:
            self._provider.add_span_processor(
                SimpleSpanProcessor(exportador_customizado)
            )
        elif self._endpoint_otlp:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                otlp_exporter = OTLPSpanExporter(endpoint=self._endpoint_otlp)
                self._provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
                logger.info(
                    "Exportador OTLP configurado com sucesso para %s",
                    self._endpoint_otlp,
                )
            except Exception as erro:  # noqa: BLE001
                logger.warning(
                    "Falha ao inicializar OTLPSpanExporter (%s). Utilizando ExportadorSpansMemoria como fallback.",
                    erro,
                )
                self._exportador_memoria = ExportadorSpansMemoria()
                self._provider.add_span_processor(
                    SimpleSpanProcessor(self._exportador_memoria)
                )
        else:
            # Padrão: mantemos em memória sem risco de exceções de rede externas
            self._exportador_memoria = ExportadorSpansMemoria()
            self._provider.add_span_processor(
                SimpleSpanProcessor(self._exportador_memoria)
            )

        self._tracer = self._provider.get_tracer(self._nome_servico)

    @property
    def exportador_memoria(self) -> ExportadorSpansMemoria | None:
        """Acesso aos spans gravados em memória para inspeção e testes."""
        return self._exportador_memoria

    def obter_trace_e_span_id_atuais(self) -> tuple[str | None, str | None]:
        """Recupera o trace_id e span_id ativos no contexto de execução formatados em hexadecimal."""
        span_atual = trace.get_current_span()
        contexto = span_atual.get_span_context()
        if contexto and contexto.is_valid:
            trace_id_hex = f"{contexto.trace_id:032x}"
            span_id_hex = f"{contexto.span_id:016x}"
            return trace_id_hex, span_id_hex
        return None, None

    def obter_traceparent_w3c(self) -> str | None:
        """Retorna o cabeçalho no padrão W3C traceparent (ex: 00-traceid-spanid-01)."""
        trace_id, span_id = self.obter_trace_e_span_id_atuais()
        if trace_id and span_id:
            return f"00-{trace_id}-{span_id}-01"
        return None

    def _extrair_contexto_remoto(self, contexto_externo: dict[str, str] | None) -> Any:
        """Extrai o contexto W3C se presente nos cabeçalhos externos informados."""
        if not contexto_externo:
            return None
        try:
            return self._propagador_w3c.extract(carrier=contexto_externo)
        except Exception:  # noqa: BLE001
            return None

    @contextmanager
    def iniciar_span(
        self,
        nome_operacao: str,
        atributos: dict[str, Any] | None = None,
        contexto_externo: dict[str, str] | None = None,
    ) -> Iterator[Span]:
        """Inicia um span síncrono sanitizado, propagando o contexto W3C externo se fornecido."""
        if not self._habilitado:
            yield trace.INVALID_SPAN
            return

        ctx_remoto = self._extrair_contexto_remoto(contexto_externo)
        atributos_sanitizados = self._sanitizar_atributos(atributos or {})
        with self._tracer.start_as_current_span(
            nome_operacao, context=ctx_remoto, attributes=atributos_sanitizados
        ) as span:
            try:
                yield span
            except Exception as erro:
                span.set_status(Status(StatusCode.ERROR, str(erro)))
                span.set_attribute("error.type", type(erro).__name__)
                raise

    @asynccontextmanager
    async def iniciar_span_assincrono(
        self,
        nome_operacao: str,
        atributos: dict[str, Any] | None = None,
        contexto_externo: dict[str, str] | None = None,
    ) -> AsyncIterator[Span]:
        """Inicia um span assíncrono gerenciado, propagando o contexto W3C externo se fornecido."""
        if not self._habilitado:
            yield trace.INVALID_SPAN
            return

        ctx_remoto = self._extrair_contexto_remoto(contexto_externo)
        atributos_sanitizados = self._sanitizar_atributos(atributos or {})
        with self._tracer.start_as_current_span(
            nome_operacao, context=ctx_remoto, attributes=atributos_sanitizados
        ) as span:
            try:
                yield span
            except Exception as erro:
                span.set_status(Status(StatusCode.ERROR, str(erro)))
                span.set_attribute("error.type", type(erro).__name__)
                raise

    def _sanitizar_atributos(self, atributos: dict[str, Any]) -> dict[str, Any]:
        """Filtra atributos garantindo que prompts, respostas ou tokens sensíveis não sejam indexados."""
        atributos_seguros: dict[str, Any] = {}
        chaves_proibidas = {
            "prompt",
            "resposta",
            "texto",
            "conteudo",
            "mensagens",
            "authorization",
            "api_key",
            "senha",
            "secret",
        }

        for chave, valor in atributos.items():
            chave_lower = chave.lower()
            if any(termo in chave_lower for termo in chaves_proibidas):
                continue
            if chave_lower in (
                "token",
                "auth_token",
                "access_token",
                "bearer_token",
            ) or chave_lower.startswith("token_"):
                continue
            if isinstance(valor, (str, int, float, bool)):
                atributos_seguros[chave] = valor
            else:
                atributos_seguros[chave] = str(valor)

        return atributos_seguros


# Instância global padrão de rastreamento para uso do sistema
rastreador_global = GerenciadorRastreamento()
