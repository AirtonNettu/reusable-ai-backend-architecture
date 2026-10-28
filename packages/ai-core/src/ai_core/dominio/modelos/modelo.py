"""Metadados e capacidades dos modelos de linguagem disponíveis na plataforma."""

from dataclasses import dataclass
from typing import Literal

CapacidadeModelo = Literal[
    "texto",
    "chat",
    "streaming",
    "ferramentas",
    "visao",
    "saida_estruturada",
]


@dataclass(frozen=True, slots=True)
class InformacoesModelo:
    """Metadados descritivos sobre um modelo de linguagem."""

    identificador: str
    nome_exibicao: str
    provedor: str
    capacidades: tuple[CapacidadeModelo, ...]
    limite_contexto: int = 4096
    custo_por_milhar_entrada: float = 0.0
    custo_por_milhar_saida: float = 0.0


@dataclass(frozen=True, slots=True)
class CriterioSelecaoModelo:
    """Critérios para seleção e roteamento automático de modelos."""

    capacidades_obrigatorias: tuple[CapacidadeModelo, ...] = ()
    provedor_preferencial: str | None = None
    limite_contexto_minimo: int = 0
