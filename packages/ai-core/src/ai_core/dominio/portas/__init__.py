"""Exportações das portas de abstração do domínio."""

from ai_core.dominio.portas.porta_ferramenta import PortaExecutorFerramentas
from ai_core.dominio.portas.porta_memoria import PortaRepositorioMemoria
from ai_core.dominio.portas.porta_observabilidade import PortaObservabilidade
from ai_core.dominio.portas.porta_provedor import PortaProvedorLLM

__all__ = [
    "PortaExecutorFerramentas",
    "PortaMemoria",
    "PortaObservabilidade",
    "PortaProvedorLLM",
    "PortaRepositorioMemoria",
]
