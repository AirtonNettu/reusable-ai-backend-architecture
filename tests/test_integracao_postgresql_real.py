"""Testes de integração física com banco PostgreSQL real.

Estes testes exercitam o banco de dados PostgreSQL real e são executados quando
uma instância ativa do PostgreSQL for detectada ou exigida obrigatoriamente via
variável de ambiente POSTGRES_OBRIGATORIO=true (ex: pipeline de CI).
Não substituem nem se confundem com os testes unitários com simulação.
"""

import asyncio
import os
import socket
import urllib.parse

import pytest
import pytest_asyncio
from ai_core.adaptadores.memoria.memoria_postgresql import MemoriaPostgresql
from ai_core.dominio.excecoes import ErroAcessoNaoAutorizadoConversa
from ai_core.dominio.modelos.mensagem import Mensagem

URL_POSTGRES_TESTE = os.getenv(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)
POSTGRES_OBRIGATORIO = os.getenv("POSTGRES_OBRIGATORIO", "false").lower() in (
    "true",
    "1",
    "sim",
)


def postgres_real_disponivel() -> bool:
    """Verifica de forma rápida e não bloqueante se o endpoint PostgreSQL configurado está acessível."""
    parsed = urllib.parse.urlsplit(URL_POSTGRES_TESTE)
    host = parsed.hostname or "localhost"
    porta = parsed.port or 5432
    try:
        with socket.create_connection((host, porta), timeout=0.8):
            return True
    except (OSError, TimeoutError):
        return False


def _avaliar_condicao_skip() -> bool:
    """Se POSTGRES_OBRIGATORIO for ativado, o teste não deve ser ignorado silenciosamente."""
    if POSTGRES_OBRIGATORIO:
        return False
    return not postgres_real_disponivel()


pytestmark = pytest.mark.skipif(
    _avaliar_condicao_skip(),
    reason=(
        "PostgreSQL real indisponível no host local e POSTGRES_OBRIGATORIO não está ativo. "
        "Execute 'docker run -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:17-alpine' "
        "ou ative POSTGRES_OBRIGATORIO=true no ambiente de CI."
    ),
)


@pytest_asyncio.fixture(loop_scope="function")
async def repositorio_postgres_real():
    """Conecta ao PostgreSQL real, aplica migrações e fornece o repositório para o ciclo de teste."""
    if not postgres_real_disponivel():
        if POSTGRES_OBRIGATORIO:
            pytest.fail(
                f"PostgreSQL real é obrigatório (POSTGRES_OBRIGATORIO=true) em {URL_POSTGRES_TESTE}, "
                "mas a conexão com o banco físico falhou."
            )
        else:
            pytest.skip("PostgreSQL real indisponível.")

    repositorio = MemoriaPostgresql(
        url_conexao=URL_POSTGRES_TESTE,
        min_conexoes=2,
        max_conexoes=10,
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
    id_usuario_titular = "usuario_homologado_01"
    id_usuario_invasor = "usuario_invasor_02"

    msg = Mensagem(papel="usuario", conteudo="Teste de gravação em PostgreSQL 17 real")
    await repositorio_postgres_real.salvar_mensagem(
        id_conversa=id_conversa,
        mensagem=msg,
        id_usuario=id_usuario_titular,
    )

    # Leitura autorizada pelo titular
    historico = await repositorio_postgres_real.recuperar_historico(
        id_conversa=id_conversa,
        id_usuario=id_usuario_titular,
    )
    assert len(historico) >= 1
    assert historico[-1].conteudo == "Teste de gravação em PostgreSQL 17 real"

    # Tentativa de acesso indevido por outro usuário (IDOR bloqueado)
    with pytest.raises(ErroAcessoNaoAutorizadoConversa):
        await repositorio_postgres_real.recuperar_historico(
            id_conversa=id_conversa,
            id_usuario=id_usuario_invasor,
        )

    # Limpeza dos dados de teste
    await repositorio_postgres_real.limpar_historico(
        id_conversa=id_conversa, id_usuario=id_usuario_titular
    )

    # Confirmação de exclusão
    historico_apos_limpeza = await repositorio_postgres_real.recuperar_historico(
        id_conversa=id_conversa,
        id_usuario=id_usuario_titular,
    )
    assert len(historico_apos_limpeza) == 0


@pytest.mark.asyncio
async def test_transacoes_e_rollback_postgresql_real(
    repositorio_postgres_real: MemoriaPostgresql,
) -> None:
    """Valida que falhas durante uma transação resultam em rollback sem efeitos colaterais residuais."""
    id_conversa = "conv_rollback_01"
    id_usuario = "usuario_transacao"

    # Salva mensagem inicial com sucesso
    msg1 = Mensagem(papel="usuario", conteudo="Mensagem consolidada")
    await repositorio_postgres_real.salvar_mensagem(
        id_conversa=id_conversa,
        mensagem=msg1,
        id_usuario=id_usuario,
    )

    # Executa bloco com erro forçado sob conexão direta
    conexao_pool = await repositorio_postgres_real._obter_conexao()
    try:
        async with conexao_pool as conexao:
            try:
                async with conexao.transaction():
                    await conexao.execute(
                        """
                        INSERT INTO mensagens_conversa (id_conversa, id_usuario, papel, conteudo)
                        VALUES ($1, $2, $3, $4);
                        """,
                        id_conversa,
                        id_usuario,
                        "assistente",
                        "Mensagem a ser desfeita",
                    )
                    # Força erro de banco ou exceção no bloco transacional
                    raise RuntimeError("Erro proposital para disparar rollback")
            except RuntimeError:
                pass
    finally:
        pass

    # Verifica que a mensagem do bloco com rollback não persiste
    historico = await repositorio_postgres_real.recuperar_historico(
        id_conversa=id_conversa,
        id_usuario=id_usuario,
    )
    assert len(historico) == 1
    assert historico[0].conteudo == "Mensagem consolidada"

    # Limpeza
    await repositorio_postgres_real.limpar_historico(
        id_conversa=id_conversa, id_usuario=id_usuario
    )


@pytest.mark.asyncio
async def test_concorrencia_massiva_postgresql_real(
    repositorio_postgres_real: MemoriaPostgresql,
) -> None:
    """Valida inserções simultâneas em conversas independentes de múltiplos usuários em paralelo."""

    async def _operacao_usuario(indice: int) -> None:
        conv = f"conv_conc_{indice}"
        usr = f"usr_{indice}"
        msg = Mensagem(papel="usuario", conteudo=f"Conteudo concorrente {indice}")
        await repositorio_postgres_real.salvar_mensagem(
            id_conversa=conv,
            mensagem=msg,
            id_usuario=usr,
        )
        hist = await repositorio_postgres_real.recuperar_historico(
            id_conversa=conv,
            id_usuario=usr,
        )
        assert len(hist) == 1
        assert hist[0].conteudo == f"Conteudo concorrente {indice}"
        await repositorio_postgres_real.limpar_historico(
            id_conversa=conv,
            id_usuario=usr,
        )

    # Dispara 15 operações simultâneas
    tarefas = [_operacao_usuario(i) for i in range(15)]
    await asyncio.gather(*tarefas)


@pytest.mark.asyncio
async def test_idempotencia_migracoes_postgresql_real(
    repositorio_postgres_real: MemoriaPostgresql,
) -> None:
    """Valida que invocar as migrações múltiplas vezes consecutivas é seguro e idempotente."""
    # Executa as migrações novamente
    await repositorio_postgres_real.executar_migracoes()
    await repositorio_postgres_real.executar_migracoes()

    # Confirma que a tabela de controle de migrações contém as versões registradas sem duplicação
    conexao_pool = await repositorio_postgres_real._obter_conexao()
    async with conexao_pool as conexao:
        registros = await conexao.fetch(
            "SELECT versao FROM schema_migracoes ORDER BY versao;"
        )
        versoes = [r["versao"] for r in registros]
        assert len(versoes) == len(set(versoes)), (
            "Versões duplicadas no schema_migracoes"
        )
