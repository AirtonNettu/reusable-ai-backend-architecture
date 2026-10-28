"""Exportações dos adaptadores de memória e contexto."""

from ai_core.adaptadores.memoria.compactador_contexto import CompactadorContexto
from ai_core.adaptadores.memoria.gerenciador_contexto import GerenciadorContexto
from ai_core.adaptadores.memoria.memoria_em_memoria import MemoriaEmMemoria
from ai_core.adaptadores.memoria.memoria_postgresql import MemoriaPostgresql
from ai_core.adaptadores.memoria.memoria_sqlite import MemoriaSQLite

__all__ = [
    "CompactadorContexto",
    "GerenciadorContexto",
    "MemoriaEmMemoria",
    "MemoriaPostgresql",
    "MemoriaSQLite",
]
