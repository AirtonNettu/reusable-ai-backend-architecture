"""Controle orçamentário atômico e limitação de custos por volume de tokens em duas fases."""

import asyncio
import uuid
from dataclasses import dataclass

from ai_core.dominio.excecoes import ErroDominio


class ErroLimiteOrcamentoTokens(ErroDominio):
    """Lançada quando a operação excede o orçamento de tokens estabelecido."""

    def __init__(
        self,
        mensagem: str,
        tokens_solicitados: int,
        limite_configurado: int,
        id_usuario: str | None = None,
    ) -> None:
        detalhes: dict[str, object] = {
            "tokens_solicitados": tokens_solicitados,
            "limite_configurado": limite_configurado,
        }
        if id_usuario:
            detalhes["id_usuario"] = id_usuario

        super().__init__(mensagem, detalhes=detalhes)
        self.tokens_solicitados = tokens_solicitados
        self.limite_configurado = limite_configurado
        self.id_usuario = id_usuario


@dataclass(frozen=True, slots=True)
class ReservaTokens:
    """Representa uma reserva atômica de tokens retida durante a execução da chamada."""

    id_reserva: str
    tokens_estimados: int
    id_usuario: str | None = None


class PoliticaOrcamentoTokens:
    """Impõe tetos orçamentários atômicos por requisição individual, por sessão e por usuário.

    Utiliza protocolo de reserva em duas fases (Two-Phase Reservation) para prevenir
    estouro de cota decorrente de requisições concorrentes (condições de corrida / TOCTOU).
    """

    def __init__(
        self,
        limite_tokens_por_requisicao: int | None = None,
        limite_tokens_total_sessao: int | None = None,
        limite_tokens_por_usuario: int | None = None,
    ) -> None:
        self._limite_por_requisicao = limite_tokens_por_requisicao
        self._limite_total_sessao = limite_tokens_total_sessao
        self._limite_por_usuario = limite_tokens_por_usuario

        self._tokens_consumidos = 0
        self._tokens_reservados_total = 0

        self._tokens_por_usuario: dict[str, int] = {}
        self._tokens_reservados_por_usuario: dict[str, int] = {}
        self._reservas_ativas: dict[str, ReservaTokens] = {}

        self._bloqueio = asyncio.Lock()

    async def reservar_tokens(
        self, estimativa_tokens: int, id_usuario: str | None = None
    ) -> ReservaTokens:
        """Reserva atimicamente a cota estimada antes do disparo da requisição."""
        if (
            self._limite_por_requisicao is not None
            and estimativa_tokens > self._limite_por_requisicao
        ):
            raise ErroLimiteOrcamentoTokens(
                f"A estimativa de {estimativa_tokens} tokens excede o teto permitido por requisição ({self._limite_por_requisicao}).",
                tokens_solicitados=estimativa_tokens,
                limite_configurado=self._limite_por_requisicao,
                id_usuario=id_usuario,
            )

        async with self._bloqueio:
            comprometido_total = (
                self._tokens_consumidos
                + self._tokens_reservados_total
                + estimativa_tokens
            )
            if (
                self._limite_total_sessao is not None
                and comprometido_total > self._limite_total_sessao
            ):
                raise ErroLimiteOrcamentoTokens(
                    f"Consumo total projetado ({comprometido_total} tokens) excede o orçamento da sessão ({self._limite_total_sessao}).",
                    tokens_solicitados=estimativa_tokens,
                    limite_configurado=self._limite_total_sessao,
                    id_usuario=id_usuario,
                )

            if id_usuario is not None and self._limite_por_usuario is not None:
                consumido_usr = self._tokens_por_usuario.get(id_usuario, 0)
                reservado_usr = self._tokens_reservados_por_usuario.get(id_usuario, 0)
                comprometido_usr = consumido_usr + reservado_usr + estimativa_tokens
                if comprometido_usr > self._limite_por_usuario:
                    raise ErroLimiteOrcamentoTokens(
                        f"Consumo projetado para o usuário '{id_usuario}' ({comprometido_usr} tokens) excede o teto individual ({self._limite_por_usuario}).",
                        tokens_solicitados=estimativa_tokens,
                        limite_configurado=self._limite_por_usuario,
                        id_usuario=id_usuario,
                    )

            id_reserva = f"res_{uuid.uuid4().hex[:12]}"
            reserva = ReservaTokens(
                id_reserva=id_reserva,
                tokens_estimados=estimativa_tokens,
                id_usuario=id_usuario,
            )

            self._reservas_ativas[id_reserva] = reserva
            self._tokens_reservados_total += estimativa_tokens

            if id_usuario is not None:
                self._tokens_reservados_por_usuario[id_usuario] = (
                    self._tokens_reservados_por_usuario.get(id_usuario, 0)
                    + estimativa_tokens
                )

            return reserva

    async def confirmar_reserva(self, id_reserva: str, tokens_reais: int) -> None:
        """Converte a reserva em consumo efetivo com base nos tokens reais apurados."""
        async with self._bloqueio:
            reserva = self._reservas_ativas.pop(id_reserva, None)
            if reserva is not None:
                self._tokens_reservados_total -= reserva.tokens_estimados
                if reserva.id_usuario is not None:
                    atual_res = self._tokens_reservados_por_usuario.get(
                        reserva.id_usuario, 0
                    )
                    self._tokens_reservados_por_usuario[reserva.id_usuario] = max(
                        0, atual_res - reserva.tokens_estimados
                    )

                self._tokens_consumidos += tokens_reais
                if reserva.id_usuario is not None:
                    self._tokens_por_usuario[reserva.id_usuario] = (
                        self._tokens_por_usuario.get(reserva.id_usuario, 0)
                        + tokens_reais
                    )
            else:
                self._tokens_consumidos += tokens_reais

    async def cancelar_reserva(self, id_reserva: str) -> None:
        """Libera integralmente a reserva quando a chamada for abortada, falhar ou for cancelada."""
        async with self._bloqueio:
            reserva = self._reservas_ativas.pop(id_reserva, None)
            if reserva is not None:
                self._tokens_reservados_total -= reserva.tokens_estimados
                if reserva.id_usuario is not None:
                    atual_res = self._tokens_reservados_por_usuario.get(
                        reserva.id_usuario, 0
                    )
                    self._tokens_reservados_por_usuario[reserva.id_usuario] = max(
                        0, atual_res - reserva.tokens_estimados
                    )

    async def verificar_pre_requisicao(
        self, estimativa_tokens: int, id_usuario: str | None = None
    ) -> None:
        """Verifica se a requisição estimada cabe dentro dos limites configurados."""
        if (
            self._limite_por_requisicao is not None
            and estimativa_tokens > self._limite_por_requisicao
        ):
            raise ErroLimiteOrcamentoTokens(
                f"A estimativa de {estimativa_tokens} tokens excede o teto permitido por requisição ({self._limite_por_requisicao}).",
                tokens_solicitados=estimativa_tokens,
                limite_configurado=self._limite_por_requisicao,
                id_usuario=id_usuario,
            )

        async with self._bloqueio:
            comprometido = (
                self._tokens_consumidos
                + self._tokens_reservados_total
                + estimativa_tokens
            )
            if (
                self._limite_total_sessao is not None
                and comprometido > self._limite_total_sessao
            ):
                raise ErroLimiteOrcamentoTokens(
                    f"Consumo total acumulado projetado ({comprometido} tokens) excede o orçamento da sessão ({self._limite_total_sessao}).",
                    tokens_solicitados=estimativa_tokens,
                    limite_configurado=self._limite_total_sessao,
                    id_usuario=id_usuario,
                )

            if id_usuario is not None and self._limite_por_usuario is not None:
                atual_usuario = self._tokens_por_usuario.get(
                    id_usuario, 0
                ) + self._tokens_reservados_por_usuario.get(id_usuario, 0)
                if (atual_usuario + estimativa_tokens) > self._limite_por_usuario:
                    raise ErroLimiteOrcamentoTokens(
                        f"Consumo projetado para o usuário '{id_usuario}' ({atual_usuario + estimativa_tokens} tokens) excede o teto individual ({self._limite_por_usuario}).",
                        tokens_solicitados=estimativa_tokens,
                        limite_configurado=self._limite_por_usuario,
                        id_usuario=id_usuario,
                    )

    async def registrar_consumo_real(
        self, tokens_reais: int, id_usuario: str | None = None
    ) -> None:
        """Atualiza a contagem real de tokens consumidos na sessão e por usuário."""
        async with self._bloqueio:
            self._tokens_consumidos += tokens_reais
            if id_usuario is not None:
                self._tokens_por_usuario[id_usuario] = (
                    self._tokens_por_usuario.get(id_usuario, 0) + tokens_reais
                )

    async def obter_tokens_acumulados(self) -> int:
        """Retorna o total atual de tokens consumidos na sessão."""
        async with self._bloqueio:
            return self._tokens_consumidos

    async def obter_tokens_reservados(self) -> int:
        """Retorna o total de tokens atualmente comprometidos em reservas ativas."""
        async with self._bloqueio:
            return self._tokens_reservados_total

    async def obter_tokens_usuario(self, id_usuario: str) -> int:
        """Retorna o total consumido por um usuário específico."""
        async with self._bloqueio:
            return self._tokens_por_usuario.get(id_usuario, 0)

    async def obter_tokens_reservados_usuario(self, id_usuario: str) -> int:
        """Retorna os tokens reservados para um usuário específico."""
        async with self._bloqueio:
            return self._tokens_reservados_por_usuario.get(id_usuario, 0)
