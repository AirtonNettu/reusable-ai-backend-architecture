"""Caso de uso de geração contínua (streaming) de respostas de LLM."""

from collections.abc import AsyncIterator

from ai_core.adaptadores.memoria.gerenciador_contexto import GerenciadorContexto
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.dominio.modelos.geracao import PedacoResposta, RequisicaoGeracao
from ai_core.dominio.portas.porta_memoria import PortaRepositorioMemoria
from ai_core.dominio.portas.porta_observabilidade import PortaObservabilidade
from ai_core.resiliencia.limitador import LimitadorTaxa


class CasoDeUsoGerarRespostaFluxo:
    """Orquestra a geração de resposta via streaming assíncrono."""

    def __init__(
        self,
        roteador: RoteadorModelos,
        gerenciador_contexto: GerenciadorContexto | None = None,
        repositorio_memoria: PortaRepositorioMemoria | None = None,
        observabilidade: PortaObservabilidade | None = None,
        limitador_taxa: LimitadorTaxa | None = None,
    ) -> None:
        self._roteador = roteador
        self._gerenciador_contexto = gerenciador_contexto or GerenciadorContexto()
        self._repositorio_memoria = repositorio_memoria
        self._observabilidade = observabilidade
        self._limitador_taxa = limitador_taxa

    async def executar(
        self,
        requisicao: RequisicaoGeracao,
        id_conversa: str | None = None,
        id_usuario: str | None = None,
    ) -> AsyncIterator[PedacoResposta]:
        """Inicia e entrega o fluxo contínuo de fragmentos da resposta com validação de usuário."""
        mensagens_finais = requisicao.mensagens

        if id_conversa and self._repositorio_memoria:
            historico = await self._repositorio_memoria.recuperar_historico(
                id_conversa, id_usuario=id_usuario
            )
            mensagens_finais = (*historico, *requisicao.mensagens)

        mensagens_ajustadas = self._gerenciador_contexto.ajustar_janela(
            mensagens_finais
        )

        requisicao_efetiva = RequisicaoGeracao(
            modelo=requisicao.modelo,
            mensagens=mensagens_ajustadas,
            configuracao=requisicao.configuracao,
            ferramentas=requisicao.ferramentas,
        )

        if self._limitador_taxa:
            await self._limitador_taxa.adquirir(1)

        if self._observabilidade:
            self._observabilidade.registrar_contagem(
                "requisicoes_streaming_iniciadas",
                tags={"modelo": requisicao.modelo},
            )

        async for pedaco in self._roteador.gerar_fluxo(requisicao_efetiva):
            yield pedaco
