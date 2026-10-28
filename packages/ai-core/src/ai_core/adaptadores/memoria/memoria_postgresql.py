"""Implementação assíncrona de persistência de memória conversacional em PostgreSQL com pool e isolamento multilocatário."""

import json
from collections.abc import Sequence
from typing import Any, Protocol

from ai_core.dominio.excecoes import ErroAcessoNaoAutorizadoConversa, ErroValidacao
from ai_core.dominio.modelos.ferramenta import ChamadaFerramenta
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.dominio.portas.porta_memoria import PortaRepositorioMemoria


class TransacaoAssincrona(Protocol):
    """Protocolo abstrato para gerenciamento de transações de banco."""

    async def __aenter__(self) -> Any: ...
    async def __aexit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> Any: ...


class ConexaoPostgresAssincrona(Protocol):
    """Protocolo abstrato de conexão individual assíncrona."""

    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> Sequence[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    def transaction(self) -> TransacaoAssincrona: ...


class PoolPostgresAssincrono(Protocol):
    """Protocolo para pool de conexões assíncronas do PostgreSQL."""

    def acquire(self) -> Any: ...
    async def close(self) -> None: ...


# Migrações versionadas e idempotentes do esquema PostgreSQL
MIGRACOES_POSTGRESQL: tuple[tuple[int, str, str], ...] = (
    (
        1,
        "001_criar_tabela_conversas_proprietarios",
        """
        CREATE TABLE IF NOT EXISTS conversas_proprietarios (
            id_conversa VARCHAR(128) PRIMARY KEY,
            id_usuario VARCHAR(128) NOT NULL,
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """,
    ),
    (
        2,
        "002_criar_tabela_mensagens_conversa",
        """
        CREATE TABLE IF NOT EXISTS mensagens_conversa (
            id BIGSERIAL PRIMARY KEY,
            id_conversa VARCHAR(128) NOT NULL,
            id_usuario VARCHAR(128),
            papel VARCHAR(32) NOT NULL,
            conteudo TEXT NOT NULL,
            nome VARCHAR(128),
            metadados_json JSONB,
            chamadas_ferramentas_json JSONB,
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_pg_conversa_id ON mensagens_conversa (id_conversa, id);
        CREATE INDEX IF NOT EXISTS idx_pg_usuario ON mensagens_conversa (id_usuario);
        """,
    ),
)


class MemoriaPostgresql(PortaRepositorioMemoria):
    """Repositório conversacional corporativo persistido em PostgreSQL assíncrono com pool e multilocatário."""

    def __init__(
        self,
        pool_conexoes: PoolPostgresAssincrono | None = None,
        url_conexao: str | None = None,
        min_conexoes: int = 2,
        max_conexoes: int = 10,
        timeout_segundos: float = 15.0,
    ) -> None:
        self._pool = pool_conexoes
        self._url_conexao = url_conexao
        self._min_conexoes = min_conexoes
        self._max_conexoes = max_conexoes
        self._timeout_segundos = timeout_segundos
        self._migrado = False

    def _validar_id_conversa(self, id_conversa: str) -> None:
        """Valida a integridade e segurança do identificador da conversa."""
        if not id_conversa or not id_conversa.strip():
            raise ErroValidacao("O identificador de conversa não pode ser vazio.")
        if len(id_conversa) > 128:
            raise ErroValidacao(
                "O identificador de conversa excede o limite máximo de 128 caracteres."
            )
        if "\x00" in id_conversa:
            raise ErroValidacao(
                "O identificador de conversa contém caracteres nulos inválidos."
            )

    async def _obter_conexao(self) -> Any:
        """Adquire uma conexão ativa do pool configurado."""
        if self._pool is None:
            try:
                import asyncpg  # type: ignore

                self._pool = await asyncpg.create_pool(
                    dsn=self._url_conexao,
                    min_size=self._min_conexoes,
                    max_size=self._max_conexoes,
                    timeout=self._timeout_segundos,
                )
            except ImportError as err:
                raise RuntimeError(
                    "O driver 'asyncpg' é necessário para conexões diretas ao PostgreSQL. "
                    "Instale a dependência ou forneça um pool pré-configurado."
                ) from err
        return self._pool.acquire()

    async def fechar(self) -> None:
        """Encerra o pool de conexões com o PostgreSQL."""
        if self._pool is not None:
            await self._pool.close()

    async def executar_migracoes(self) -> None:
        """Aplica as migrações de esquema pendentes em transação atômica."""
        async with await self._obter_conexao() as conexao, conexao.transaction():
            await conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migracoes (
                    versao INT PRIMARY KEY,
                    nome VARCHAR(128) NOT NULL,
                    executado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            registros = await conexao.fetch(
                "SELECT versao FROM schema_migracoes ORDER BY versao ASC;"
            )
            versoes_executadas = {int(r["versao"]) for r in registros}

            for versao, nome, script_sql in MIGRACOES_POSTGRESQL:
                if versao not in versoes_executadas:
                    await conexao.execute(script_sql)
                    await conexao.execute(
                        "INSERT INTO schema_migracoes (versao, nome) VALUES ($1, $2);",
                        versao,
                        nome,
                    )

            self._migrado = True

    async def _checar_posse(
        self, conexao: Any, id_conversa: str, id_usuario: str | None
    ) -> None:
        """Assegura a titularidade da conversa prevenindo acessos cruzados (IDOR)."""
        linha = await conexao.fetchrow(
            "SELECT id_usuario FROM conversas_proprietarios WHERE id_conversa = $1;",
            id_conversa,
        )
        if linha is not None:
            proprietario = linha["id_usuario"]
            if id_usuario is not None and proprietario != id_usuario:
                raise ErroAcessoNaoAutorizadoConversa(
                    f"Acesso negado à conversa '{id_conversa}'. Ela pertence a outro usuário."
                )
            if id_usuario is None:
                raise ErroAcessoNaoAutorizadoConversa(
                    f"Acesso negado à conversa '{id_conversa}'. Usuário não autenticado para conversa privada."
                )

    async def salvar_mensagem(
        self, id_conversa: str, mensagem: Mensagem, id_usuario: str | None = None
    ) -> None:
        self._validar_id_conversa(id_conversa)

        metadados_str = json.dumps(mensagem.metadados, ensure_ascii=False)
        chamadas_lista = [
            {
                "identificador": cf.identificador,
                "nome_ferramenta": cf.nome_ferramenta,
                "argumentos": cf.argumentos,
            }
            for cf in mensagem.chamadas_ferramentas
        ]
        chamadas_str = json.dumps(chamadas_lista, ensure_ascii=False)

        async with await self._obter_conexao() as conexao, conexao.transaction():
            await self._checar_posse(conexao, id_conversa, id_usuario)

            if id_usuario is not None:
                await conexao.execute(
                    """
                    INSERT INTO conversas_proprietarios (id_conversa, id_usuario)
                    VALUES ($1, $2)
                    ON CONFLICT (id_conversa) DO NOTHING;
                    """,
                    id_conversa,
                    id_usuario,
                )

            await conexao.execute(
                """
                INSERT INTO mensagens_conversa (
                    id_conversa, id_usuario, papel, conteudo, nome, metadados_json, chamadas_ferramentas_json
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb);
                """,
                id_conversa,
                id_usuario,
                mensagem.papel,
                mensagem.conteudo,
                mensagem.nome,
                metadados_str,
                chamadas_str,
            )

    async def recuperar_historico(
        self,
        id_conversa: str,
        limite: int | None = None,
        id_usuario: str | None = None,
    ) -> tuple[Mensagem, ...]:
        self._validar_id_conversa(id_conversa)

        async with await self._obter_conexao() as conexao:
            await self._checar_posse(conexao, id_conversa, id_usuario)

            consulta = """
                SELECT papel, conteudo, nome, metadados_json, chamadas_ferramentas_json
                FROM mensagens_conversa
                WHERE id_conversa = $1
                ORDER BY id ASC;
            """
            linhas = await conexao.fetch(consulta, id_conversa)

        if limite is not None and limite > 0:
            linhas = linhas[-limite:]

        mensagens: list[Mensagem] = []
        for l in linhas:
            m_raw = l["metadados_json"]
            metadados = json.loads(m_raw) if isinstance(m_raw, str) else (m_raw or {})

            cf_raw = l["chamadas_ferramentas_json"]
            chamadas_brutas = (
                json.loads(cf_raw) if isinstance(cf_raw, str) else (cf_raw or [])
            )

            chamadas = tuple(
                ChamadaFerramenta(
                    identificador=c["identificador"],
                    nome_ferramenta=c["nome_ferramenta"],
                    argumentos=c["argumentos"],
                )
                for c in chamadas_brutas
            )

            mensagens.append(
                Mensagem(
                    papel=l["papel"],
                    conteudo=l["conteudo"],
                    nome=l["nome"],
                    metadados=metadados,
                    chamadas_ferramentas=chamadas,
                )
            )

        return tuple(mensagens)

    async def limpar_historico(
        self, id_conversa: str, id_usuario: str | None = None
    ) -> None:
        self._validar_id_conversa(id_conversa)

        async with await self._obter_conexao() as conexao, conexao.transaction():
            await self._checar_posse(conexao, id_conversa, id_usuario)
            await conexao.execute(
                "DELETE FROM mensagens_conversa WHERE id_conversa = $1;",
                id_conversa,
            )
            await conexao.execute(
                "DELETE FROM conversas_proprietarios WHERE id_conversa = $1;",
                id_conversa,
            )
