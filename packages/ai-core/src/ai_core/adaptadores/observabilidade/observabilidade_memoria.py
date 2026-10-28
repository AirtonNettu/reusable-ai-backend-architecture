"""Implementação em memória da porta de observabilidade e métricas."""

import threading
from dataclasses import dataclass, field
from typing import Any

from ai_core.dominio.portas.porta_observabilidade import PortaObservabilidade


@dataclass(frozen=True, slots=True)
class RegistroMetrica:
    """Dado coletado de métrica contadora ou de latência."""

    nome: str
    valor: float
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RegistroEvento:
    """Evento registrado para auditoria de ciclo de vida."""

    evento: str
    dados: dict[str, Any] = field(default_factory=dict)


class ObservabilidadeEmMemoria(PortaObservabilidade):
    """Coletor em memória para telemetria, métricas e testes automatizados."""

    def __init__(self) -> None:
        self._metricas: list[RegistroMetrica] = []
        self._latencias: list[RegistroMetrica] = []
        self._eventos: list[RegistroEvento] = []
        self._trava = threading.Lock()

    def registrar_contagem(
        self, nome: str, valor: int = 1, tags: dict[str, str] | None = None
    ) -> None:
        with self._trava:
            self._metricas.append(
                RegistroMetrica(nome=nome, valor=float(valor), tags=tags or {})
            )

    def registrar_latencia(
        self, nome: str, segundos: float, tags: dict[str, str] | None = None
    ) -> None:
        with self._trava:
            self._latencias.append(
                RegistroMetrica(nome=nome, valor=segundos, tags=tags or {})
            )

    def registrar_evento(
        self, evento: str, dados: dict[str, object] | None = None
    ) -> None:
        with self._trava:
            self._eventos.append(RegistroEvento(evento=evento, dados=dict(dados or {})))

    def obter_metricas(self) -> tuple[RegistroMetrica, ...]:
        with self._trava:
            return tuple(self._metricas)

    def obter_latencias(self) -> tuple[RegistroMetrica, ...]:
        with self._trava:
            return tuple(self._latencias)

    def obter_eventos(self) -> tuple[RegistroEvento, ...]:
        with self._trava:
            return tuple(self._eventos)

    def limpar(self) -> None:
        with self._trava:
            self._metricas.clear()
            self._latencias.clear()
            self._eventos.clear()
