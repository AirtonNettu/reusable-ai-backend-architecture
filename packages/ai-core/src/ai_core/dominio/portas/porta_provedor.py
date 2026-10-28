"""Porta abstrata para provedores de Modelos de Linguagem (LLM)."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ai_core.dominio.modelos.geracao import (
    PedacoResposta,
    RequisicaoGeracao,
    RespostaGeracao,
)


class PortaProvedorLLM(ABC):
    """Contrato que todo adaptador de provedor LLM deve implementar."""

    @property
    @abstractmethod
    def nome_provedor(self) -> str:
        """Identificador textual único do provedor (ex: ollama, openai, gemini)."""

    @property
    @abstractmethod
    def modelos_suportados(self) -> tuple[str, ...]:
        """Coleção de identificadores de modelos suportados por este provedor."""

    @abstractmethod
    async def gerar(self, requisicao: RequisicaoGeracao) -> RespostaGeracao:
        """Gera uma resposta consolidada a partir da requisição recebida."""

    @abstractmethod
    async def gerar_fluxo(
        self, requisicao: RequisicaoGeracao
    ) -> AsyncIterator[PedacoResposta]:
        """Gera resposta em fluxo contínuo (streaming) de fragmentos."""

    @abstractmethod
    async def validar_disponibilidade(self) -> bool:
        """Verifica se o provedor está acessível e operacional."""
