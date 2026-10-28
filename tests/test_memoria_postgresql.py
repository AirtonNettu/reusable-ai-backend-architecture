"""Testes para o adaptador de memória conversacional persistida em PostgreSQL assíncrono."""

from typing import Any

import pytest
from ai_core.adaptadores.memoria.memoria_postgresql import (
    MIGRACOES_POSTGRESQL,
    MemoriaPostgresql,
)
from ai_core.dominio.excecoes import ErroAcessoNaoAutorizadoConversa, ErroValidacao
from ai_core.dominio.modelos.ferramenta import ChamadaFerramenta
from ai_core.dominio.modelos.mensagem import Mensagem


class TransacaoSimulada:
    """Simula um contexto de transação assíncrona ACID."""

    def __init__(self, conexao: "ConexaoPostgresSimulada") -> None:
        self._conexao = conexao

    async def __aenter__(self) -> "ConexaoPostgresSimulada":
        return self._conexao

    async def __aexit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> None:
        pass


class ConexaoPostgresSimulada:
    """Simulador de conexão assíncrona PostgreSQL para testes unitários isolados e determinísticos."""

    def __init__(self, estado_compartilhado: dict[str, Any]) -> None:
        self._estado = estado_compartilhado

    def transaction(self) -> TransacaoSimulada:
        return TransacaoSimulada(self)

    async def execute(self, query: str, *args: Any) -> str:
        q = query.strip()
        if "CREATE TABLE" in q or "CREATE INDEX" in q:
            return "CREATE"

        if "INSERT INTO schema_migracoes" in q:
            versao, nome = args[0], args[1]
            self._estado["migracoes"].append({"versao": versao, "nome": nome})
            return "INSERT 0 1"

        if "INSERT INTO conversas_proprietarios" in q:
            id_conversa, id_usuario = args[0], args[1]
            if id_conversa not in self._estado["proprietarios"]:
                self._estado["proprietarios"][id_conversa] = id_usuario
            return "INSERT 0 1"

        if "INSERT INTO mensagens_conversa" in q:
            id_conversa = args[0]
            id_usuario = args[1]
            papel = args[2]
            conteudo = args[3]
            nome = args[4]
            metadados_json = args[5]
            chamadas_json = args[6]

            self._estado["mensagens"].append(
                {
                    "id": len(self._estado["mensagens"]) + 1,
                    "id_conversa": id_conversa,
                    "id_usuario": id_usuario,
                    "papel": papel,
                    "conteudo": conteudo,
                    "nome": nome,
                    "metadados_json": metadados_json,
                    "chamadas_ferramentas_json": chamadas_json,
                }
            )
            return "INSERT 0 1"

        if "DELETE FROM mensagens_conversa" in q:
            id_conversa = args[0]
            self._estado["mensagens"] = [
                m for m in self._estado["mensagens"] if m["id_conversa"] != id_conversa
            ]
            return "DELETE"

        if "DELETE FROM conversas_proprietarios" in q:
            id_conversa = args[0]
            self._estado["proprietarios"].pop(id_conversa, None)
            return "DELETE"

        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        q = query.strip()
        if "SELECT versao FROM schema_migracoes" in q:
            return self._estado["migracoes"]

        if "SELECT papel, conteudo, nome" in q:
            id_conversa = args[0]
            return [
                m for m in self._estado["mensagens"] if m["id_conversa"] == id_conversa
            ]

        return []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = query.strip()
        if "SELECT id_usuario FROM conversas_proprietarios" in q:
            id_conversa = args[0]
            prop = self._estado["proprietarios"].get(id_conversa)
            if prop is not None:
                return {"id_usuario": prop}
            return None
        return None


class PoolPostgresSimulado:
    """Simula um pool com controle de limite de conexões e gerenciamento de contexto."""

    def __init__(self) -> None:
        self._estado: dict[str, Any] = {
            "migracoes": [],
            "proprietarios": {},
            "mensagens": [],
        }

    class ContextoConexao:
        def __init__(self, pool: "PoolPostgresSimulado") -> None:
            self._pool = pool

        async def __aenter__(self) -> ConexaoPostgresSimulada:
            return ConexaoPostgresSimulada(self._pool._estado)

        async def __aexit__(
            self, exc_type: object, exc_val: object, exc_tb: object
        ) -> None:
            pass

    def acquire(self) -> ContextoConexao:
        return self.ContextoConexao(self)

    async def close(self) -> None:
        pass


@pytest.fixture
def repositorio_pg() -> MemoriaPostgresql:
    """Instancia a memória PostgreSQL integrada ao simulador de pool."""
    pool = PoolPostgresSimulado()
    return MemoriaPostgresql(pool_conexoes=pool)


@pytest.mark.asyncio
async def test_migracoes_versionadas_postgresql_idempotentes(
    repositorio_pg: MemoriaPostgresql,
) -> None:
    """Verifica execução de migrações e garantia de não reexecutar migrações já aplicadas."""
    await repositorio_pg.executar_migracoes()

    pool: PoolPostgresSimulado = repositorio_pg._pool  # type: ignore
    assert len(pool._estado["migracoes"]) == len(MIGRACOES_POSTGRESQL)

    # Executa novamente: deve ser idempotente
    await repositorio_pg.executar_migracoes()
    assert len(pool._estado["migracoes"]) == len(MIGRACOES_POSTGRESQL)


@pytest.mark.asyncio
async def test_salvar_e_recuperar_historico_postgresql(
    repositorio_pg: MemoriaPostgresql,
) -> None:
    """Valida gravação e recuperação cronológica com ferramentas e metadados."""
    await repositorio_pg.executar_migracoes()

    chamada = ChamadaFerramenta(
        identificador="call_1",
        nome_ferramenta="calcular_rota",
        argumentos={"origem": "SP", "destino": "RJ"},
    )
    mensagem_envio = Mensagem(
        papel="assistente",
        conteudo="Calculando rota",
        chamadas_ferramentas=(chamada,),
        metadados={"origem": "gps"},
    )

    await repositorio_pg.salvar_mensagem(
        id_conversa="conv_pg_01",
        mensagem=mensagem_envio,
        id_usuario="usuario_caminhoneiro",
    )

    historico = await repositorio_pg.recuperar_historico(
        id_conversa="conv_pg_01",
        id_usuario="usuario_caminhoneiro",
    )

    assert len(historico) == 1
    assert historico[0].papel == "assistente"
    assert historico[0].conteudo == "Calculando rota"
    assert len(historico[0].chamadas_ferramentas) == 1
    assert historico[0].chamadas_ferramentas[0].nome_ferramenta == "calcular_rota"


@pytest.mark.asyncio
async def test_isolamento_multilocatario_postgresql_bloqueia_acesso_cruzado(
    repositorio_pg: MemoriaPostgresql,
) -> None:
    """Verifica que o adaptador PostgreSQL impede acesso cruzado entre usuários (IDOR)."""
    await repositorio_pg.executar_migracoes()

    msg = Mensagem(papel="usuario", conteudo="Segredo empresarial")
    await repositorio_pg.salvar_mensagem(
        id_conversa="conv_confidencial",
        mensagem=msg,
        id_usuario="diretor_executivo",
    )

    # Usuário não autorizado tenta ler
    with pytest.raises(
        ErroAcessoNaoAutorizadoConversa, match="pertence a outro usuário"
    ):
        await repositorio_pg.recuperar_historico(
            id_conversa="conv_confidencial",
            id_usuario="funcionario_curioso",
        )

    # Usuário não autenticado tenta ler
    with pytest.raises(ErroAcessoNaoAutorizadoConversa, match="não autenticado"):
        await repositorio_pg.recuperar_historico(
            id_conversa="conv_confidencial",
            id_usuario=None,
        )


@pytest.mark.asyncio
async def test_limpar_historico_postgresql(
    repositorio_pg: MemoriaPostgresql,
) -> None:
    """Verifica exclusão segura do histórico e liberação do identificador da conversa."""
    await repositorio_pg.executar_migracoes()

    msg = Mensagem(papel="usuario", conteudo="Mensagem temporária")
    await repositorio_pg.salvar_mensagem(
        id_conversa="conv_temp",
        mensagem=msg,
        id_usuario="usuario_temp",
    )

    assert (
        len(
            await repositorio_pg.recuperar_historico(
                "conv_temp", id_usuario="usuario_temp"
            )
        )
        == 1
    )

    await repositorio_pg.limpar_historico("conv_temp", id_usuario="usuario_temp")

    assert (
        len(
            await repositorio_pg.recuperar_historico(
                "conv_temp", id_usuario="usuario_temp"
            )
        )
        == 0
    )


@pytest.mark.asyncio
async def test_validacao_id_conversa_invalido_postgresql(
    repositorio_pg: MemoriaPostgresql,
) -> None:
    """Verifica bloqueio de identificadores maliciosos ou vazios no PostgreSQL."""
    msg = Mensagem(papel="usuario", conteudo="Teste")

    with pytest.raises(ErroValidacao, match="não pode ser vazio"):
        await repositorio_pg.salvar_mensagem("", msg)

    with pytest.raises(ErroValidacao, match="caracteres nulos"):
        await repositorio_pg.salvar_mensagem("conversa\x00maliciosa", msg)
