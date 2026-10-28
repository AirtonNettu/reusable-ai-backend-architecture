"""Implementação de memória conversacional em memória volátil com isolamento de usuário."""

import asyncio

from ai_core.dominio.excecoes import ErroAcessoNaoAutorizadoConversa
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.dominio.portas.porta_memoria import PortaRepositorioMemoria


class MemoriaEmMemoria(PortaRepositorioMemoria):
    """Repositório de histórico conversacional seguro para execução assíncrona e multilocatário."""

    def __init__(self) -> None:
        self._conversas: dict[str, list[Mensagem]] = {}
        self._proprietarios: dict[str, str] = {}
        self._bloqueio = asyncio.Lock()

    def _validar_propriedade(self, id_conversa: str, id_usuario: str | None) -> None:
        proprietario = self._proprietarios.get(id_conversa)
        if (
            proprietario is not None
            and id_usuario is not None
            and proprietario != id_usuario
        ):
            raise ErroAcessoNaoAutorizadoConversa(
                f"Acesso negado à conversa '{id_conversa}'. Ela pertence a outro usuário."
            )
        if proprietario is not None and id_usuario is None:
            raise ErroAcessoNaoAutorizadoConversa(
                f"Acesso negado à conversa '{id_conversa}'. Usuário não autenticado para conversa privada."
            )

    async def salvar_mensagem(
        self, id_conversa: str, mensagem: Mensagem, id_usuario: str | None = None
    ) -> None:
        async with self._bloqueio:
            self._validar_propriedade(id_conversa, id_usuario)
            if id_usuario is not None and id_conversa not in self._proprietarios:
                self._proprietarios[id_conversa] = id_usuario

            if id_conversa not in self._conversas:
                self._conversas[id_conversa] = []
            self._conversas[id_conversa].append(mensagem)

    async def recuperar_historico(
        self,
        id_conversa: str,
        limite: int | None = None,
        id_usuario: str | None = None,
    ) -> tuple[Mensagem, ...]:
        async with self._bloqueio:
            self._validar_propriedade(id_conversa, id_usuario)
            mensagens = self._conversas.get(id_conversa, [])
            if limite is not None and limite > 0:
                return tuple(mensagens[-limite:])
            return tuple(mensagens)

    async def limpar_historico(
        self, id_conversa: str, id_usuario: str | None = None
    ) -> None:
        async with self._bloqueio:
            self._validar_propriedade(id_conversa, id_usuario)
            if id_conversa in self._conversas:
                del self._conversas[id_conversa]
            if id_conversa in self._proprietarios:
                del self._proprietarios[id_conversa]
