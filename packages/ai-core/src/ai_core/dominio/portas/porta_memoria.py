"""Porta abstrata para armazenamento e recuperação de histórico de conversas."""

from abc import ABC, abstractmethod

from ai_core.dominio.modelos.mensagem import Mensagem


class PortaRepositorioMemoria(ABC):
    """Contrato abstrato para persistência e recuperação de histórico conversacional."""

    @abstractmethod
    async def salvar_mensagem(
        self, id_conversa: str, mensagem: Mensagem, id_usuario: str | None = None
    ) -> None:
        """Adiciona uma mensagem ao histórico da conversa indicada, validando posse do usuário."""

    @abstractmethod
    async def recuperar_historico(
        self,
        id_conversa: str,
        limite: int | None = None,
        id_usuario: str | None = None,
    ) -> tuple[Mensagem, ...]:
        """Recupera mensagens da conversa se pertencente ao usuário ou pública."""

    @abstractmethod
    async def limpar_historico(
        self, id_conversa: str, id_usuario: str | None = None
    ) -> None:
        """Remove todo o histórico da conversa indicada sob validação de autorização."""
