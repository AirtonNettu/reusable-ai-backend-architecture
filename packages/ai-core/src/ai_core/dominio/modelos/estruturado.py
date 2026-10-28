"""Modelos de domínio para geração e validação de saídas estruturadas."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ResultadoSaidaEstruturada[T]:
    """Resultado da geração e validação tipada de um dado estruturado."""

    dados: T | None
    sucesso: bool
    tentativas: int = 1
    json_bruto: str = ""
    erros_validacao: tuple[str, ...] = field(default_factory=tuple)
