"""Testes para o compactador e sintetizador inteligente de contexto."""

import pytest
from ai_core.adaptadores.memoria.compactador_contexto import CompactadorContexto
from ai_core.adaptadores.provedores.simulado import AdaptadorSimulado
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.dominio.modelos.mensagem import Mensagem


@pytest.mark.asyncio
async def test_compactador_sem_necessidade_de_corte() -> None:
    """Quando o histórico não atinge o limiar, as mensagens devem permanecer intactas."""
    roteador = RoteadorModelos()
    compactador = CompactadorContexto(
        roteador=roteador,
        modelo_sumarizacao="modelo-teste",
        limiar_tokens_ativacao=500,
        manter_ultimas_mensagens=2,
    )

    mensagens = (
        Mensagem(papel="sistema", conteudo="Você é um assistente."),
        Mensagem(papel="usuario", conteudo="Olá!"),
        Mensagem(papel="assistente", conteudo="Oi!"),
    )

    resultado = await compactador.compactar(mensagens)
    assert len(resultado) == 3
    assert resultado == mensagens


@pytest.mark.asyncio
async def test_compactador_com_sumarizacao_ativa() -> None:
    """Quando excede o limiar, sintetiza as mensagens antigas em resumo de sistema."""
    provedor = AdaptadorSimulado(
        modelos_suportados=("mod-sumarizador",),
        resposta_padrao="O usuário discutiu tópicos iniciais do projeto.",
    )
    roteador = RoteadorModelos()
    roteador.registrar_provedor(provedor)

    compactador = CompactadorContexto(
        roteador=roteador,
        modelo_sumarizacao="mod-sumarizador",
        limiar_tokens_ativacao=20,  # Limiar baixo para forçar compactação
        manter_ultimas_mensagens=2,
    )

    mensagens = (
        Mensagem(papel="sistema", conteudo="Instrução mestre."),
        Mensagem(papel="usuario", conteudo="Mensagem longa antiga 1 " * 10),
        Mensagem(papel="assistente", conteudo="Resposta longa antiga 1 " * 10),
        Mensagem(papel="usuario", conteudo="Mensagem intermediária " * 10),
        Mensagem(papel="assistente", conteudo="Resposta recente"),
        Mensagem(papel="usuario", conteudo="Última mensagem do usuário"),
    )

    resultado = await compactador.compactar(mensagens)

    # Verifica estrutura do resultado:
    # 1. Instrução de sistema original
    assert resultado[0].papel == "sistema"
    assert resultado[0].conteudo == "Instrução mestre."

    # 2. Resumo da conversa anterior injetado como sistema
    assert resultado[1].papel == "sistema"
    assert "Contexto resumido da conversa anterior:" in resultado[1].conteudo
    assert "O usuário discutiu tópicos iniciais" in resultado[1].conteudo

    # 3. As duas últimas mensagens mantidas intactas
    assert resultado[-2].conteudo == "Resposta recente"
    assert resultado[-1].conteudo == "Última mensagem do usuário"
