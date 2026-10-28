"""Testes de integração física com banco PostgreSQL real (quando disponível no host).

Estes testes exercitam o banco de dados PostgreSQL real e são executados apenas quando
uma instância ativa do PostgreSQL for detectada ou fornecida via variável de ambiente.
Não substituem nem se confundem com os testes unitários com simulação.
"""

import os
import socket

import pytest
from ai_core.adaptadores.memoria.memoria_postgresql import MemoriaPostgresql
from ai_core.dominio.excecoes import ErroAcessoNaoAutorizadoConversa
from ai_core.dominio.modelos.mensagem import Mensagem

URL_POSTGRES_TESTE = os.getenv(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)


def postgres_real_disponivel() -> bool:
    """Verifica de forma rápida e não bloqueante se há uma porta de PostgreSQL aberta."""
    host = "localhost"
    porta = 5432
    try:
        with socket.create_connection((host, porta), timeout=0.5):
            return True
    except (OSError, TimeoutError):
        return False


pytestmark = pytest.mark.skipif(
    not postgres_real_disponivel(),
    reason="PostgreSQL real (porta 5432) indisponível no host local. "
    "Execute 'docker run -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:17-alpine' para habilitar.",
)


@pytest.fixture
async def repositorio_postgres_real():
    """Conecta ao PostgreSQL real, aplica migrações e fornece o repositório."""
    import importlib.util

    if importlib.util.find_spec("asyncpg") is None:
        pytest.skip("asyncpg não instalado.")

    repositorio = MemoriaPostgresql(
        url_conexao=URL_POSTGRES_TESTE,
        min_conexoes=1,
        max_conexoes=5,
    )
    await repositorio.executar_migracoes()
    yield repositorio
    await repositorio.fechar()


@pytest.mark.asyncio
async def test_fluxo_real_postgresql_e_isolamento(
    repositorio_postgres_real: MemoriaPostgresql,
) -> None:
    """Valida gravação, consulta e bloqueio multilocatário contra banco físico."""
    id_conversa = "conv_homologacao_real_01"

    msg = Mensagem(papel="usuario", conteudo="Teste em PostgreSQL real")
    await repositorio_postgres_real.salvar_mensagem(
        id_conversa=id_conversa,
        mensagem=msg,
        id_usuario="usuario_homologado",
    )

    # Leitura pelo titular
    historico = await repositorio_postgres_real.recuperar_historico(
        id_conversa=id_conversa,
        id_usuario="usuario_homologado",
    )
    assert len(historico) >= 1
    assert historico[-1].conteudo == "Teste em PostgreSQL real"

    # Tentativa de acesso indevido por outro usuário
    with pytest.raises(ErroAcessoNaoAutorizadoConversa):
        await repositorio_postgres_real.recuperar_historico(
            id_conversa=id_conversa,
            id_usuario="usuario_invasor",
        )

    # Limpeza
    await repositorio_postgres_real.limpar_historico(
        id_conversa=id_conversa, id_usuario="usuario_homologado"
    )
