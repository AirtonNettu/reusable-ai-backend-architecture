"""Orquestrador e runtime cognitivo de agentes autônomos (Padrão ReAct)."""

import time

from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.dominio.modelos.agente import (
    ConfiguracaoAgente,
    PassoAgente,
    ResultadoExecucaoAgente,
)
from ai_core.dominio.modelos.ferramenta import (
    DefinicaoFerramenta,
    ResultadoFerramenta,
)
from ai_core.dominio.modelos.geracao import (
    ConfiguracaoGeracao,
    RequisicaoGeracao,
    UsoTokens,
)
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.dominio.portas.porta_ferramenta import PortaExecutorFerramentas
from ai_core.dominio.portas.porta_observabilidade import PortaObservabilidade


class OrquestradorAgente:
    """Runtime de execução de agentes com raciocínio, uso de ferramentas e salvaguardas."""

    def __init__(
        self,
        roteador: RoteadorModelos,
        executor_ferramentas: PortaExecutorFerramentas,
        modelo_padrao: str,
        observabilidade: PortaObservabilidade | None = None,
    ) -> None:
        self._roteador = roteador
        self._executor_ferramentas = executor_ferramentas
        self._modelo_padrao = modelo_padrao
        self._observabilidade = observabilidade

    def _filtrar_ferramentas(
        self, permitidas: tuple[str, ...]
    ) -> tuple[DefinicaoFerramenta, ...]:
        todas = self._executor_ferramentas.obter_definicoes()
        if not permitidas:
            return todas
        return tuple(f for f in todas if f.nome in permitidas)

    async def executar(
        self,
        objetivo: str,
        configuracao: ConfiguracaoAgente,
        historico_previo: tuple[Mensagem, ...] = (),
    ) -> ResultadoExecucaoAgente:
        """Executa o ciclo de raciocínio e ação do agente até a resolução do objetivo."""
        inicio = time.monotonic()
        passos: list[PassoAgente] = []
        tokens_acumulados = [0, 0, 0]  # entrada, saida, total

        ferramentas = self._filtrar_ferramentas(configuracao.ferramentas_permitidas)

        mensagens_ciclo: list[Mensagem] = [
            Mensagem(papel="sistema", conteudo=configuracao.instrucao_sistema),
            *historico_previo,
            Mensagem(papel="usuario", conteudo=objetivo),
        ]

        resposta_final = ""
        sucesso = True
        erro_final: str | None = None

        for numero_passo in range(1, configuracao.limite_passos + 1):
            if time.monotonic() - inicio > configuracao.timeout_segundos:
                sucesso = False
                erro_final = f"Tempo limite ({configuracao.timeout_segundos}s) esgotado no agente."
                break

            requisicao = RequisicaoGeracao(
                modelo=self._modelo_padrao,
                mensagens=tuple(mensagens_ciclo),
                configuracao=ConfiguracaoGeracao(temperatura=0.2),
                ferramentas=ferramentas,
            )

            resposta = await self._roteador.gerar(requisicao)

            tokens_acumulados[0] += resposta.uso.tokens_entrada
            tokens_acumulados[1] += resposta.uso.tokens_saida
            tokens_acumulados[2] += resposta.uso.total_tokens

            if not resposta.chamadas_ferramentas:
                resposta_final = resposta.texto
                passos.append(
                    PassoAgente(
                        numero_passo=numero_passo,
                        pensamento=resposta.texto,
                        resposta_parcial=resposta.texto,
                    )
                )
                break

            # Se há chamadas de ferramenta
            resultados_passo: list[ResultadoFerramenta] = []
            mensagem_assistente = Mensagem(
                papel="assistente",
                conteudo=resposta.texto,
                chamadas_ferramentas=resposta.chamadas_ferramentas,
            )
            mensagens_ciclo.append(mensagem_assistente)

            for chamada in resposta.chamadas_ferramentas:
                if self._observabilidade:
                    self._observabilidade.registrar_evento(
                        "execucao_ferramenta_agente",
                        {
                            "ferramenta": chamada.nome_ferramenta,
                            "agente": configuracao.nome,
                        },
                    )

                resultado = await self._executor_ferramentas.executar(chamada)
                resultados_passo.append(resultado)

                conteudo_resposta = (
                    str(resultado.resultado)
                    if resultado.sucesso
                    else f"Erro: {resultado.erro}"
                )
                mensagens_ciclo.append(
                    Mensagem(
                        papel="ferramenta",
                        conteudo=conteudo_resposta,
                        nome=chamada.nome_ferramenta,
                        identificador_chamada_ferramenta=chamada.identificador,
                    )
                )

            passos.append(
                PassoAgente(
                    numero_passo=numero_passo,
                    pensamento=resposta.texto,
                    chamadas_ferramentas=resposta.chamadas_ferramentas,
                    resultados_ferramentas=tuple(resultados_passo),
                )
            )
        else:
            sucesso = False
            erro_final = (
                f"Limite de {configuracao.limite_passos} passos atingido sem conclusão."
            )
            resposta_final = passos[-1].pensamento if passos else ""

        duracao_total = time.monotonic() - inicio

        return ResultadoExecucaoAgente(
            resposta_final=resposta_final,
            passos=tuple(passos),
            sucesso=sucesso,
            total_tokens=UsoTokens(
                tokens_entrada=tokens_acumulados[0],
                tokens_saida=tokens_acumulados[1],
                total_tokens=tokens_acumulados[2],
            ),
            tempo_total_segundos=duracao_total,
            erro=erro_final,
        )
