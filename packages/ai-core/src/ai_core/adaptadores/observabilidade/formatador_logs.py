"""Formatador de logs estruturados em JSON com sanitização automática de credenciais e correlação com traces."""

import datetime
import json
import logging
import re
from typing import Any

from opentelemetry import trace

from ai_core.adaptadores.seguranca.cofre_credenciais import CofreCredenciais

TERMOS_SENSIVEIS = {
    "chave_api",
    "api_key",
    "token",
    "authorization",
    "password",
    "senha",
    "secret",
    "segredo",
    "bearer",
    "x-api-key",
}

PADROES_REGEX_SENSIVEIS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE), "[CREDENTIAL_REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}", re.IGNORECASE), "[CREDENTIAL_REDACTED]"),
    (re.compile(r"AIza[A-Za-z0-9_\-]{10,}", re.IGNORECASE), "[CREDENTIAL_REDACTED]"),
    (
        re.compile(
            r"(api_key|token|password|senha|secret|segredo)=([^&\s]+)",
            re.IGNORECASE,
        ),
        r"\1=[CREDENTIAL_REDACTED]",
    ),
]


def sanitizar_mensagem_erro(
    mensagem: str | None,
    limite_caracteres: int = 500,
    tamanho_maximo: int | None = None,
) -> str:
    """Sanitiza mensagens de erro ou logs removendo padrões de credenciais e tokens sensíveis."""
    if not mensagem:
        return ""
    limite = tamanho_maximo if tamanho_maximo is not None else limite_caracteres
    texto = str(mensagem)
    for padrao, substituicao in PADROES_REGEX_SENSIVEIS:
        texto = padrao.sub(substituicao, texto)
    if len(texto) > limite:
        texto = texto[:limite] + " [TRUNCADO]"
    return texto


class FormatadorLogJson(logging.Formatter):
    """Formata registros de log em formato JSON seguro e correlacionado com OpenTelemetry e Request-ID."""

    def __init__(self, servico: str = "ai-backend") -> None:
        super().__init__()
        self._servico = servico

    def _sanitizar_texto(self, texto: str) -> str:
        """Substitui padrões detectados de tokens conhecidos por marcadores seguros."""
        return sanitizar_mensagem_erro(texto)

    def _sanitizar_valor(self, chave: str, valor: Any) -> Any:
        """Mascara o valor caso a chave indique um dado sensível."""
        chave_normalizada = chave.lower().replace("-", "_")
        if any(termo in chave_normalizada for termo in TERMOS_SENSIVEIS):
            return CofreCredenciais.mascarar_chave(str(valor))
        if isinstance(valor, str):
            return self._sanitizar_texto(valor)
        if isinstance(valor, dict):
            return {k: self._sanitizar_valor(k, v) for k, v in valor.items()}
        return valor

    def _obter_contexto_rastreamento(self) -> tuple[str | None, str | None]:
        """Obtém trace_id e span_id do contexto ativo do OpenTelemetry em formato hexadecimal."""
        try:
            span_atual = trace.get_current_span()
            ctx = span_atual.get_span_context()
            if ctx and ctx.is_valid:
                return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"
        except Exception:  # noqa: BLE001
            return None, None
        return None, None

    def format(self, record: logging.LogRecord) -> str:
        mensagem_bruta = record.getMessage()
        mensagem_sanitizada = self._sanitizar_texto(mensagem_bruta)

        trace_id, span_id = self._obter_contexto_rastreamento()

        dados: dict[str, Any] = {
            "timestamp": datetime.datetime.fromtimestamp(
                record.created, tz=datetime.UTC
            ).isoformat(),
            "servico": self._servico,
            "nivel": record.levelname,
            "logger": record.name,
            "mensagem": mensagem_sanitizada,
            "arquivo": record.filename,
            "linha": record.lineno,
        }

        # Injeta identificadores de correlação se disponíveis
        if trace_id:
            dados["trace_id"] = trace_id
        if span_id:
            dados["span_id"] = span_id

        # Captura request_id se fornecido no registro
        if hasattr(record, "request_id") and record.request_id:
            dados["request_id"] = str(record.request_id)

        if record.exc_info:
            dados["excecao"] = self._sanitizar_texto(
                self.formatException(record.exc_info)
            )

        # Campos extras úteis para observabilidade
        for chave, valor in record.__dict__.items():
            if chave not in (
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "request_id",
            ):
                dados[chave] = self._sanitizar_valor(chave, valor)

        return json.dumps(dados, ensure_ascii=False)
