"""Controle de vazão, taxa de requisições e concorrência."""

import asyncio
import time
from typing import Self


class LimitadorTaxa:
    """Implementação do algoritmo Token Bucket para controle assíncrono de taxa."""

    def __init__(self, taxa_por_segundo: float, capacidade_maxima: int) -> None:
        if taxa_por_segundo <= 0:
            raise ValueError("taxa_por_segundo deve ser estritamente positiva.")
        if capacidade_maxima <= 0:
            raise ValueError("capacidade_maxima deve ser estritamente positiva.")

        self._taxa = taxa_por_segundo
        self._capacidade = float(capacidade_maxima)
        self._tokens = float(capacidade_maxima)
        self._ultima_atualizacao = time.monotonic()
        self._bloqueio = asyncio.Lock()

    async def adquirir(self, tokens_necessarios: int = 1) -> None:
        """Bloqueia assincronamente até que haja tokens suficientes disponíveis."""
        if tokens_necessarios > self._capacidade:
            raise ValueError(
                f"Demanda de {tokens_necessarios} tokens excede a capacidade total {self._capacidade}."
            )

        while True:
            async with self._bloqueio:
                agora = time.monotonic()
                decorrido = agora - self._ultima_atualizacao
                self._ultima_atualizacao = agora

                self._tokens = min(
                    self._capacidade, self._tokens + decorrido * self._taxa
                )

                if self._tokens >= tokens_necessarios:
                    self._tokens -= tokens_necessarios
                    return

                faltante = tokens_necessarios - self._tokens
                tempo_espera = faltante / self._taxa

            await asyncio.sleep(tempo_espera)


class SemaforoConcorrencia:
    """Controlador de chamadas concorrentes simultâneas via semáforo assíncrono."""

    def __init__(self, limite_simultaneo: int) -> None:
        if limite_simultaneo <= 0:
            raise ValueError("limite_simultaneo deve ser maior que zero.")
        self._semaforo = asyncio.Semaphore(limite_simultaneo)
        self._limite = limite_simultaneo

    @property
    def limite(self) -> int:
        """Número máximo de execuções simultâneas permitidas."""
        return self._limite

    async def __aenter__(self) -> Self:
        await self._semaforo.acquire()
        return self

    async def __aexit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> None:
        self._semaforo.release()


class RastreadorConsumoTokens:
    """Rastreador em memória para auditoria de consumo de tokens por modelo."""

    def __init__(self) -> None:
        self._consumo: dict[str, dict[str, int]] = {}
        self._bloqueio = asyncio.Lock()

    async def registrar(
        self, modelo: str, tokens_entrada: int, tokens_saida: int
    ) -> None:
        """Registra o consumo de tokens de forma segura para concorrência."""
        async with self._bloqueio:
            if modelo not in self._consumo:
                self._consumo[modelo] = {
                    "tokens_entrada": 0,
                    "tokens_saida": 0,
                    "total_tokens": 0,
                }
            self._consumo[modelo]["tokens_entrada"] += tokens_entrada
            self._consumo[modelo]["tokens_saida"] += tokens_saida
            self._consumo[modelo]["total_tokens"] += tokens_entrada + tokens_saida

    async def obter_relatorio(self) -> dict[str, dict[str, int]]:
        """Retorna uma cópia do relatório de consumo consolidado."""
        async with self._bloqueio:
            return {modelo: dados.copy() for modelo, dados in self._consumo.items()}
