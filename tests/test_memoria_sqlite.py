"""Testes para persistência conversacional com MemoriaSQLite."""

import os
import tempfile

import pytest
from ai_core.adaptadores.memoria.memoria_sqlite import MemoriaSQLite
from ai_core.dominio.modelos.ferramenta import ChamadaFerramenta
from ai_core.dominio.modelos.mensagem import Mensagem


@pytest.mark.asyncio
async def test_memoria_sqlite_em_memoria() -> None:
    """Verifica operações básicas no SQLite em memória (:memory:)."""
    memoria = MemoriaSQLite(caminho_banco=":memory:")
    id_conversa = "conv-sqlite-01"

    # Salva mensagens
    msg1 = Mensagem(papel="usuario", conteudo="Primeira mensagem")
    msg2 = Mensagem(
        papel="assistente",
        conteudo="Chamando ferramenta",
        chamadas_ferramentas=(
            ChamadaFerramenta(
                identificador="call_1", nome_ferramenta="calc", argumentos={"a": 1}
            ),
        ),
    )
    msg3 = Mensagem(papel="usuario", conteudo="Segunda mensagem")

    await memoria.salvar_mensagem(id_conversa, msg1)
    await memoria.salvar_mensagem(id_conversa, msg2)
    await memoria.salvar_mensagem(id_conversa, msg3)

    # Recupera histórico total
    historico = await memoria.recuperar_historico(id_conversa)
    assert len(historico) == 3
    assert historico[0].conteudo == "Primeira mensagem"
    assert len(historico[1].chamadas_ferramentas) == 1
    assert historico[1].chamadas_ferramentas[0].nome_ferramenta == "calc"

    # Recupera com limite
    ultimas = await memoria.recuperar_historico(id_conversa, limite=2)
    assert len(ultimas) == 2
    assert ultimas[1].conteudo == "Segunda mensagem"

    # Limpeza
    await memoria.limpar_historico(id_conversa)
    assert len(await memoria.recuperar_historico(id_conversa)) == 0
    memoria.fechar()


@pytest.mark.asyncio
async def test_memoria_sqlite_arquivo_fisico() -> None:
    """Verifica persistência e reabertura de arquivo SQLite temporário."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as arquivo_temp:
        caminho = arquivo_temp.name

    memoria1: MemoriaSQLite | None = None
    memoria2: MemoriaSQLite | None = None

    try:
        memoria1 = MemoriaSQLite(caminho_banco=caminho)
        await memoria1.salvar_mensagem(
            "c-1", Mensagem(papel="usuario", conteudo="Persistido no disco")
        )
        memoria1.fechar()
        memoria1 = None

        # Nova instância apontando para o mesmo arquivo físico
        memoria2 = MemoriaSQLite(caminho_banco=caminho)
        historico = await memoria2.recuperar_historico("c-1")
        assert len(historico) == 1
        assert historico[0].conteudo == "Persistido no disco"
        memoria2.fechar()
        memoria2 = None
    finally:
        if memoria1:
            memoria1.fechar()
        if memoria2:
            memoria2.fechar()
        if os.path.exists(caminho):
            os.remove(caminho)
