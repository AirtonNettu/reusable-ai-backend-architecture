"""Registro e executor concreto de ferramentas para agentes."""

import inspect
from collections.abc import Callable
from typing import Any

from ai_core.adaptadores.ferramentas.seguranca import PoliticaAutorizacaoFerramenta
from ai_core.dominio.excecoes import ErroFerramentaNaoAutorizada
from ai_core.dominio.modelos.ferramenta import (
    ChamadaFerramenta,
    DefinicaoFerramenta,
    ResultadoFerramenta,
)
from ai_core.dominio.portas.porta_ferramenta import PortaExecutorFerramentas


class RegistroFerramentas(PortaExecutorFerramentas):
    """Implementação da porta de ferramentas com registro dinâmico e controle de segurança."""

    def __init__(
        self,
        politica_autorizacao: PoliticaAutorizacaoFerramenta | None = None,
    ) -> None:
        self._ferramentas: dict[str, DefinicaoFerramenta] = {}
        self._executores: dict[str, Callable[..., Any]] = {}
        self._politica = politica_autorizacao or PoliticaAutorizacaoFerramenta()

    def registrar(
        self,
        definicao: DefinicaoFerramenta,
        funcao: Callable[..., Any],
    ) -> None:
        """Registra uma nova ferramenta e sua função executora."""
        self._ferramentas[definicao.nome] = definicao
        self._executores[definicao.nome] = funcao

    def obter_definicoes(self) -> tuple[DefinicaoFerramenta, ...]:
        return tuple(self._ferramentas.values())

    def obter_definicao(self, nome: str) -> DefinicaoFerramenta | None:
        return self._ferramentas.get(nome)

    async def executar(self, chamada: ChamadaFerramenta) -> ResultadoFerramenta:
        nome = chamada.nome_ferramenta
        definicao = self.obter_definicao(nome)

        if not definicao or nome not in self._executores:
            return ResultadoFerramenta(
                identificador_chamada=chamada.identificador,
                nome_ferramenta=nome,
                resultado=None,
                sucesso=False,
                erro=f"Ferramenta '{nome}' não está registrada.",
            )

        try:
            self._politica.autorizar(definicao, chamada)
        except ErroFerramentaNaoAutorizada as erro:
            return ResultadoFerramenta(
                identificador_chamada=chamada.identificador,
                nome_ferramenta=nome,
                resultado=None,
                sucesso=False,
                erro=str(erro),
            )

        funcao = self._executores[nome]
        try:
            if inspect.iscoroutinefunction(funcao):
                resultado = await funcao(**chamada.argumentos)
            else:
                resultado = funcao(**chamada.argumentos)

            return ResultadoFerramenta(
                identificador_chamada=chamada.identificador,
                nome_ferramenta=nome,
                resultado=resultado,
                sucesso=True,
            )
        except TypeError as erro_parametro:
            return ResultadoFerramenta(
                identificador_chamada=chamada.identificador,
                nome_ferramenta=nome,
                resultado=None,
                sucesso=False,
                erro=f"Parâmetros inválidos para ferramenta '{nome}': {erro_parametro}",
            )
        except Exception as erro_execucao:  # noqa: BLE001
            return ResultadoFerramenta(
                identificador_chamada=chamada.identificador,
                nome_ferramenta=nome,
                resultado=None,
                sucesso=False,
                erro=f"Erro interno ao executar '{nome}': {erro_execucao}",
            )
