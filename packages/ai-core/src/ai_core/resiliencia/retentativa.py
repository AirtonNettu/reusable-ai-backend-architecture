"""Política de retentativas assíncronas com backoff exponencial e jitter."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from ai_core.dominio.excecoes import (
    ErroAcessoNaoAutorizadoConversa,
    ErroAutenticacaoProvedor,
    ErroDominio,
    ErroFerramentaNaoAutorizada,
    ErroLimiteTaxa,
    ErroModeloNaoSuportado,
    ErroValidacao,
)
from ai_core.resiliencia.orcamento import ErroLimiteOrcamentoTokens

T = TypeVar("T")

registro_log = logging.getLogger(__name__)


class PoliticaRetentativa:
    """Aplica retentativas com recuo exponencial e jitter para chamadas assíncronas."""

    def __init__(
        self,
        max_tentativas: int = 3,
        atraso_inicial_segundos: float = 0.5,
        fator_multiplicador: float = 2.0,
        atraso_maximo_segundos: float = 10.0,
        usar_jitter: bool = True,
        excecoes_irrecuperaveis: tuple[type[Exception], ...] = (
            ErroAutenticacaoProvedor,
            ErroModeloNaoSuportado,
            ErroValidacao,
            ErroLimiteOrcamentoTokens,
            ErroFerramentaNaoAutorizada,
            ErroAcessoNaoAutorizadoConversa,
        ),
    ) -> None:
        self._max_tentativas = max_tentativas
        self._atraso_inicial = atraso_inicial_segundos
        self._fator = fator_multiplicador
        self._atraso_maximo = atraso_maximo_segundos
        self._usar_jitter = usar_jitter
        self._excecoes_irrecuperaveis = excecoes_irrecuperaveis

    def calcular_atraso(self, tentativa: int, erro: Exception | None = None) -> float:
        """Calcula o atraso em segundos para a tentativa informada."""
        if isinstance(erro, ErroLimiteTaxa) and erro.segundos_espera is not None:
            return float(erro.segundos_espera)

        atraso = min(
            self._atraso_maximo,
            self._atraso_inicial * (self._fator ** (tentativa - 1)),
        )

        if self._usar_jitter:
            atraso = atraso * (0.5 + random.random() * 0.5)

        return atraso

    async def executar(
        self,
        operacao: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Executa a operação com retentativas caso ocorram erros transitórios."""
        ultima_excecao: Exception | None = None

        for tentativa in range(1, self._max_tentativas + 1):
            try:
                return await operacao(*args, **kwargs)
            except Exception as erro:
                ultima_excecao = erro

                if any(
                    isinstance(erro, tipo_erro)
                    for tipo_erro in self._excecoes_irrecuperaveis
                ):
                    registro_log.warning(
                        "Exceção irrecuperável detectada (%s). Abortando retentativas.",
                        type(erro).__name__,
                    )
                    raise

                if tentativa == self._max_tentativas:
                    registro_log.error(
                        "Limite de %d tentativas excedido. Último erro: %s",
                        self._max_tentativas,
                        erro,
                    )
                    raise

                atraso = self.calcular_atraso(tentativa, erro)
                registro_log.info(
                    "Tentativa %d falhou com %s. Aguardando %.2fs antes de tentar novamente.",
                    tentativa,
                    type(erro).__name__,
                    atraso,
                )
                await asyncio.sleep(atraso)

        if ultima_excecao:
            raise ultima_excecao
        raise ErroDominio("Falha desconhecida durante execução com retentativas.")
