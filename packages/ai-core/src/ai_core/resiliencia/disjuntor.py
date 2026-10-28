"""Padrão Disjuntor (Circuit Breaker) para proteção contra falhas em cascata."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

from ai_core.dominio.excecoes import ErroDisjuntorAberto

EstadoDisjuntor = Literal["fechado", "aberto", "meio_aberto"]

T = TypeVar("T")


class Disjuntor:
    """Implementação do padrão Circuit Breaker assíncrono.

    Estados:
    - Fechado: Requisições trafegam normalmente. Falhas são contabilizadas.
    - Aberto: Requisições falham imediatamente com `ErroDisjuntorAberto`.
    - Meio-Aberto: Após intervalo de recuperação, permite requisições teste.
    """

    def __init__(
        self,
        nome: str,
        limite_falhas: int = 5,
        tempo_recuperacao_segundos: float = 30.0,
        limite_sucessos_meio_aberto: int = 2,
    ) -> None:
        self._nome = nome
        self._limite_falhas = limite_falhas
        self._tempo_recuperacao_segundos = tempo_recuperacao_segundos
        self._limite_sucessos_meio_aberto = limite_sucessos_meio_aberto

        self._estado: EstadoDisjuntor = "fechado"
        self._contador_falhas = 0
        self._contador_sucessos_meio_aberto = 0
        self._momento_ultima_falha = 0.0
        self._bloqueio = asyncio.Lock()

    @property
    def nome(self) -> str:
        """Nome do circuito."""
        return self._nome

    @property
    def estado(self) -> EstadoDisjuntor:
        """Estado atual do circuito."""
        return self._estado

    async def _atualizar_estado(self) -> None:
        """Atualiza estado interno se o tempo de recuperação tiver expirado."""
        if self._estado == "aberto":
            agora = time.monotonic()
            if agora - self._momento_ultima_falha >= self._tempo_recuperacao_segundos:
                self._estado = "meio_aberto"
                self._contador_sucessos_meio_aberto = 0

    async def executar(
        self,
        operacao: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Executa a operação protegida pelo disjuntor."""
        async with self._bloqueio:
            await self._atualizar_estado()

            if self._estado == "aberto":
                tempo_restante = self._tempo_recuperacao_segundos - (
                    time.monotonic() - self._momento_ultima_falha
                )
                raise ErroDisjuntorAberto(
                    nome_circuito=self._nome,
                    mensagem=(
                        f"Circuito '{self._nome}' aberto. "
                        f"Recuperação em {max(0.0, tempo_restante):.1f}s."
                    ),
                )

        try:
            resultado = await operacao(*args, **kwargs)
        except Exception:
            async with self._bloqueio:
                await self._registrar_falha()
            raise

        async with self._bloqueio:
            await self._registrar_sucesso()

        return resultado

    async def _registrar_sucesso(self) -> None:
        """Trata o sucesso de uma chamada."""
        if self._estado == "meio_aberto":
            self._contador_sucessos_meio_aberto += 1
            if self._contador_sucessos_meio_aberto >= self._limite_sucessos_meio_aberto:
                self._estado = "fechado"
                self._contador_falhas = 0
                self._contador_sucessos_meio_aberto = 0
        elif self._estado == "fechado":
            self._contador_falhas = 0

    async def _registrar_falha(self) -> None:
        """Trata a falha de uma chamada."""
        self._momento_ultima_falha = time.monotonic()
        if self._estado == "meio_aberto":
            self._estado = "aberto"
            self._contador_sucessos_meio_aberto = 0
        elif self._estado == "fechado":
            self._contador_falhas += 1
            if self._contador_falhas >= self._limite_falhas:
                self._estado = "aberto"
