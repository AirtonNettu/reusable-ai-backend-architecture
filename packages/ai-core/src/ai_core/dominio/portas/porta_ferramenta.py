"""Porta abstrata para execução e registro de ferramentas."""

from abc import ABC, abstractmethod

from ai_core.dominio.modelos.ferramenta import (
    ChamadaFerramenta,
    DefinicaoFerramenta,
    ResultadoFerramenta,
)


class PortaExecutorFerramentas(ABC):
    """Contrato abstrato para autorização, inspeção e execução de ferramentas."""

    @abstractmethod
    def obter_definicoes(self) -> tuple[DefinicaoFerramenta, ...]:
        """Retorna todas as ferramentas registradas e seus contratos."""

    @abstractmethod
    def obter_definicao(self, nome: str) -> DefinicaoFerramenta | None:
        """Busca os metadados de uma ferramenta específica pelo nome."""

    @abstractmethod
    async def executar(self, chamada: ChamadaFerramenta) -> ResultadoFerramenta:
        """Executa a ferramenta solicitada após validações de segurança e parâmetros."""
