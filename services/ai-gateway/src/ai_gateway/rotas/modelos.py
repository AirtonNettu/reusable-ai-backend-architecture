"""Rotas de inspeção de modelos de linguagem disponíveis."""

from typing import Annotated

from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from fastapi import APIRouter, Depends

from ai_gateway.dependencias import obter_roteador, obter_validador_autenticacao
from ai_gateway.esquemas.modelo import (
    EsquemaInformacaoModelo,
    EsquemaListaModelos,
)

roteador_modelos = APIRouter(prefix="/v1/modelos", tags=["Modelos"])


@roteador_modelos.get("", response_model=EsquemaListaModelos)
def listar_modelos(
    roteador: Annotated[RoteadorModelos, Depends(obter_roteador)],
    _autenticado: Annotated[str | None, Depends(obter_validador_autenticacao())] = None,
) -> EsquemaListaModelos:
    """Lista todos os modelos cadastrados e suas capacidades."""
    modelos = roteador.listar_modelos()
    return EsquemaListaModelos(
        dados=[
            EsquemaInformacaoModelo(
                identificador=m.identificador,
                nome_exibicao=m.nome_exibicao,
                provedor=m.provedor,
                capacidades=list(m.capacidades),
                limite_contexto=m.limite_contexto,
            )
            for m in modelos
        ]
    )
