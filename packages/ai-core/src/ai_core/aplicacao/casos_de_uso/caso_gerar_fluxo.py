"""Caso de uso de geração contínua (streaming) de respostas de LLM."""

from collections.abc import AsyncIterator

from ai_core.adaptadores.memoria.gerenciador_contexto import GerenciadorContexto
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.dominio.modelos.geracao import PedacoResposta, RequisicaoGeracao
from ai_core.dominio.portas.porta_memoria import PortaRepositorioMemoria
from ai_core.dominio.portas.porta_observabilidade import PortaObservabilidade
from ai_core.resiliencia.limitador import LimitadorTaxa
from ai_core.resiliencia.orcamento import PoliticaOrcamentoTokens


class CasoDeUsoGerarRespostaFluxo:
    """Orquestra a geração de resposta via streaming assíncrono."""

    def __init__(
        self,
        roteador: RoteadorModelos,
        gerenciador_contexto: GerenciadorContexto | None = None,
        repositorio_memoria: PortaRepositorioMemoria | None = None,
        observabilidade: PortaObservabilidade | None = None,
        limitador_taxa: LimitadorTaxa | None = None,
        politica_orcamento: PoliticaOrcamentoTokens | None = None,
    ) -> None:
        self._roteador = roteador
        self._gerenciador_contexto = gerenciador_contexto or GerenciadorContexto()
        self._repositorio_memoria = repositorio_memoria
        self._observabilidade = observabilidade
        self._limitador_taxa = limitador_taxa
        self._politica_orcamento = politica_orcamento

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

        reserva = None
        estimativa_entrada = 0
        if self._politica_orcamento:
            estimativa_entrada = sum(
                self._gerenciador_contexto.estimar_tokens_mensagem(m)
                for m in mensagens_ajustadas
            )
            max_saida = (
                requisicao.configuracao.max_tokens
                if requisicao.configuracao and requisicao.configuracao.max_tokens
                else 256
            )
            reserva = await self._politica_orcamento.reservar_tokens(
                estimativa_entrada + max_saida, id_usuario=id_usuario
            )

        tokens_saida_estimados = 0
        reserva_finalizada = False
        try:
            async for pedaco in self._roteador.gerar_fluxo(requisicao_efetiva):
                if pedaco.texto:
                    tokens_saida_estimados += max(1, len(pedaco.texto) // 4)
                yield pedaco

            if self._politica_orcamento and reserva is not None:
                total_real = estimativa_entrada + tokens_saida_estimados
                reserva_finalizada = True
                await self._politica_orcamento.confirmar_reserva(
                    reserva.id_reserva, total_real
                )
        except BaseException:
            if (
                self._politica_orcamento
                and reserva is not None
                and not reserva_finalizada
            ):
                reserva_finalizada = True
                await self._politica_orcamento.cancelar_reserva(reserva.id_reserva)
            raise
        finally:
            if (
                self._politica_orcamento
                and reserva is not None
                and not reserva_finalizada
            ):
                reserva_finalizada = True
                await self._politica_orcamento.cancelar_reserva(reserva.id_reserva)
