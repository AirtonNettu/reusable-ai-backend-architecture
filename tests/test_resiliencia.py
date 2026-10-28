"""Testes unitários para as políticas de resiliência e estabilidade."""

import asyncio

import pytest
from ai_core.dominio.excecoes import (
    ErroAutenticacaoProvedor,
    ErroDisjuntorAberto,
    ErroDominio,
)
from ai_core.resiliencia.disjuntor import Disjuntor
from ai_core.resiliencia.fallback import PoliticaFallback
from ai_core.resiliencia.limitador import (
    LimitadorTaxa,
    RastreadorConsumoTokens,
    SemaforoConcorrencia,
)
from ai_core.resiliencia.retentativa import PoliticaRetentativa


@pytest.mark.asyncio
async def test_disjuntor_transicao_estados() -> None:
    """Verifica abertura após falhas consecutivas e reabertura controlada."""
    disjuntor = Disjuntor(
        nome="teste-circuito",
        limite_falhas=2,
        tempo_recuperacao_segundos=0.1,
        limite_sucessos_meio_aberto=1,
    )

    async def _operacao_falha() -> str:
        raise ValueError("Falha na chamada externa")

    # Primeira falha: ainda fechado
    with pytest.raises(ValueError):
        await disjuntor.executar(_operacao_falha)
    assert disjuntor.estado == "fechado"

    # Segunda falha: abre o circuito
    with pytest.raises(ValueError):
        await disjuntor.executar(_operacao_falha)
    assert disjuntor.estado == "aberto"

    # Enquanto aberto: rejeição imediata com ErroDisjuntorAberto
    with pytest.raises(ErroDisjuntorAberto):
        await disjuntor.executar(lambda: asyncio.sleep(0.01))

    # Aguarda expirar tempo de recuperação
    await asyncio.sleep(0.12)

    # Operação bem-sucedida fecha novamente o circuito
    async def _operacao_sucesso() -> str:
        return "sucesso"

    resultado = await disjuntor.executar(_operacao_sucesso)
    assert resultado == "sucesso"
    assert disjuntor.estado == "fechado"


@pytest.mark.asyncio
async def test_politica_retentativa_sucesso_posterior() -> None:
    """Verifica repetição de chamada que tem sucesso na segunda tentativa."""
    politica = PoliticaRetentativa(
        max_tentativas=3,
        atraso_inicial_segundos=0.01,
        usar_jitter=False,
    )

    tentativas = 0

    async def _operacao_instavel() -> str:
        nonlocal tentativas
        tentativas += 1
        if tentativas < 2:
            raise ConnectionError("Instabilidade de rede")
        return "recuperado"

    resultado = await politica.executar(_operacao_instavel)
    assert resultado == "recuperado"
    assert tentativas == 2


@pytest.mark.asyncio
async def test_politica_retentativa_aborto_imediato_auth() -> None:
    """Erros de autenticação não devem sofrer retentativas inúteis."""
    politica = PoliticaRetentativa(max_tentativas=3, atraso_inicial_segundos=0.01)

    tentativas = 0

    async def _operacao_nao_autorizada() -> None:
        nonlocal tentativas
        tentativas += 1
        raise ErroAutenticacaoProvedor("Chave inválida", provedor="openai")

    with pytest.raises(ErroAutenticacaoProvedor):
        await politica.executar(_operacao_nao_autorizada)

    assert tentativas == 1


@pytest.mark.asyncio
async def test_politica_fallback_chaveamento() -> None:
    """Verifica se a política aciona a alternativa de retaguarda após falha primária."""
    fallback = PoliticaFallback()

    async def _primario() -> str:
        raise ConnectionError("Provedor primário inacessível")

    async def _secundario() -> str:
        return "resposta do fallback"

    resultado = await fallback.executar_com_retaguarda(
        [("primario", _primario), ("secundario", _secundario)]
    )

    assert resultado == "resposta do fallback"


@pytest.mark.asyncio
async def test_politica_fallback_todas_falham() -> None:
    """Quando todas as alternativas falham, lança ErroDominio detalhado."""
    fallback = PoliticaFallback()

    async def _f1() -> None:
        raise ValueError("erro 1")

    async def _f2() -> None:
        raise ValueError("erro 2")

    with pytest.raises(ErroDominio, match="Todas as alternativas de fallback falharam"):
        await fallback.executar_com_retaguarda([("f1", _f1), ("f2", _f2)])


@pytest.mark.asyncio
async def test_limitador_taxa_e_semaforo() -> None:
    """Valida aquisição de tokens e controle por semáforo."""
    limitador = LimitadorTaxa(taxa_por_segundo=100.0, capacidade_maxima=10)
    await limitador.adquirir(2)

    with pytest.raises(ValueError):
        await limitador.adquirir(15)  # Acima da capacidade total

    semaforo = SemaforoConcorrencia(limite_simultaneo=2)
    assert semaforo.limite == 2
    async with semaforo:
        pass


@pytest.mark.asyncio
async def test_rastreador_consumo_tokens() -> None:
    """Valida agregação de tokens por modelo."""
    rastreador = RastreadorConsumoTokens()
    await rastreador.registrar("gpt-4o", 100, 50)
    await rastreador.registrar("gpt-4o", 20, 10)
    await rastreador.registrar("claude", 30, 30)

    relatorio = await rastreador.obter_relatorio()
    assert relatorio["gpt-4o"]["tokens_entrada"] == 120
    assert relatorio["gpt-4o"]["tokens_saida"] == 60
    assert relatorio["gpt-4o"]["total_tokens"] == 180
    assert relatorio["claude"]["total_tokens"] == 60
