"""Testes para o orquestrador e runtime de agentes autônomos."""

from collections.abc import AsyncIterator

import pytest
from ai_core.adaptadores.ferramentas.registro import RegistroFerramentas
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.aplicacao.agentes.orquestrador import OrquestradorAgente
from ai_core.dominio.modelos.agente import ConfiguracaoAgente
from ai_core.dominio.modelos.ferramenta import (
    ChamadaFerramenta,
    DefinicaoFerramenta,
)
from ai_core.dominio.modelos.geracao import (
    PedacoResposta,
    RequisicaoGeracao,
    RespostaGeracao,
    UsoTokens,
)
from ai_core.dominio.portas.porta_provedor import PortaProvedorLLM


class ProvedorMockReAct(PortaProvedorLLM):
    """Provedor para testar o ciclo ReAct em múltiplos passos."""

    def __init__(self) -> None:
        self.chamadas = 0

    @property
    def nome_provedor(self) -> str:
        return "react-mock"

    @property
    def modelos_suportados(self) -> tuple[str, ...]:
        return ("modelo-react",)

    async def gerar(self, requisicao: RequisicaoGeracao) -> RespostaGeracao:
        self.chamadas += 1

        # Passo 1: O modelo decide chamar a ferramenta de cálculo
        if self.chamadas == 1:
            return RespostaGeracao(
                texto="Preciso somar os valores antes de responder.",
                modelo=requisicao.modelo,
                motivo_finalizacao="chamada_ferramenta",
                uso=UsoTokens(tokens_entrada=20, tokens_saida=10, total_tokens=30),
                chamadas_ferramentas=(
                    ChamadaFerramenta(
                        identificador="call_1",
                        nome_ferramenta="somar",
                        argumentos={"a": 15, "b": 25},
                    ),
                ),
            )

        # Passo 2: O modelo observa o resultado (40) e responde conclusivamente
        return RespostaGeracao(
            texto="A soma dos valores 15 e 25 é exatamente 40.",
            modelo=requisicao.modelo,
            motivo_finalizacao="sucesso",
            uso=UsoTokens(tokens_entrada=30, tokens_saida=15, total_tokens=45),
            chamadas_ferramentas=(),
        )

    async def gerar_fluxo(
        self, requisicao: RequisicaoGeracao
    ) -> AsyncIterator[PedacoResposta]:
        yield PedacoResposta(texto="mock")

    async def validar_disponibilidade(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_ciclo_react_agente_completo() -> None:
    """Valida raciocínio, execução de ferramenta e entrega de resposta final."""
    roteador = RoteadorModelos()
    provedor = ProvedorMockReAct()
    roteador.registrar_provedor(provedor)

    registro_ferramentas = RegistroFerramentas()
    registro_ferramentas.registrar(
        DefinicaoFerramenta(nome="somar", descricao="Soma dois números"),
        lambda a, b: a + b,
    )

    orquestrador = OrquestradorAgente(
        roteador=roteador,
        executor_ferramentas=registro_ferramentas,
        modelo_padrao="modelo-react",
    )

    config = ConfiguracaoAgente(
        nome="agente-matematica",
        instrucao_sistema="Você é um assistente analítico.",
        limite_passos=5,
    )

    resultado = await orquestrador.executar(
        objetivo="Quanto é 15 + 25?",
        configuracao=config,
    )

    assert resultado.sucesso is True
    assert "40" in resultado.resposta_final
    assert len(resultado.passos) == 2
    assert resultado.total_tokens.total_tokens == 75
    assert resultado.passos[0].chamadas_ferramentas[0].nome_ferramenta == "somar"
    assert resultado.passos[0].resultados_ferramentas[0].resultado == 40


@pytest.mark.asyncio
async def test_agente_limite_passos_atingido() -> None:
    """Verifica interrupção segura quando o limite de iterações é atingido."""
    roteador = RoteadorModelos()

    class ProvedorLoopInfinito(PortaProvedorLLM):
        @property
        def nome_provedor(self) -> str:
            return "loop"

        @property
        def modelos_suportados(self) -> tuple[str, ...]:
            return ("modelo-loop",)

        async def gerar(self, requisicao: RequisicaoGeracao) -> RespostaGeracao:
            return RespostaGeracao(
                texto="Chamando ferramenta novamente...",
                modelo="modelo-loop",
                motivo_finalizacao="chamada_ferramenta",
                chamadas_ferramentas=(
                    ChamadaFerramenta(identificador="c_rep", nome_ferramenta="eco"),
                ),
            )

        async def gerar_fluxo(
            self, req: RequisicaoGeracao
        ) -> AsyncIterator[PedacoResposta]:
            yield PedacoResposta(texto="")

        async def validar_disponibilidade(self) -> bool:
            return True

    roteador.registrar_provedor(ProvedorLoopInfinito())
    registro = RegistroFerramentas()
    registro.registrar(DefinicaoFerramenta(nome="eco", descricao="Eco"), lambda: "ok")

    orquestrador = OrquestradorAgente(
        roteador=roteador,
        executor_ferramentas=registro,
        modelo_padrao="modelo-loop",
    )

    config = ConfiguracaoAgente(
        nome="agente-loop",
        instrucao_sistema="Loop",
        limite_passos=2,  # Limite restrito para teste
    )

    resultado = await orquestrador.executar(
        objetivo="Fique em loop", configuracao=config
    )
    assert resultado.sucesso is False
    assert "Limite de 2 passos atingido" in (resultado.erro or "")
