"""Testes para memória conversacional e gerenciamento de contexto."""

import pytest
from ai_core.adaptadores.memoria.gerenciador_contexto import GerenciadorContexto
from ai_core.adaptadores.memoria.memoria_em_memoria import MemoriaEmMemoria
from ai_core.dominio.modelos.mensagem import Mensagem


@pytest.mark.asyncio
async def test_repositorio_memoria_em_memoria() -> None:
    """Verifica salvamento, recuperação e limpeza de histórico."""
    memoria = MemoriaEmMemoria()
    id_conversa = "conversa-123"

    await memoria.salvar_mensagem(
        id_conversa, Mensagem(papel="usuario", conteudo="Mensagem 1")
    )
    await memoria.salvar_mensagem(
        id_conversa, Mensagem(papel="assistente", conteudo="Resposta 1")
    )
    await memoria.salvar_mensagem(
        id_conversa, Mensagem(papel="usuario", conteudo="Mensagem 2")
    )

    historico = await memoria.recuperar_historico(id_conversa)
    assert len(historico) == 3

    ultimas_duas = await memoria.recuperar_historico(id_conversa, limite=2)
    assert len(ultimas_duas) == 2
    assert ultimas_duas[0].conteudo == "Resposta 1"
    assert ultimas_duas[1].conteudo == "Mensagem 2"

    await memoria.limpar_historico(id_conversa)
    vazio = await memoria.recuperar_historico(id_conversa)
    assert len(vazio) == 0


def test_gerenciador_contexto_janela_deslizante() -> None:
    """Verifica retenção obrigatória da mensagem de sistema e corte das mais antigas."""
    gerenciador = GerenciadorContexto(limite_maximo_tokens_padrao=100)

    msg_sistema = Mensagem(papel="sistema", conteudo="Você é um assistente conciso.")
    msg_1 = Mensagem(papel="usuario", conteudo="Mensagem muito antiga 1 " * 10)
    msg_2 = Mensagem(papel="assistente", conteudo="Resposta muito antiga 1 " * 10)
    msg_3 = Mensagem(papel="usuario", conteudo="Mensagem recente")

    mensagens = (msg_sistema, msg_1, msg_2, msg_3)

    # Limite pequeno o suficiente para forçar descarte de mensagens antigas
    ajustadas = gerenciador.ajustar_janela(mensagens, limite_tokens=35)

    # A mensagem de sistema DEVE estar presente
    assert ajustadas[0].papel == "sistema"
    assert ajustadas[0].conteudo == "Você é um assistente conciso."

    # A mensagem mais recente DEVE estar presente
    assert any(m.conteudo == "Mensagem recente" for m in ajustadas)

    # As mensagens intermediárias grandes foram podadas para respeitar o limite
    assert len(ajustadas) < len(mensagens)
