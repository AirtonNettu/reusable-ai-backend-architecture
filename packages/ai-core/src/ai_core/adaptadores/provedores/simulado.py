"""Adaptador de provedor simulado (Fake/Mock) para testes e execução offline."""

import asyncio
from collections.abc import AsyncIterator

from ai_core.dominio.excecoes import ErroModeloNaoSuportado
from ai_core.dominio.modelos.ferramenta import ChamadaFerramenta
from ai_core.dominio.modelos.geracao import (
    PedacoResposta,
    RequisicaoGeracao,
    RespostaGeracao,
    UsoTokens,
)
from ai_core.dominio.portas.porta_provedor import PortaProvedorLLM


class AdaptadorSimulado(PortaProvedorLLM):
    """Provedor LLM simulado para testes unitários, de integração e modo offline."""

    def __init__(
        self,
        nome_provedor: str = "simulado",
        modelos_suportados: tuple[str, ...] = ("modelo-teste", "modelo-rapido"),
        resposta_padrao: str = "Resposta simulada de teste.",
        excecao_para_lancar: Exception | None = None,
        atraso_segundos: float = 0.0,
    ) -> None:
        self._nome_provedor = nome_provedor
        self._modelos_suportados = modelos_suportados
        self.resposta_padrao = resposta_padrao
        self.excecao_para_lancar = excecao_para_lancar
        self.atraso_segundos = atraso_segundos
        self.historico_requisicoes: list[RequisicaoGeracao] = []
        self.chamadas_ferramentas_para_retornar: list[ChamadaFerramenta] = []

    @property
    def nome_provedor(self) -> str:
        return self._nome_provedor

    @property
    def modelos_suportados(self) -> tuple[str, ...]:
        return self._modelos_suportados

    def _validar_modelo(self, modelo: str) -> None:
        if (
            self._modelos_suportados
            and modelo not in self._modelos_suportados
            and "*" not in self._modelos_suportados
        ):
            raise ErroModeloNaoSuportado(
                f"Modelo '{modelo}' não suportado pelo provedor '{self._nome_provedor}'."
            )

    async def gerar(self, requisicao: RequisicaoGeracao) -> RespostaGeracao:
        self.historico_requisicoes.append(requisicao)
        self._validar_modelo(requisicao.modelo)

        if self.atraso_segundos > 0:
            await asyncio.sleep(self.atraso_segundos)

        if self.excecao_para_lancar:
            raise self.excecao_para_lancar

        motivo = "sucesso"
        chamadas = tuple(self.chamadas_ferramentas_para_retornar)
        if chamadas:
            motivo = "chamada_ferramenta"

        texto = self.resposta_padrao
        tokens_entrada = sum(len(m.conteudo.split()) for m in requisicao.mensagens)
        tokens_saida = len(texto.split())

        return RespostaGeracao(
            texto=texto,
            modelo=requisicao.modelo,
            motivo_finalizacao=motivo,
            uso=UsoTokens(
                tokens_entrada=tokens_entrada,
                tokens_saida=tokens_saida,
                total_tokens=tokens_entrada + tokens_saida,
            ),
            chamadas_ferramentas=chamadas,
        )

    async def gerar_fluxo(
        self, requisicao: RequisicaoGeracao
    ) -> AsyncIterator[PedacoResposta]:
        self.historico_requisicoes.append(requisicao)
        self._validar_modelo(requisicao.modelo)

        if self.excecao_para_lancar:
            raise self.excecao_para_lancar

        palavras = self.resposta_padrao.split(" ")
        for i, palavra in enumerate(palavras):
            if self.atraso_segundos > 0:
                await asyncio.sleep(self.atraso_segundos)

            espaco = " " if i < len(palavras) - 1 else ""
            eh_ultimo = i == len(palavras) - 1

            yield PedacoResposta(
                texto=palavra + espaco,
                finalizado=eh_ultimo,
                motivo_finalizacao="sucesso" if eh_ultimo else None,
            )

    async def validar_disponibilidade(self) -> bool:
        return self.excecao_para_lancar is None
