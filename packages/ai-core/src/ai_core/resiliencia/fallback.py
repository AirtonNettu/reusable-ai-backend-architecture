"""Mecanismo de fallback controlado para chaveamento entre alternativas de execução."""

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ai_core.dominio.excecoes import ErroDominio
from ai_core.dominio.portas.porta_observabilidade import PortaObservabilidade

T = TypeVar("T")

registro_log = logging.getLogger(__name__)


class PoliticaFallback:
    """Coordena a execução encadeada de alternativas de fallback."""

    def __init__(
        self,
        excecoes_acionadoras: tuple[type[Exception], ...] = (Exception,),
        registrar_avisos: bool = True,
        observabilidade: PortaObservabilidade | None = None,
    ) -> None:
        self._excecoes_acionadoras = excecoes_acionadoras
        self._registrar_avisos = registrar_avisos
        self._observabilidade = observabilidade

    async def executar_com_retaguarda(
        self,
        operacoes: list[tuple[str, Callable[[], Awaitable[T]]]],
    ) -> T:
        """Executa a primeira operação bem-sucedida da lista de tuplas (nome, operacao)."""
        if not operacoes:
            raise ErroDominio("Nenhuma operação fornecida para política de fallback.")

        erros_acumulados: list[str] = []
        ultimo_erro: Exception | None = None

        for indice, (nome, operacao) in enumerate(operacoes):
            try:
                if indice > 0:
                    if self._registrar_avisos:
                        registro_log.warning(
                            "Ativando fallback para alternativa [%d]: %s", indice, nome
                        )
                    if self._observabilidade is not None:
                        origem = operacoes[indice - 1][0]
                        destino = nome
                        self._observabilidade.registrar_contagem(
                            "llm_fallback",
                            valor=1,
                            tags={"modelo_origem": origem, "modelo_destino": destino},
                        )

                return await operacao()
            except self._excecoes_acionadoras as erro:
                ultimo_erro = erro
                mensagem_falha = f"[{nome}]: {type(erro).__name__} - {erro}"
                erros_acumulados.append(mensagem_falha)
                registro_log.warning(
                    "Operação '%s' falhou no fallback. Motivo: %s", nome, erro
                )

        detalhe_erros = "; ".join(erros_acumulados)
        detalhes: dict[str, object] = {"erros_acumulados": erros_acumulados}

        if ultimo_erro is not None:
            tf = getattr(ultimo_erro, "tokens_faturados", None)
            if tf is not None:
                detalhes["tokens_faturados"] = tf
            if hasattr(ultimo_erro, "detalhes") and isinstance(
                ultimo_erro.detalhes, dict
            ):
                detalhes.update(ultimo_erro.detalhes)

        erro_final = ErroDominio(
            f"Todas as alternativas de fallback falharam. Detalhes: {detalhe_erros}",
            detalhes=detalhes,
        )
        if ultimo_erro is not None:
            erro_final.__cause__ = ultimo_erro

        raise erro_final
