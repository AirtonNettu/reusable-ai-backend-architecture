"""Gerenciador de rastreamento distribuído com OpenTelemetry e exportação OTLP resiliente."""

import collections
import logging
import os
import threading
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

from ai_core.adaptadores.observabilidade.formatador_logs import (
    sanitizar_mensagem_erro,
)

logger = logging.getLogger("ai_core.observabilidade.otel")


class ExportadorSpansMemoria(SpanExporter):
    """Exportador em memória thread-safe com retenção limitada para testes e fallback local."""

    def __init__(self, capacidade_maxima: int = 1000) -> None:
        self._capacidade_maxima = capacidade_maxima
        self._spans: collections.deque[ReadableSpan] = collections.deque(
            maxlen=capacidade_maxima
        )
        self._trava = threading.Lock()

    @property
    def capacidade_maxima(self) -> int:
        """Capacidade máxima de retenção de spans em memória."""
        return self._capacidade_maxima

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._trava:
            for s in spans:
                self._spans.append(s)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def obter_spans_finalizados(self) -> tuple[ReadableSpan, ...]:
        with self._trava:
            return tuple(self._spans)

    def quantidade_spans(self) -> int:
        with self._trava:
            return len(self._spans)

    def limpar(self) -> None:
        with self._trava:
            self._spans.clear()


class GerenciadorRastreamento:
    """Configura e provê instrumentação distribuída OpenTelemetry sem expor dados sensíveis."""

    def __init__(
        self,
        nome_servico: str = "ai-gateway",
        habilitado: bool = True,
        endpoint_otlp: str | None = None,
        exportador_customizado: SpanExporter | None = None,
        capacidade_memoria: int = 1000,
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
                self._exportador_memoria = ExportadorSpansMemoria(
                    capacidade_maxima=capacidade_memoria
                )
                self._provider.add_span_processor(
                    SimpleSpanProcessor(self._exportador_memoria)
                )
        else:
            # Padrão: mantemos em memória sem risco de exceções de rede externas
            self._exportador_memoria = ExportadorSpansMemoria(
                capacidade_maxima=capacidade_memoria
            )
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
        """Retorna o cabeçalho no padrão W3C traceparent respeitando as flags reais do span ativo."""
        # 1. Utiliza injeção oficial do propagador W3C do OpenTelemetry
        carrier: dict[str, str] = {}
        try:
            self._propagador_w3c.inject(carrier)
            if "traceparent" in carrier:
                return carrier["traceparent"]
        except Exception:  # noqa: BLE001, S110
            pass

        # 2. Fallback de formatação com as flags reais do contexto
        span_atual = trace.get_current_span()
        contexto = span_atual.get_span_context()
        if contexto and contexto.is_valid:
            trace_id_hex = f"{contexto.trace_id:032x}"
            span_id_hex = f"{contexto.span_id:016x}"
            flags_hex = f"{contexto.trace_flags:02x}"
            return f"00-{trace_id_hex}-{span_id_hex}-{flags_hex}"
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
        span = self._tracer.start_span(
            nome_operacao, context=ctx_remoto, attributes=atributos_sanitizados
        )
        token = trace.use_span(span, end_on_exit=False)
        try:
            with token:
                yield span
        except Exception as erro:
            msg_sanitizada = sanitizar_mensagem_erro(str(erro))
            span.set_status(
                Status(StatusCode.ERROR, f"{type(erro).__name__}: {msg_sanitizada}")
            )
            span.set_attribute("error.type", type(erro).__name__)
            span.set_attribute("error.message", msg_sanitizada)
            raise
        finally:
            span.end()

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
        span = self._tracer.start_span(
            nome_operacao, context=ctx_remoto, attributes=atributos_sanitizados
        )
        token = trace.use_span(span, end_on_exit=False)
        try:
            with token:
                yield span
        except Exception as erro:
            msg_sanitizada = sanitizar_mensagem_erro(str(erro))
            span.set_status(
                Status(StatusCode.ERROR, f"{type(erro).__name__}: {msg_sanitizada}")
            )
            span.set_attribute("error.type", type(erro).__name__)
            span.set_attribute("error.message", msg_sanitizada)
            raise
        finally:
            span.end()

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
