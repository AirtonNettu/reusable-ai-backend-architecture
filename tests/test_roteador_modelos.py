"""Testes para o roteador de modelos e catálogo inteligente."""

import pytest
from ai_core.adaptadores.provedores.simulado import AdaptadorSimulado
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.dominio.modelos.geracao import RequisicaoGeracao
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.dominio.modelos.modelo import (
    CriterioSelecaoModelo,
    InformacoesModelo,
)


@pytest.mark.asyncio
async def test_roteador_selecao_e_execucao() -> None:
    """Verifica seleção por critérios e chamada através do roteador."""
    roteador = RoteadorModelos()

    p_rapido = AdaptadorSimulado(
        nome_provedor="simulado-rapido",
        modelos_suportados=("mod-rapido",),
        resposta_padrao="Resposta rápida",
    )
    p_inteligente = AdaptadorSimulado(
        nome_provedor="simulado-inteligente",
        modelos_suportados=("mod-inteligente",),
        resposta_padrao="Resposta inteligente",
    )

    roteador.registrar_provedor(p_rapido)
    roteador.registrar_provedor(p_inteligente)

    roteador.registrar_modelo(
        InformacoesModelo(
            identificador="mod-rapido",
            nome_exibicao="Modelo Rápido",
            provedor="simulado-rapido",
            capacidades=("texto", "streaming"),
            limite_contexto=2048,
        )
    )
    roteador.registrar_modelo(
        InformacoesModelo(
            identificador="mod-inteligente",
            nome_exibicao="Modelo Inteligente",
            provedor="simulado-inteligente",
            capacidades=("texto", "ferramentas", "visao"),
            limite_contexto=32768,
        )
    )

    # Seleção por critério: exige ferramentas
    criterio = CriterioSelecaoModelo(capacidades_obrigatorias=("ferramentas",))
    selecionado = roteador.selecionar_modelo(criterio)
    assert selecionado.identificador == "mod-inteligente"

    # Execução através do modelo
    req = RequisicaoGeracao(
        modelo="mod-rapido",
        mensagens=(Mensagem(papel="usuario", conteudo="Oi"),),
    )
    resposta = await roteador.gerar(req)
    assert resposta.texto == "Resposta rápida"


@pytest.mark.asyncio
async def test_roteador_fallback_automatico() -> None:
    """Verifica fallback para segundo modelo se o primeiro falhar."""
    roteador = RoteadorModelos()

    p_falho = AdaptadorSimulado(
        nome_provedor="falho",
        modelos_suportados=("mod-falho",),
        excecao_para_lancar=ConnectionError("Falha no servidor"),
    )
    p_ok = AdaptadorSimulado(
        nome_provedor="ok",
        modelos_suportados=("mod-ok",),
        resposta_padrao="Recuperado com sucesso no fallback",
    )

    roteador.registrar_provedor(p_falho)
    roteador.registrar_provedor(p_ok)

    req = RequisicaoGeracao(
        modelo="mod-falho",
        mensagens=(Mensagem(papel="usuario", conteudo="Oi"),),
    )

    resposta = await roteador.gerar(req, modelos_fallback=("mod-ok",))
    assert resposta.texto == "Recuperado com sucesso no fallback"
