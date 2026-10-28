"""Porta abstrata para métricas, rastreamento (tracing) e telemetria."""

from abc import ABC, abstractmethod


class PortaObservabilidade(ABC):
    """Contrato abstrato para emissão de métricas e rastreabilidade."""

    @abstractmethod
    def registrar_contagem(
        self, nome: str, valor: int = 1, tags: dict[str, str] | None = None
    ) -> None:
        """Registra incremento ou valor pontual de métrica contadora."""

    @abstractmethod
    def registrar_latencia(
        self, nome: str, segundos: float, tags: dict[str, str] | None = None
    ) -> None:
        """Registra duração temporal de uma operação."""

    @abstractmethod
    def registrar_evento(
        self, evento: str, dados: dict[str, object] | None = None
    ) -> None:
        """Registra um evento de auditoria ou rastreabilidade operacional."""
