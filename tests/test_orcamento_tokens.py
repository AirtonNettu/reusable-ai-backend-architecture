"""Testes para limitação orçamentária de tokens e custos de LLM."""

import pytest
from ai_core.adaptadores.provedores.simulado import AdaptadorSimulado
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.aplicacao.casos_de_uso.caso_gerar_resposta import CasoDeUsoGerarResposta
from ai_core.dominio.modelos.geracao import RequisicaoGeracao
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.resiliencia.orcamento import (
    ErroDominio,
    ErroLimiteOrcamentoTokens,
    PoliticaOrcamentoTokens,
)


@pytest.mark.asyncio
async def test_orcamento_limite_individual_por_requisicao() -> None:
    """Verifica bloqueio quando a requisição estimada excede o teto permitido."""
    politica = PoliticaOrcamentoTokens(limite_tokens_por_requisicao=50)

    # Requisição pequena: permitida
    await politica.verificar_pre_requisicao(30)

    # Requisição grande: bloqueada com ErroLimiteOrcamentoTokens
    with pytest.raises(ErroLimiteOrcamentoTokens, match="excede o teto permitido"):
        await politica.verificar_pre_requisicao(80)


@pytest.mark.asyncio
async def test_orcamento_limite_acumulado_sessao() -> None:
    """Verifica bloqueio quando o total acumulado estoura o orçamento da sessão."""
    politica = PoliticaOrcamentoTokens(
        limite_tokens_por_requisicao=100,
        limite_tokens_total_sessao=150,
    )

    await politica.verificar_pre_requisicao(50)
    await politica.registrar_consumo_real(60)

    await politica.verificar_pre_requisicao(70)
    await politica.registrar_consumo_real(70)
    # Total acumulado atual: 130 tokens

    # Nova estimativa de 30 tokens levaria a 160 > 150 -> bloqueado
    with pytest.raises(ErroLimiteOrcamentoTokens, match="orçamento da sessão"):
        await politica.verificar_pre_requisicao(30)


@pytest.mark.asyncio
async def test_orcamento_integrado_ao_caso_de_uso() -> None:
    """Valida bloqueio automático de execução dentro do CasoDeUsoGerarResposta."""
    roteador = RoteadorModelos()
    provedor = AdaptadorSimulado(modelos_suportados=("mod-teste",))
    roteador.registrar_provedor(provedor)

    politica = PoliticaOrcamentoTokens(limite_tokens_por_requisicao=5)
    caso_uso = CasoDeUsoGerarResposta(
        roteador=roteador,
        politica_orcamento=politica,
    )

    # Mensagem grande (> 5 tokens estimados)
    req = RequisicaoGeracao(
        modelo="mod-teste",
        mensagens=(
            Mensagem(
                papel="usuario",
                conteudo="Esta é uma mensagem intencionalmente longa com muitos caracteres para gerar vários tokens.",
            ),
        ),
    )

    with pytest.raises(ErroLimiteOrcamentoTokens):
        await caso_uso.executar(req)


@pytest.mark.asyncio
async def test_orcamento_limite_individual_por_usuario() -> None:
    """Valida bloqueio quando o consumo de um usuário específico estoura o limite individual."""
    politica = PoliticaOrcamentoTokens(
        limite_tokens_por_usuario=100,
    )

    # Usuário 1 consome 70 tokens
    await politica.verificar_pre_requisicao(50, id_usuario="usr_alpha")
    await politica.registrar_consumo_real(70, id_usuario="usr_alpha")

    # Usuário 2 consome 50 tokens (permitido, cota independente)
    await politica.verificar_pre_requisicao(50, id_usuario="usr_beta")
    await politica.registrar_consumo_real(50, id_usuario="usr_beta")

    # Usuário 1 tenta mais 40 tokens (70 + 40 = 110 > 100) -> bloqueado
    with pytest.raises(ErroLimiteOrcamentoTokens, match="excede o teto individual"):
        await politica.verificar_pre_requisicao(40, id_usuario="usr_alpha")

    # Usuário 2 ainda pode consumir 30 tokens (50 + 30 = 80 <= 100)
    await politica.verificar_pre_requisicao(30, id_usuario="usr_beta")
    assert await politica.obter_tokens_usuario("usr_alpha") == 70
    assert await politica.obter_tokens_usuario("usr_beta") == 50


@pytest.mark.asyncio
async def test_reserva_duas_fases_bloqueia_concorrencia_excessiva() -> None:
    """Verifica bloqueio atômico quando requisições concorrentes somadas ultrapassam a cota."""
    politica = PoliticaOrcamentoTokens(
        limite_tokens_por_usuario=100,
    )

    # Requisição 1 reserva 60 tokens
    reserva_1 = await politica.reservar_tokens(60, id_usuario="usuario_concorrente")
    assert reserva_1.tokens_estimados == 60
    assert await politica.obter_tokens_reservados_usuario("usuario_concorrente") == 60

    # Requisição 2 em paralelo tenta reservar 50 tokens (60 + 50 = 110 > 100) -> bloqueada
    with pytest.raises(ErroLimiteOrcamentoTokens, match="excede o teto individual"):
        await politica.reservar_tokens(50, id_usuario="usuario_concorrente")

    # Requisição 1 conclui com sucesso consumindo 55 tokens
    await politica.confirmar_reserva(reserva_1.id_reserva, tokens_reais=55)

    assert await politica.obter_tokens_reservados_usuario("usuario_concorrente") == 0
    assert await politica.obter_tokens_usuario("usuario_concorrente") == 55

    # Agora uma nova requisição de 40 tokens é aceita (55 + 40 = 95 <= 100)
    reserva_3 = await politica.reservar_tokens(40, id_usuario="usuario_concorrente")
    assert reserva_3.tokens_estimados == 40


@pytest.mark.asyncio
async def test_cancelamento_reserva_apos_falha_de_provedor() -> None:
    """Valida liberação automática da cota reservada quando a execução do provedor falha."""
    from ai_core.dominio.excecoes import ErroConexaoProvedor
    from ai_core.dominio.modelos.geracao import RequisicaoGeracao

    roteador = RoteadorModelos()

    # Provedor que sempre falha com erro irrecuperável
    class ProvedorComFalha(AdaptadorSimulado):
        async def gerar(
            self, requisicao: RequisicaoGeracao, timeout_segundos: float = 30.0
        ):
            raise ErroConexaoProvedor(
                "Falha de rede com provedor externo.", provedor="falho"
            )

    roteador.registrar_provedor(ProvedorComFalha(modelos_suportados=("mod-falho",)))

    politica = PoliticaOrcamentoTokens(limite_tokens_por_usuario=100)
    caso_uso = CasoDeUsoGerarResposta(
        roteador=roteador,
        politica_orcamento=politica,
    )

    req = RequisicaoGeracao(
        modelo="mod-falho",
        mensagens=(Mensagem(papel="usuario", conteudo="Mensagem de teste com falha"),),
    )

    # Execução deve falhar e liberar a reserva
    with pytest.raises(ErroDominio):
        await caso_uso.executar(req, id_usuario="usr_resiliente")

    # A reserva deve ter sido cancelada e os tokens reservados zerados
    assert await politica.obter_tokens_reservados_usuario("usr_resiliente") == 0
    assert await politica.obter_tokens_usuario("usr_resiliente") == 0


@pytest.mark.asyncio
async def test_reconciliacao_quando_provedor_falha_com_consumo_faturado() -> None:
    """Diferencia falha pura de rede (zero custo) de falha interrompida com faturamento parcial pelo provedor."""
    from ai_core.dominio.excecoes import ErroProvedor

    roteador = RoteadorModelos()

    class ProvedorComFaturamentoParcial(AdaptadorSimulado):
        async def gerar(
            self, requisicao: RequisicaoGeracao, timeout_segundos: float = 30.0
        ):
            # Provedor gerou parte do texto mas parou por violação de política, cobrando 25 tokens
            raise ErroProvedor(
                "Geração abortada por filtro de conteúdo.",
                provedor="parcial",
                tokens_faturados=25,
            )

    roteador.registrar_provedor(
        ProvedorComFaturamentoParcial(modelos_suportados=("mod-parcial",))
    )

    politica = PoliticaOrcamentoTokens(limite_tokens_por_usuario=100)
    caso_uso = CasoDeUsoGerarResposta(
        roteador=roteador,
        politica_orcamento=politica,
    )

    req = RequisicaoGeracao(
        modelo="mod-parcial",
        mensagens=(
            Mensagem(
                papel="usuario", conteudo="Geração que causará interrupção parcial"
            ),
        ),
    )

    with pytest.raises(ErroDominio):
        await caso_uso.executar(req, id_usuario="usr_faturado")

    # A reserva estimada foi convertida nos 25 tokens efetivamente consumidos e faturados
    assert await politica.obter_tokens_reservados_usuario("usr_faturado") == 0
    assert await politica.obter_tokens_usuario("usr_faturado") == 25
