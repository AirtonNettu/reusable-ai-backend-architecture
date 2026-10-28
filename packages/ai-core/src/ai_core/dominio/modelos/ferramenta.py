"""Modelos de domínio para ferramentas e chamadas de ferramentas (Tool Calling)."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class DefinicaoParametro:
    """Metadados de um parâmetro de ferramenta."""

    tipo: str
    descricao: str
    obrigatorio: bool = True
    padrao: Any = None


@dataclass(frozen=True, slots=True)
class DefinicaoFerramenta:
    """Definição de contrato de uma ferramenta executável por agentes."""

    nome: str
    descricao: str
    esquema_parametros: dict[str, Any] = field(default_factory=dict)
    requer_autorizacao: bool = False


@dataclass(frozen=True, slots=True)
class ChamadaFerramenta:
    """Requisição gerada pelo modelo para execução de uma ferramenta específica."""

    identificador: str
    nome_ferramenta: str
    argumentos: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResultadoFerramenta:
    """Resultado da execução de uma ferramenta para ser devolvido ao modelo."""

    identificador_chamada: str
    nome_ferramenta: str
    resultado: Any
    sucesso: bool = True
    erro: str | None = None
