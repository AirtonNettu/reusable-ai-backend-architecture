"""Caso de uso de geração síncrona/consolidada de resposta de LLM."""

import time
from typing import Any

from ai_core.adaptadores.memoria.gerenciador_contexto import GerenciadorContexto
from ai_core.adaptadores.observabilidade.rastreador_otel import rastreador_global
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.dominio.modelos.geracao import RequisicaoGeracao, RespostaGeracao
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.dominio.portas.porta_memoria import PortaRepositorioMemoria
from ai_core.dominio.portas.porta_observabilidade import PortaObservabilidade
from ai_core.resiliencia.disjuntor import Disjuntor
from ai_core.resiliencia.limitador import LimitadorTaxa, RastreadorConsumoTokens
from ai_core.resiliencia.orcamento import PoliticaOrcamentoTokens
from ai_core.resiliencia.retentativa import PoliticaRetentativa


class CasoDeUsoGerarResposta:
    """Orquestra as etapas de contexto, resiliência, observabilidade e geração."""

    def __init__(
        self,
        roteador: RoteadorModelos,
        gerenciador_contexto: GerenciadorContexto | None = None,
        repositorio_memoria: PortaRepositorioMemoria | None = None,
        observabilidade: PortaObservabilidade | None = None,
        disjuntor: Disjuntor | None = None,
        politica_retentativa: PoliticaRetentativa | None = None,
        limitador_taxa: LimitadorTaxa | None = None,
        rastreador_consumo: RastreadorConsumoTokens | None = None,
        politica_orcamento: PoliticaOrcamentoTokens | None = None,
    ) -> None:
        self._roteador = roteador
        self._gerenciador_contexto = gerenciador_contexto or GerenciadorContexto()
        self._repositorio_memoria = repositorio_memoria
        self._observabilidade = observabilidade
        self._disjuntor = disjuntor
        self._politica_retentativa = politica_retentativa or PoliticaRetentativa()
        self._limitador_taxa = limitador_taxa
        self._rastreador_consumo = rastreador_consumo
        self._politica_orcamento = politica_orcamento

    async def executar(
        self,
        requisicao: RequisicaoGeracao,
        id_conversa: str | None = None,
        modelos_fallback: tuple[str, ...] = (),
        id_usuario: str | None = None,
    ) -> RespostaGeracao:
        """Executa a geração aplicando políticas de confiabilidade, contexto e isolamento de usuário."""
        inicio = time.monotonic()

        atributos_span = {
            "llm.model": requisicao.modelo,
            "llm.is_fallback_enabled": bool(modelos_fallback),
        }

        async with rastreador_global.iniciar_span_assincrono(
            "caso_de_uso.gerar_resposta", atributos=atributos_span
        ) as span:
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

            reserva = None
            if self._politica_orcamento:
                estimativa_tokens = sum(
                    self._gerenciador_contexto.estimar_tokens_mensagem(m)
                    for m in mensagens_ajustadas
                )
                reserva = await self._politica_orcamento.reservar_tokens(
                    estimativa_tokens, id_usuario=id_usuario
                )

            try:
                if self._limitador_taxa:
                    await self._limitador_taxa.adquirir(1)

                async def _chamada_geracao() -> RespostaGeracao:
                    return await self._roteador.gerar(
                        requisicao_efetiva, modelos_fallback=modelos_fallback
                    )

                async def _chamada_com_disjuntor() -> RespostaGeracao:
                    if self._disjuntor:
                        return await self._disjuntor.executar(_chamada_geracao)
                    return await _chamada_geracao()

                resposta = await self._politica_retentativa.executar(
                    _chamada_com_disjuntor
                )

                if self._politica_orcamento and reserva is not None:
                    await self._politica_orcamento.confirmar_reserva(
                        reserva.id_reserva, resposta.uso.total_tokens
                    )
            except Exception as erro:
                if self._observabilidade:
                    self._observabilidade.registrar_contagem(
                        "llm_falha",
                        tags={
                            "modelo": requisicao.modelo,
                            "tipo_erro": type(erro).__name__,
                        },
                    )

                if self._politica_orcamento and reserva is not None:
                    tokens_faturados = 0
                    cursor: Any = erro
                    while cursor is not None:
                        if (
                            hasattr(cursor, "tokens_faturados")
                            and isinstance(cursor.tokens_faturados, int)
                            and cursor.tokens_faturados > 0
                        ):
                            tokens_faturados = cursor.tokens_faturados
                            break
                        if hasattr(cursor, "detalhes") and isinstance(
                            cursor.detalhes, dict
                        ):
                            tf = cursor.detalhes.get("tokens_faturados")
                            if isinstance(tf, int) and tf > 0:
                                tokens_faturados = tf
                                break
                        cursor = getattr(cursor, "__cause__", None)

                    if tokens_faturados > 0:
                        await self._politica_orcamento.confirmar_reserva(
                            reserva.id_reserva, tokens_faturados
                        )
                    else:
                        await self._politica_orcamento.cancelar_reserva(
                            reserva.id_reserva
                        )
                raise

            duracao = time.monotonic() - inicio

            # Registro de atributos sanitizados no span OpenTelemetry
            span.set_attribute("llm.response.model", resposta.modelo)
            span.set_attribute("llm.usage.prompt_tokens", resposta.uso.tokens_entrada)
            span.set_attribute("llm.usage.completion_tokens", resposta.uso.tokens_saida)
            span.set_attribute("llm.usage.total_tokens", resposta.uso.total_tokens)

            if self._rastreador_consumo:
                await self._rastreador_consumo.registrar(
                    resposta.modelo,
                    resposta.uso.tokens_entrada,
                    resposta.uso.tokens_saida,
                )

            if self._observabilidade:
                # Registro padrão da porta
                self._observabilidade.registrar_contagem(
                    "requisicoes_geracao_total", tags={"modelo": resposta.modelo}
                )
                self._observabilidade.registrar_latencia(
                    "latencia_geracao_segundos",
                    duracao,
                    tags={"modelo": resposta.modelo},
                )
                # Métodos avançados se for MetricasPrometheus
                if hasattr(self._observabilidade, "registrar_execucao_llm"):
                    self._observabilidade.registrar_execucao_llm(
                        modelo=resposta.modelo,
                        provedor=resposta.modelo,
                        duracao_segundos=duracao,
                    )
                if hasattr(self._observabilidade, "registrar_tokens"):
                    self._observabilidade.registrar_tokens(
                        modelo=resposta.modelo,
                        tokens_entrada=resposta.uso.tokens_entrada,
                        tokens_saida=resposta.uso.tokens_saida,
                    )

            if id_conversa and self._repositorio_memoria:
                for m in requisicao.mensagens:
                    await self._repositorio_memoria.salvar_mensagem(
                        id_conversa, m, id_usuario=id_usuario
                    )
                mensagem_assistente = Mensagem(
                    papel="assistente",
                    conteudo=resposta.texto,
                    chamadas_ferramentas=resposta.chamadas_ferramentas,
                )
                await self._repositorio_memoria.salvar_mensagem(
                    id_conversa, mensagem_assistente, id_usuario=id_usuario
                )

            return resposta
