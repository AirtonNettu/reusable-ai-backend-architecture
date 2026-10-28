"""Exportações dos roteadores da API HTTP."""

from ai_gateway.rotas.agentes import roteador_agentes
from ai_gateway.rotas.conclusoes import roteador_conclusoes
from ai_gateway.rotas.conversas import roteador_conversas
from ai_gateway.rotas.estruturado import roteador_estruturado
from ai_gateway.rotas.metricas import roteador_metricas
from ai_gateway.rotas.modelos import roteador_modelos
from ai_gateway.rotas.piloto import roteador_piloto
from ai_gateway.rotas.saude import roteador_saude

__all__ = [
    "roteador_agentes",
    "roteador_conclusoes",
    "roteador_conversas",
    "roteador_estruturado",
    "roteador_metricas",
    "roteador_modelos",
    "roteador_piloto",
    "roteador_saude",
]
