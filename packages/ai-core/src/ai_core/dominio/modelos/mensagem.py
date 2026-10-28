"""Entidade Mensagem do domínio do AI Core."""

from dataclasses import dataclass, field
from typing import Any, Literal

from ai_core.dominio.modelos.ferramenta import ChamadaFerramenta

PapelMensagem = Literal["sistema", "usuario", "assistente", "ferramenta"]


@dataclass(frozen=True, slots=True)
class Mensagem:
    """Representa uma mensagem utilizada em uma interação com IA.

    Attributes:
        papel: Identifica a origem ou função da mensagem.
        conteudo: Conteúdo textual associado à mensagem.
        nome: Identificador opcional do participante ou ferramenta.
        metadados: Dicionário opcional para metadados arbitrários.
        chamadas_ferramentas: Chamadas de ferramentas solicitadas pelo assistente.
        identificador_chamada_ferramenta: ID da chamada respondida caso o papel seja ferramenta.
    """

    papel: PapelMensagem
    conteudo: str
    nome: str | None = None
    metadados: dict[str, Any] = field(default_factory=dict)
    chamadas_ferramentas: tuple[ChamadaFerramenta, ...] = ()
    identificador_chamada_ferramenta: str | None = None
