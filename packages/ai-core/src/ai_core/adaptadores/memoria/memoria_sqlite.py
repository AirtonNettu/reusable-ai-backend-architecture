"""Implementação de persistência de memória conversacional em SQLite com suporte a concorrência e multilocatário."""

import asyncio
import json
import sqlite3
import threading
from typing import Any

from ai_core.dominio.excecoes import ErroAcessoNaoAutorizadoConversa, ErroValidacao
from ai_core.dominio.modelos.ferramenta import ChamadaFerramenta
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.dominio.portas.porta_memoria import PortaRepositorioMemoria


class MemoriaSQLite(PortaRepositorioMemoria):
    """Repositório de histórico conversacional persistido em banco SQLite seguro, concorrente e isolado por usuário."""

    def __init__(
        self, caminho_banco: str = ":memory:", timeout_segundos: float = 15.0
    ) -> None:
        self._caminho_banco = caminho_banco
        self._timeout_segundos = timeout_segundos
        self._trava = threading.Lock()
        self._conexao = sqlite3.connect(
            self._caminho_banco,
            check_same_thread=False,
            timeout=self._timeout_segundos,
        )
        self._conexao.row_factory = sqlite3.Row
        self._inicializar_banco()

    def fechar(self) -> None:
        """Encerra a conexão física com o banco de dados."""
        with self._trava:
            self._conexao.close()

    def _validar_id_conversa(self, id_conversa: str) -> None:
        """Valida que o id_conversa é seguro e não corrompe a integridade da consulta."""
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

    def _inicializar_banco(self) -> None:
        with self._trava:
            if self._caminho_banco != ":memory:":
                self._conexao.execute("PRAGMA journal_mode = WAL;")
                self._conexao.execute("PRAGMA synchronous = NORMAL;")
            self._conexao.execute(
                f"PRAGMA busy_timeout = {int(self._timeout_segundos * 1000)};"
            )

            with self._conexao:
                self._conexao.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversas_proprietarios (
                        id_conversa TEXT PRIMARY KEY,
                        id_usuario TEXT NOT NULL,
                        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                self._conexao.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mensagens_conversa (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        id_conversa TEXT NOT NULL,
                        id_usuario TEXT,
                        papel TEXT NOT NULL,
                        conteudo TEXT NOT NULL,
                        nome TEXT,
                        metadados_json TEXT,
                        chamadas_ferramentas_json TEXT,
                        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                self._conexao.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_conversa 
                    ON mensagens_conversa (id_conversa, id);
                    """
                )

    def _checar_posse_conversa(self, id_conversa: str, id_usuario: str | None) -> None:
        cursor = self._conexao.execute(
            "SELECT id_usuario FROM conversas_proprietarios WHERE id_conversa = ?;",
            (id_conversa,),
        )
        linha = cursor.fetchone()
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

    def _salvar_sincrono(
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

        with self._trava, self._conexao:
            self._checar_posse_conversa(id_conversa, id_usuario)

            if id_usuario is not None:
                self._conexao.execute(
                    """
                    INSERT OR IGNORE INTO conversas_proprietarios (id_conversa, id_usuario)
                    VALUES (?, ?);
                    """,
                    (id_conversa, id_usuario),
                )

            self._conexao.execute(
                """
                INSERT INTO mensagens_conversa (
                    id_conversa, id_usuario, papel, conteudo, nome, metadados_json, chamadas_ferramentas_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    id_conversa,
                    id_usuario,
                    mensagem.papel,
                    mensagem.conteudo,
                    mensagem.nome,
                    metadados_str,
                    chamadas_str,
                ),
            )

    def _recuperar_sincrono(
        self,
        id_conversa: str,
        limite: int | None = None,
        id_usuario: str | None = None,
    ) -> tuple[Mensagem, ...]:
        self._validar_id_conversa(id_conversa)

        consulta = """
            SELECT papel, conteudo, nome, metadados_json, chamadas_ferramentas_json
            FROM mensagens_conversa
            WHERE id_conversa = ?
            ORDER BY id ASC
        """
        parametros: list[Any] = [id_conversa]

        with self._trava:
            self._checar_posse_conversa(id_conversa, id_usuario)
            cursor = self._conexao.execute(consulta, parametros)
            linhas = cursor.fetchall()

        if limite is not None and limite > 0:
            linhas = linhas[-limite:]

        mensagens: list[Mensagem] = []
        for l in linhas:
            metadados = json.loads(l["metadados_json"] or "{}")
            chamadas_brutas = json.loads(l["chamadas_ferramentas_json"] or "[]")
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

    def _limpar_sincrono(self, id_conversa: str, id_usuario: str | None = None) -> None:
        self._validar_id_conversa(id_conversa)

        with self._trava, self._conexao:
            self._checar_posse_conversa(id_conversa, id_usuario)
            self._conexao.execute(
                "DELETE FROM mensagens_conversa WHERE id_conversa = ?;",
                (id_conversa,),
            )
            self._conexao.execute(
                "DELETE FROM conversas_proprietarios WHERE id_conversa = ?;",
                (id_conversa,),
            )

    async def salvar_mensagem(
        self, id_conversa: str, mensagem: Mensagem, id_usuario: str | None = None
    ) -> None:
        await asyncio.to_thread(
            self._salvar_sincrono, id_conversa, mensagem, id_usuario
        )

    async def recuperar_historico(
        self,
        id_conversa: str,
        limite: int | None = None,
        id_usuario: str | None = None,
    ) -> tuple[Mensagem, ...]:
        return await asyncio.to_thread(
            self._recuperar_sincrono, id_conversa, limite, id_usuario
        )

    async def limpar_historico(
        self, id_conversa: str, id_usuario: str | None = None
    ) -> None:
        await asyncio.to_thread(self._limpar_sincrono, id_conversa, id_usuario)
