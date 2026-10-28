"""Modelos de domínio para agentes autônomos e orquestração de ciclos cognitivos."""

from dataclasses import dataclass, field
from typing import Literal

from ai_core.dominio.modelos.ferramenta import ChamadaFerramenta, ResultadoFerramenta
from ai_core.dominio.modelos.geracao import UsoTokens

EstadoCicloAgente = Literal[
    "iniciado",
    "pensando",
    "aguardando_ferramenta",
    "executando_ferramenta",
    "concluido",
    "falhou",
]


@dataclass(frozen=True, slots=True)
class PassoAgente:
    """Representa uma iteração ou passo do ciclo de raciocínio de um agente."""

    numero_passo: int
    pensamento: str = ""
    chamadas_ferramentas: tuple[ChamadaFerramenta, ...] = ()
    resultados_ferramentas: tuple[ResultadoFerramenta, ...] = ()
    resposta_parcial: str = ""


@dataclass(frozen=True, slots=True)
class ConfiguracaoAgente:
    """Configurações e limites operacionais de um agente."""

    nome: str
    instrucao_sistema: str
    limite_passos: int = 10
    timeout_segundos: float = 60.0
    ferramentas_permitidas: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResultadoExecucaoAgente:
    """Resultado consolidado da execução de um fluxo de agente."""

    resposta_final: str
    passos: tuple[PassoAgente, ...] = field(default_factory=tuple)
    sucesso: bool = True
    total_tokens: UsoTokens = field(default_factory=UsoTokens)
    tempo_total_segundos: float = 0.0
    erro: str | None = None
