"""Roteamento dinâmico de modelos e seleção inteligente de provedores."""

import logging
from collections.abc import AsyncIterator

from ai_core.dominio.excecoes import ErroModeloNaoSuportado
from ai_core.dominio.modelos.geracao import (
    PedacoResposta,
    RequisicaoGeracao,
    RespostaGeracao,
)
from ai_core.dominio.modelos.modelo import (
    CriterioSelecaoModelo,
    InformacoesModelo,
)
from ai_core.dominio.portas.porta_provedor import PortaProvedorLLM
from ai_core.resiliencia.fallback import PoliticaFallback

registro_log = logging.getLogger(__name__)


class RoteadorModelos:
    """Roteia requisições para o provedor apropriado com suporte a fallback."""

    def __init__(
        self,
        politica_fallback: PoliticaFallback | None = None,
    ) -> None:
        self._provedores: dict[str, PortaProvedorLLM] = {}
        self._modelos_info: dict[str, InformacoesModelo] = {}
        self._mapa_fallbacks: dict[str, tuple[str, ...]] = {}
        self._fallback = politica_fallback or PoliticaFallback()

    def definir_fallback(
        self, modelo_origem: str, modelos_fallback: tuple[str, ...]
    ) -> None:
        """Configura modelos de contingência padrão para um determinado modelo."""
        self._mapa_fallbacks[modelo_origem] = modelos_fallback

    def registrar_provedor(self, provedor: PortaProvedorLLM) -> None:
        """Adiciona um provedor ao catálogo operacional."""
        self._provedores[provedor.nome_provedor] = provedor

    def registrar_modelo(self, info: InformacoesModelo) -> None:
        """Cadastra metadados e capacidades de um modelo."""
        self._modelos_info[info.identificador] = info

    def listar_modelos(self) -> tuple[InformacoesModelo, ...]:
        """Retorna lista com todos os modelos cadastrados."""
        return tuple(self._modelos_info.values())

    def obter_provedor_para_modelo(self, modelo: str) -> PortaProvedorLLM:
        """Localiza o primeiro provedor cadastrado que declara suporte ao modelo."""
        for provedor in self._provedores.values():
            if (
                modelo in provedor.modelos_suportados
                or "*" in provedor.modelos_suportados
            ):
                return provedor

        info = self._modelos_info.get(modelo)
        if info and info.provedor in self._provedores:
            return self._provedores[info.provedor]

        raise ErroModeloNaoSuportado(
            f"Nenhum provedor ativo registrado para o modelo '{modelo}'."
        )

    def selecionar_modelo(self, criterio: CriterioSelecaoModelo) -> InformacoesModelo:
        """Seleciona o modelo mais adequado segundo os critérios exigidos."""
        candidatos = list(self._modelos_info.values())

        if criterio.provedor_preferencial:
            preferidos = [
                m for m in candidatos if m.provedor == criterio.provedor_preferencial
            ]
            if preferidos:
                candidatos = preferidos

        for cap in criterio.capacidades_obrigatorias:
            candidatos = [m for m in candidatos if cap in m.capacidades]

        if criterio.limite_contexto_minimo > 0:
            candidatos = [
                m
                for m in candidatos
                if m.limite_contexto >= criterio.limite_contexto_minimo
            ]

        if not candidatos:
            raise ErroModeloNaoSuportado(
                f"Nenhum modelo atende aos critérios especificados: {criterio}"
            )

        return candidatos[0]

    async def gerar(
        self,
        requisicao: RequisicaoGeracao,
        modelos_fallback: tuple[str, ...] = (),
    ) -> RespostaGeracao:
        """Gera resposta com suporte a encadeamento de fallback automático."""
        fallbacks_configurados = self._mapa_fallbacks.get(requisicao.modelo, ())
        modelos_tentativa = [
            requisicao.modelo,
            *modelos_fallback,
            *[m for m in fallbacks_configurados if m not in modelos_fallback],
        ]
        operacoes = []

        for mod in modelos_tentativa:
            try:
                provedor = self.obter_provedor_para_modelo(mod)
                req_mod = RequisicaoGeracao(
                    modelo=mod,
                    mensagens=requisicao.mensagens,
                    configuracao=requisicao.configuracao,
                    ferramentas=requisicao.ferramentas,
                )

                async def _executar(p=provedor, r=req_mod) -> RespostaGeracao:
                    return await p.gerar(r)

                operacoes.append((f"{provedor.nome_provedor}:{mod}", _executar))
            except ErroModeloNaoSuportado:
                continue

        if not operacoes:
            raise ErroModeloNaoSuportado(
                f"Nenhum provedor registrado para o modelo '{requisicao.modelo}'."
            )

        return await self._fallback.executar_com_retaguarda(operacoes)

    async def gerar_fluxo(
        self, requisicao: RequisicaoGeracao
    ) -> AsyncIterator[PedacoResposta]:
        """Gera resposta em fluxo através do provedor responsável."""
        provedor = self.obter_provedor_para_modelo(requisicao.modelo)
        async for pedaco in provedor.gerar_fluxo(requisicao):
            yield pedaco
