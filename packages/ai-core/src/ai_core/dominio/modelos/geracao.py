"""Modelos de geração de texto, configurações e respostas do domínio."""

from dataclasses import dataclass, field
from typing import Any, Literal

from ai_core.dominio.modelos.ferramenta import ChamadaFerramenta, DefinicaoFerramenta
from ai_core.dominio.modelos.mensagem import Mensagem

TipoFinalizacao = Literal[
    "sucesso",
    "limite_tokens",
    "chamada_ferramenta",
    "filtro_conteudo",
    "erro",
]


@dataclass(frozen=True, slots=True)
class UsoTokens:
    """Contagem de tokens consumidos na requisição."""

    tokens_entrada: int = 0
    tokens_saida: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ConfiguracaoGeracao:
    """Parâmetros de controle da geração do modelo LLM."""

    temperatura: float = 0.7
    top_p: float | None = None
    max_tokens: int | None = None
    sequencias_parada: tuple[str, ...] = ()
    formato_json: bool = False
    esquema_saida: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RequisicaoGeracao:
    """Contrato agnóstico de requisição de geração para provedores de LLM."""

    modelo: str
    mensagens: tuple[Mensagem, ...]
    configuracao: ConfiguracaoGeracao = field(default_factory=ConfiguracaoGeracao)
    ferramentas: tuple[DefinicaoFerramenta, ...] = ()


@dataclass(frozen=True, slots=True)
class PedacoResposta:
    """Fragmento (chunk) de resposta para streaming assíncrono."""

    texto: str = ""
    chamadas_ferramentas: tuple[ChamadaFerramenta, ...] = ()
    finalizado: bool = False
    motivo_finalizacao: TipoFinalizacao | None = None
    uso: UsoTokens | None = None


@dataclass(frozen=True, slots=True)
class RespostaGeracao:
    """Resultado final consolidado da geração de um modelo LLM."""

    texto: str
    modelo: str
    motivo_finalizacao: TipoFinalizacao
    uso: UsoTokens = field(default_factory=UsoTokens)
    chamadas_ferramentas: tuple[ChamadaFerramenta, ...] = ()
